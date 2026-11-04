"""Cloud usage packages retain current classification checks and the return contract."""
import io
import json
import zipfile

import pytest

from cim.service import FactoryService


def test_public_handoff_bundle_is_usable_but_current_internal_source_blocks_export(tmp_path):
    service = FactoryService(tmp_path / "business")
    project = service.create_project("Public synthetic handoff", classification="public", requirements="Synthetic scope only")
    document = service.add_document(project["id"], 1, "public.txt", b"synthetic evidence only", classification="public")
    tasks = service.plan_tasks(project["id"], 2)
    task = next(item for item in tasks if item["stage"] == "requirements")
    attempt = service.start_attempt(project["id"], task["id"], "external-usage-fixture")
    raw = service.bundle(project["id"], attempt["id"], "external")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "external/public" in archive.read("INSTRUCTIONS.md").decode()
        result = json.loads(archive.read("return-template.json"))
        assert all(result[key] == attempt["contract"][key] for key in
                   ("project_id", "task_id", "attempt_id", "input_revision", "snapshot_hash"))
        result["summary"] = "Synthetic evidence needs engineering review"
        result["verdict"] = "candidate"
    returned = service.submit_result(project["id"], result)
    assert not returned["accepted"] and not returned["stale"]
    service.classify_document(project["id"], document["id"], 2, "internal", "fixture-owner", "source is now internal")
    with pytest.raises(PermissionError):
        service.bundle(project["id"], attempt["id"], "external")
