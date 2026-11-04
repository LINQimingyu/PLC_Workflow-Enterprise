"""Local factory launcher: isolated settings, no telemetry or automatic cloud jobs."""
from __future__ import annotations
import argparse
import os
import secrets
import threading
import webbrowser
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8772)
    parser.add_argument("--host",choices=("127.0.0.1","0.0.0.0"),default="127.0.0.1",
                        help="容器内使用 0.0.0.0；宿主机发布端口仍应绑定 127.0.0.1")
    parser.add_argument("--browser-port",type=int,help="浏览器访问的宿主机端口，默认与服务端口相同")
    parser.add_argument("--workspace",type=Path,default=Path(__file__).resolve().parents[3]/"workspace")
    parser.add_argument("--open-browser",action="store_true")
    args=parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error("端口范围 1024..65535")
    if args.browser_port is not None and not 1024<=args.browser_port<=65535:
        parser.error("浏览器端口范围 1024..65535")
    root=args.workspace.resolve()
    local=root/".local"
    local.mkdir(parents=True,exist_ok=True)
    from filelock import FileLock
    with FileLock(local/"factory-service.lock",timeout=0):
        run_server(args,root,local)


def run_server(args,root,local):
    # A previous process's login link must never appear ready for a new token.
    (local/"login-url.txt").unlink(missing_ok=True)
    os.environ["PLC_AI_DATA_DIR"]=str(local/"gxworks-settings")
    os.environ["HAYSTACK_TELEMETRY_ENABLED"]="false"
    os.environ["DO_NOT_TRACK"]="1"
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["TRANSFORMERS_OFFLINE"]="1"
    from integrations.web.app import create_app
    from .workbench import FactoryWorkbench
    import uvicorn
    token=secrets.token_urlsafe(32)
    origin=f"http://127.0.0.1:{args.browser_port or args.port}"
    service=FactoryWorkbench(root/"engineering",root/"engineering-state")
    # No upstream agent credential publication: native MCP remains a separate explicit configuration.
    app=create_app(root/"engineering",service=service,origin=origin,operator_token=token)
    url=origin+"/#cim?token="+token
    server=uvicorn.Server(uvicorn.Config(app,host=args.host,port=args.port,workers=1,access_log=False))
    stopped=threading.Event()
    def open_ready():
        import time
        while not stopped.wait(.1):
            if server.started:
                login_file=local/"login-url.txt"
                login_temp=local/"login-url.tmp"
                fd=os.open(login_temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(fd,"w",encoding="utf-8") as stream:
                    stream.write(url)
                login_temp.chmod(0o600)
                login_temp.replace(login_file)
                (local/"server.pid").write_text(str(os.getpid()),encoding="ascii")
                if args.open_browser:
                    webbrowser.open(url)
                return
    threading.Thread(target=open_ready,daemon=True).start()
    try:
        server.run()
    finally:
        stopped.set()


if __name__=="__main__":
    main()
