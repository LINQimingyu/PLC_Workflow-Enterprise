"""Start only the enterprise transport, never the legacy permissive identity surface."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import webbrowser
import uvicorn
from filelock import FileLock
from .service import EnterpriseService
from .http import create_app
from .operations import Operations

ROOT=Path(__file__).resolve().parents[3]

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default=str(ROOT/'.local/config.json'));p.add_argument('--no-browser',action='store_true');args=p.parse_args()
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8'));root=Path(cfg['root']);root.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        who=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,check=True)
        sid=who.stdout.split(',')[-1].strip().strip('"')
        subprocess.run(['icacls',str(root),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F','/grant:r','*S-1-5-18:(OI)(CI)F'],capture_output=True,check=True)
    else:root.chmod(0o700);os.umask(0o077)
    with FileLock(str(root/'.enterprise.lock'),timeout=0):
        s=EnterpriseService(cfg['dsn'],root,cfg.get('environment','production'));Operations(s).recover_unknown()
        from .vendor import VendorTasks
        VendorTasks(s).recover_unknown()
        local=root/'.local';local.mkdir(mode=0o700,exist_ok=True);file=local/'setup-token'
        if not file.exists():file.write_text(secrets.token_urlsafe(40),encoding='utf-8')
        token=file.read_text(encoding='utf-8');url=cfg['origin']+'/#setup='+token
        (local/'first-login-url.txt').write_text(url,encoding='utf-8')
        app=create_app(s,cfg['origin'],token,ROOT/'app/web/dist')
        if not args.no_browser:webbrowser.open(url)
        uvicorn.run(app,host=os.environ.get('EP_BIND','127.0.0.1'),port=cfg.get('port',8774),access_log=False)

if __name__=='__main__':main()
