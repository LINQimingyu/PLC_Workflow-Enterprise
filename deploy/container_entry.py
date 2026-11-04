"""Create a private runtime config from read-only secrets, then run enterprise only."""
import json,os,sys,time
from pathlib import Path
from psycopg.conninfo import make_conninfo
import psycopg
root=Path('/data');local=root/'.local';local.mkdir(mode=0o700,exist_ok=True)
password=Path('/run/secrets/app_password').read_text().strip()
dsn=make_conninfo(host='db',port=5432,user='ep_app',password=password,dbname='plc_enterprise')
for attempt in range(30):
    try:
        with psycopg.connect(dsn):pass
        break
    except psycopg.OperationalError:
        if attempt==29:raise RuntimeError('Enterprise PostgreSQL is unavailable') from None
        time.sleep(1)
config=local/'config.json'
config.write_text(json.dumps({'dsn':dsn,'root':'/data/workspace','environment':'production','origin':'http://127.0.0.1:8774','port':8774}))
config.chmod(0o600)
os.execv(sys.executable,[sys.executable,'-m','factory_enterprise.launch','--config',str(config),'--no-browser'])
