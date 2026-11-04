"""Bounded deterministic operations, private backups and readiness reports."""
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from cim.records import uid,now,Conflict
from cim.registry import digest

def tool(service,pid,grant_id,name,arguments,request_id):
    allowed={"plc.inspect_csv":"csv-inspect","plc.compare_csv":"csv-compare","tt.analyze":"tt-analyze","tt.simulate":"simulate","business.estimate":"estimate"}
    if name not in allowed or not isinstance(arguments,dict) or not 8<=len(request_id)<=100: raise ValueError("工具字段无效")
    with service.connect(True) as db:
        p=service._project(db,pid); g=service._owned(db,"grant",grant_id,pid); module=service._valid_grant(db,p,g)
        if g['purpose']!='execute' or module['status'] not in {'waiting_return','running'}: raise Conflict('模块当前不接受工具执行')
        if name not in g["tools"] or g["tool_calls"]>=g["max_tools"]: raise PermissionError("工具未授权或已达上限")
        if g["mode"]=="api":
            c=service.runtime.connection(db,g["connection_id"])
            if c["destination"]=="external": raise PermissionError("外部模型不挂载厂内工具")
        fingerprint=digest([grant_id,name,arguments])
        for old in service._list(db,"operation",pid):
            if old["request_id"]==request_id:
                if old["fingerprint"]!=fingerprint: raise Conflict("幂等键参数不同")
                if old["status"]!="completed": raise Conflict("工具结果未核实，禁止自动重复")
                return old
        refs=set(arguments.get("source_ids",[]))|{v for k,v in arguments.items() if k in {"source_id","before_id","after_id","comment_source_id"} and v}
        if not refs<={d["id"] for d in g["contract"]["sources"]}: raise PermissionError("工具输入超出授权资料")
        op={"id":uid(),"project_id":pid,"grant_id":grant_id,"request_id":request_id,"fingerprint":fingerprint,"tool":name,"status":"running","created_at":now()}
        g["tool_calls"]+=1; service._put(db,"grant",g); service._put(db,"operation",op)
    from cim.commands import invoke
    try:
        result=invoke(service,pid,allowed[name],{"expected_revision":p["revision"],**arguments})
        with service.connect(True) as db:
            service._valid_grant(db,service._project(db,pid),service._get(db,"grant",grant_id))
            op.update(status="completed",record_id=result["id"],record=result); service._put(db,"operation",op)
        return op
    except Exception:
        with service.connect(True) as db: op["status"]="unknown"; service._put(db,"operation",op)
        raise

def health(service):
    with service.connect() as db:
        db.execute("SELECT 1").fetchone()
        cfg=service.knowledge.embedding_settings()
        return {"application":"plc-workflow-v3","database":"ready","worker":"ready" if service.runtime.thread and service.runtime.thread.is_alive() else "stopped",
                "embedding":cfg["mode"],"free_bytes":shutil.disk_usage(service.root).free,
                "native_validation":"inspect engineering capability; no field evidence inferred"}

def backup(service,kind='manual'):
    if kind not in {'manual','daily','preupgrade'}: raise ValueError('备份类别无效')
    root=service.root.parent/"backups"; root.mkdir(parents=True,exist_ok=True)
    key=uid(); destination=root/(key+".sqlite3")
    with sqlite3.connect(service.db) as source, sqlite3.connect(destination) as target: source.backup(target)
    with sqlite3.connect(destination) as target:
        if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError("备份一致性检查失败")
    sha=hashlib.sha256(destination.read_bytes()).hexdigest()
    # Evidence blobs, module results and knowledge live in the same SQLite snapshot.
    manifest={"id":key,"created_at":now(),"kind":kind,"database_sha256":sha,"schema":"factory-v3","credentials_included":False,"files":"原件/成果以数据库 blob/记录保存","restore_status":"not_rehearsed"}
    destination.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    if kind!='manual':
        candidates=[]
        for f in root.glob('*.manifest.json'):
            try: item=json.loads(f.read_text(encoding='utf-8'))
            except (ValueError,OSError): continue
            if item.get('kind')==kind: candidates.append((item['created_at'],f))
        for _,f in sorted(candidates,reverse=True)[7 if kind=='daily' else 3:]:
            old=f.with_name(f.name.replace('.manifest.json','.sqlite3'))
            if old.resolve().parent!=root.resolve() or f.resolve().parent!=root.resolve(): raise PermissionError('备份清理路径越界')
            old.unlink(missing_ok=True); f.unlink()
    return manifest

def restore_check(path,target):
    """Restore only to a new isolated folder. No login sessions or model dispatch."""
    path=Path(path).resolve(); target=Path(target).resolve()
    if target.exists(): raise ValueError("恢复目标必须是不存在的独立目录")
    manifest=json.loads(path.with_suffix('.manifest.json').read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest["database_sha256"]: raise ValueError("备份哈希不符")
    target.mkdir(parents=True); shutil.copy2(path,target/"factory.sqlite3")
    with sqlite3.connect(target/"factory.sqlite3") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ValueError("恢复库检查失败")
        for sha,raw in db.execute("SELECT sha,content FROM blobs"):
            if hashlib.sha256(raw).hexdigest()!=sha: raise ValueError("原件哈希异常")
    return {"restored":True,"model_requests_sent":0}
