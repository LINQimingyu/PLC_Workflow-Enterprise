"""Exercise mounted credentials and the actual container-style launcher."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from cim.planner import PlannerError
from cim.service import FactoryService


def test_mounted_key_is_endpoint_bound_readonly_and_absent_from_records(tmp_path, monkeypatch):
    key_file = tmp_path / "planner-secret"
    key_file.write_text("synthetic-mounted-credential\n", encoding="utf-8")
    monkeypatch.setenv("PLC_WORKFLOW_PLANNER_KEY_FILE", str(key_file))
    monkeypatch.setenv("PLC_WORKFLOW_PLANNER_KEY_BASE_URL", "https://api.deepseek.com/")
    service = FactoryService(tmp_path / "business")
    settings = service.planner.settings()
    assert settings["key_read_only"] and settings["has_key"]
    for changes in ({"api_key": "replacement"}, {"clear_key": True}):
        with pytest.raises(PlannerError, match="只读"):
            service.planner.save_settings(changes)
    assert key_file.read_text(encoding="utf-8") == "synthetic-mounted-credential\n"
    assert service.planner.save_settings({"model": "configured-model"})["has_key"]
    assert not service.planner.save_settings({"provider": "compatible", "base_url": "https://another.invalid/v1"})["has_key"]
    with service.connect() as db:
        assert "synthetic-mounted-credential" not in "\n".join(db.iterdump())
    key_file.write_text("invalid\nmultiline", encoding="utf-8")
    assert not service.planner.save_settings({"provider": "deepseek", "base_url": "https://api.deepseek.com"})["has_key"]


def test_container_launcher_preserves_host_checks_login_and_data_on_restart(tmp_path):
    app = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # Deliberately differs from the service port, as with a Compose port mapping.
    browser_port = 18772 if port != 18772 else 18773
    origin = f"http://127.0.0.1:{browser_port}"
    workspace = tmp_path / "data"
    key_file = tmp_path / "empty-secret"
    key_file.write_text("", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(app / "src"), "PLC_WORKFLOW_PLANNER_KEY_FILE": str(key_file)}
    command = [sys.executable, "-m", "cim.launch", "--host", "0.0.0.0", "--port", str(port),
               "--browser-port", str(browser_port), "--workspace", str(workspace)]
    project_id = None
    previous_token = None
    for _ in range(2):
        process = subprocess.Popen(command, cwd=app, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Host": f"127.0.0.1:{browser_port}"}, trust_env=False) as client:
                for _ in range(160):
                    assert process.poll() is None, "Launcher exited before becoming ready"
                    try:
                        ready = client.get("/api/health").status_code == 200
                        if ready and (workspace / ".local/login-url.txt").is_file():
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    pytest.fail("Launcher did not become ready")
                assert client.get("/api/health", headers={"Host": "untrusted.invalid"}).status_code == 403
                assert client.get("/api/cim/projects").status_code == 401
                url = (workspace / ".local/login-url.txt").read_text(encoding="utf-8")
                assert url.startswith(origin + "/#cim?token=")
                token = parse_qs(urlsplit(url).fragment.split("?", 1)[1])["token"][0]
                assert token != previous_token
                if previous_token:
                    assert client.post("/api/session", json={"token": previous_token}).status_code == 403
                session = client.post("/api/session", json={"token": token}).json()
                headers = {"Origin": origin, "x-csrf-token": session["csrf"]}
                assert client.post("/api/cim/projects", json={"name": "blocked"}).status_code == 403
                assert len(client.get("/api/cim/catalog").json()["agents"]) == 34
                assert client.get("/api/cim/planner/settings").json()["key_read_only"]
                if project_id:
                    assert client.get(f"/api/cim/projects/{project_id}").json()["project"]["name"] == "Container restart fixture"
                else:
                    result = client.post("/api/cim/projects", json={"name": "Container restart fixture"}, headers=headers)
                    assert result.status_code == 201
                    project_id = result.json()["id"]
                previous_token = token
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
