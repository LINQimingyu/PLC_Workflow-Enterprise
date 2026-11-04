"""Consistent PostgreSQL + immutable blob backup; restore only to an empty DB/new directory."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from psycopg.conninfo import conninfo_to_dict
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.file_digest(Path(path).open('rb'),'sha256').hexdigest()
def command(binary,cfg,*args):
    info=conninfo_to_dict(cfg['dsn'])
    env={**os.environ,'PGPASSWORD':info.get('password','')}
    binary_path=Path(os.environ.get('EP_PG_BIN',ROOT/'.runtime/pgsql/bin'))/(binary+('.exe' if os.name=='nt' else ''))
    result=subprocess.run([str(binary_path),'-h',info.get('host','127.0.0.1'),'-p',info.get('port','5432'),'-U',info['user'],'-d',info['dbname'],*map(str,args)],env=env,capture_output=True,timeout=180)
    if result.returncode:raise RuntimeError(binary+' failed; inspect database availability/permissions; credentials are not logged')
def backup(cfg,destination):
    root=Path(cfg['root']).resolve();dst=Path(destination).resolve()
    if dst.exists():raise ValueError('备份目标必须为新目录')
    dst.mkdir(parents=True)
    with psycopg.connect(cfg['dsn']) as c:
        c.execute('SELECT pg_advisory_xact_lock(734091553)')
        binding=c.execute("SELECT body FROM ep_records WHERE id='enterprise-storage-binding'").fetchone()[0]
        if binding['environment']!=cfg['environment'] or (root/'.storage-id').read_text(encoding='utf-8')!=binding['store_id']:raise ValueError('数据库与制品存储不配套')
        snapshot=c.execute('SELECT pg_export_snapshot()').fetchone()[0]
        command('pg_dump',cfg,'-Fc','--no-owner','--snapshot='+snapshot,'-f',dst/'database.dump')
        refs=set()
        for (body,) in c.execute("SELECT body FROM ep_records WHERE kind IN ('artifact','patch')"):
            if body.get('sha256'):refs.add(body['sha256'])
        files=[]
        for value in sorted(refs):
            source=root/'blobs'/value[:2]/value
            if sha(source)!=value:raise ValueError('制品摘要损坏，备份停止')
            out=dst/'blobs'/value[:2]/value;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,out)
            files.append({'path':str(out.relative_to(dst)).replace('\\','/'),'sha256':value})
    manifest={'schema':'enterprise-backup-1','created_at':datetime.now(timezone.utc).isoformat(),'environment':cfg['environment'],
              'database_sha256':sha(dst/'database.dump'),'files':files,'database_connection_and_model_secrets_included':False,'password_hashes_included':True,
              'note':'Database contains private records and password hashes; treat the entire backup as restricted.'}
    (dst/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
def verify(path):
    path=Path(path).resolve();manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if manifest['schema']!='enterprise-backup-1' or sha(path/'database.dump')!=manifest['database_sha256']:raise ValueError('数据库备份摘要不一致')
    for ref in manifest['files']:
        target=(path/ref['path']).resolve()
        if not target.is_relative_to(path/'blobs') or sha(target)!=ref['sha256']:raise ValueError('备份制品摘要不一致')
    return manifest
def restore(source,cfg):
    source=Path(source).resolve();manifest=verify(source);root=Path(cfg['root']).resolve()
    if root.exists():raise ValueError('恢复目标必须为全新目录；禁止覆盖工作区')
    if manifest['environment']!=cfg['environment']:raise ValueError('QA 与生产数据域不能互相恢复')
    with psycopg.connect(cfg['dsn']) as c:
        if c.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]:raise ValueError('恢复数据库必须为空')
    command('pg_restore',cfg,'--no-owner','--no-privileges',source/'database.dump')
    root.mkdir(parents=True);shutil.copytree(source/'blobs',root/'blobs',dirs_exist_ok=True)
    # Do not restore live sessions or dispatch active model/vendor jobs.
    with psycopg.connect(cfg['dsn']) as c:
        c.execute('DELETE FROM ep_sessions')
        c.execute("""UPDATE ep_records SET body=jsonb_set(body,'{auth_epoch}',to_jsonb((body->>'auth_epoch')::int+1)) WHERE kind='project'""")
        c.execute("""UPDATE ep_records SET body=jsonb_set(body,'{revoked}','true'::jsonb) WHERE kind='grant'""")
        c.execute("""UPDATE ep_records SET body=jsonb_set(body,'{status}','"unknown"'::jsonb) WHERE kind IN ('operation','job') AND body->>'status' IN ('queued','running')""")
        binding=c.execute("SELECT body FROM ep_records WHERE id='enterprise-storage-binding'").fetchone()[0]
        (root/'.storage-id').write_text(binding['store_id'],encoding='utf-8')
    return {'restored':True,'sessions_removed':True,'permissions_revalidation_required':True,'jobs_dispatched':False}
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['backup','verify','restore']);p.add_argument('--config');p.add_argument('--path',required=True);a=p.parse_args()
    if a.action=='verify':verify(a.path);print('Backup hashes verified');return
    if not a.config:raise SystemExit('--config required')
    cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
    if a.action=='backup':backup(cfg,a.path);print('Restricted backup saved; do not include it in source releases')
    else:print(json.dumps(restore(a.path,cfg)))
if __name__=='__main__':main()
