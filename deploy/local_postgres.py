"""Project-local PostgreSQL, loopback + SCRAM; never installs a Windows service."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import hashlib
import urllib.request
import zipfile
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime'
BIN=RUNTIME/'pgsql/bin'
DATA=RUNTIME/'pgdata'

def run(*args):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if p.returncode: raise RuntimeError('PostgreSQL 操作失败：'+p.stderr[-1200:])
    return p

def protect(path):
    if os.name=='nt':
        sid=run('whoami','/user','/fo','csv','/nh').stdout.split(',')[-1].strip().strip('"')
        run('icacls',path,'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F','/grant:r','*S-1-5-18:(OI)(CI)F')

def ensure_binaries():
    if (BIN/'postgres.exe').exists(): return
    RUNTIME.mkdir(exist_ok=True);protect(RUNTIME)
    url='https://get.enterprisedb.com/postgresql/postgresql-18.6-1-windows-x64-binaries.zip'
    archive=RUNTIME/'postgresql-18.6-1-windows-x64-binaries.zip'
    urllib.request.urlretrieve(url,archive)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.startswith(('pgsql/bin/','pgsql/lib/','pgsql/share/')) and not name.endswith('/'):z.extract(name,RUNTIME)
    (RUNTIME/'postgres-provenance.json').write_text(json.dumps({'url':url,'sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),'version':'18.6-1'},indent=2))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--qa',action='store_true');parser.add_argument('--stop',action='store_true');args=parser.parse_args()
    if args.stop:
        run(BIN/'pg_ctl.exe','-D',DATA,'-m','fast','-w','stop');print('PostgreSQL stopped');return
    ensure_binaries();local=ROOT/'.local';local.mkdir(exist_ok=True);protect(local);protect(RUNTIME)
    cfg_file=local/'postgres-admin.json'
    if not DATA.exists():
        password=secrets.token_urlsafe(36);pw=local/'init-password.tmp';pw.write_text(password,encoding='utf-8')
        try:run(BIN/'initdb.exe','-D',DATA,'-U','postgres','--pwfile',pw,'--auth=scram-sha-256','--encoding=UTF8','--locale=C')
        finally:pw.unlink(missing_ok=True)
        with (DATA/'postgresql.conf').open('a',encoding='utf-8') as f:f.write("\nlisten_addresses='127.0.0.1'\nport=5544\npassword_encryption='scram-sha-256'\n")
        cfg_file.write_text(json.dumps({'password':password}),encoding='utf-8')
    admin=json.loads(cfg_file.read_text(encoding='utf-8'))
    check=subprocess.run([str(BIN/'pg_ctl.exe'),'-D',str(DATA),'status'],capture_output=True)
    if check.returncode:
        # PostgreSQL descendants can inherit pipe handles on Windows; do not capture start pipes.
        subprocess.run([str(BIN/'pg_ctl.exe'),'-D',str(DATA),'-l',str(RUNTIME/'postgres.log'),'-w','start'],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=60)
    dbname='plc_enterprise_qa' if args.qa else 'plc_enterprise'
    role='ep_qa' if args.qa else 'ep_app'
    config=ROOT/'.qa/config.json' if args.qa else local/'config.json';config.parent.mkdir(exist_ok=True)
    if config.exists():print('PostgreSQL ready; configuration: '+str(config));return
    pwd=secrets.token_urlsafe(36)
    with psycopg.connect(host='127.0.0.1',port=5544,user='postgres',password=admin['password'],dbname='postgres',autocommit=True) as c:
        if not c.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
            c.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(pwd)))
        else:raise RuntimeError('角色已存在但配置缺失，需要恢复配置，禁止静默重置密码')
        c.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(dbname),sql.Identifier(role)))
    root=ROOT/'.qa/data' if args.qa else ROOT/'workspace'
    config.write_text(json.dumps({'dsn':make_conninfo(host='127.0.0.1',port=5544,user=role,password=pwd,dbname=dbname),'root':str(root),
                                 'environment':'qa' if args.qa else 'production','origin':'http://127.0.0.1:8774','port':8774},indent=2),encoding='utf-8')
    protect(config.parent)
    print('PostgreSQL ready; configuration: '+str(config))

if __name__=='__main__':main()
