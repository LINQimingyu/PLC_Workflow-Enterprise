"""Create an empty isolated QA DB for browser regression. No production workspace reads."""
import json,secrets
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
ROOT=Path(__file__).resolve().parents[1]
base=json.loads((ROOT/'.qa/config.json').read_text(encoding='utf-8'))
assert base['environment']=='qa' and 'plc_enterprise_qa' in base['dsn']
admin=json.loads((ROOT/'.local/postgres-admin.json').read_text(encoding='utf-8'))
dbname='plc_enterprise_qa_browser_'+secrets.token_hex(6)
with psycopg.connect(host='127.0.0.1',port=5544,user='postgres',password=admin['password'],dbname='postgres',autocommit=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {} OWNER ep_qa').format(sql.Identifier(dbname)))
root=ROOT/'.qa'/dbname;root.mkdir(parents=True)
config={**base,'dsn':make_conninfo(base['dsn'],dbname=dbname),'root':str(root/'data'),'origin':'http://127.0.0.1:18774','port':18774}
(root/'config.json').write_text(json.dumps(config),encoding='utf-8')
print(str(root/'config.json'))
