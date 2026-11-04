"""Human-accepted knowledge, live provenance checks, local hybrid retrieval."""
import json
import math
import os
import subprocess
import sys
import hashlib
from pathlib import Path
from cim.records import uid,now,encode,Conflict
from cim.registry import digest
from cim.retrieval import terms
from cim import policy

class Knowledge:
    def __init__(self,service): self.s=service

    def enqueue(self,db,p,m,d,actor):
        old=next((k for k in self.s._list(db,"knowledge",p["id"]) if k["deliverable_id"]==d["id"]),None)
        if old: return old
        text=d["result"]["summary"]+"\n"+"\n".join(a["name"]+"\n"+a["content"] for a in d["result"]["artifacts"])
        chunks=[{"location":f"paragraph:{i+1}","text":t[j:j+600]} for i,t in enumerate(text.splitlines()) if t.strip() for j in range(0,len(t),500)]
        k={"id":uid(),"project_id":p["id"],"deliverable_id":d["id"],"module_id":m["id"],"module_version":m["version"],"title":p["name"]+" · "+m["label"],
           "cpu":p["cpu"],"area":p["area"],"equipment":p["equipment"],"classification":d["classification"],"sources":d["sources"],"knowledge_ids":d["knowledge_ids"],
           "status":"accepted","accepted_by":actor,"verification":self.s._list(db,"verification",p["id"]),"chunks":chunks,"sha256":digest(text),"index_status":"pending","created_at":now()}
        self.s._put(db,"knowledge",k)
        self.s._put(db,"outbox",{"id":uid(),"project_id":p["id"],"kind":"index","knowledge_id":k["id"],"status":"queued","created_at":now()})
        return k

    def usable(self,db,kid,target,seen=None):
        seen=set() if seen is None else seen
        if kid in seen: raise Conflict("知识引用循环")
        seen.add(kid)
        k=self.s._get(db,"knowledge",kid)
        if k["status"]!="accepted" or k["cpu"]!=target["cpu"] or k["area"]!=target["area"] or k["equipment"]!=target["equipment"]: raise PermissionError("知识已撤回或不适用当前设备/CPU")
        source=self.s._project(db,k["project_id"])
        m=self.s._get(db,"module",k["module_id"])
        if m["version"]!=k["module_version"]: raise PermissionError("来源模块已经变更，知识待重新确认")
        levels=[k["classification"],source["classification"]]
        for ref in k["sources"]:
            d=self.s._get(db,"document",ref["id"])
            if d["revoked"] or d["sha256"]!=ref["sha256"]: raise PermissionError("知识来源已撤回")
            levels.append(d["classification"])
        for parent in k["knowledge_ids"]: levels.append(self.usable(db,parent,target,seen.copy())["classification"])
        k["classification"]=policy.inherited(*levels)
        policy.allow(k["classification"],"internal")
        return k

    def withdraw(self,kid,actor,reason):
        if not actor.strip() or not reason.strip(): raise ValueError("撤回需要责任人与依据")
        with self.s.connect(True) as db:
            k=self.s._get(db,"knowledge",kid); k.update(status="withdrawn",withdrawn_by=actor,reason=reason); self.s._put(db,"knowledge",k)
            impacted={kid}
            while True:
                expanded=impacted|{item['id'] for item in self.s._list(db,'knowledge') if set(item['knowledge_ids'])&impacted}
                if expanded==impacted: break
                impacted=expanded
            for p in self.s._list(db,"project"):
                affected=[m["key"] for m in self.s._list(db,"module",p["id"]) if set(m["knowledge_ids"])&impacted]
                if affected: self.s._invalidate(db,p,affected,"引用知识已撤回")
            self.s._event(db,k["project_id"],"v3.knowledge.withdrawn",knowledge_id=kid,actor=actor)
            return k

    def embedding_settings(self):
        with self.s.connect() as db:
            rows=self.s._list(db,"embedding_settings")
            return rows[0] if rows else {"id":"local","python":"","model_dir":"","mode":"keyword","fingerprint":None}

    def configure(self,python,model_dir):
        exe=Path(python).resolve(); model=Path(model_dir).resolve()
        if not exe.is_file() or not model.is_dir() or not (model/"config.json").is_file(): raise ValueError("请选择已准备的 Python 与本地模型目录")
        files=[]
        for x in sorted(model.rglob('*')):
            if x.is_file() and '.cache' not in x.parts:
                with x.open('rb') as stream: files.append((str(x.relative_to(model)),hashlib.file_digest(stream,'sha256').hexdigest()))
        cfg={"id":"local","python":str(exe),"model_dir":str(model),"mode":"semantic","fingerprint":digest(files)}
        self.encode(["离线检索能力检查"],cfg)
        with self.s.connect(True) as db: self.s._put(db,"embedding_settings",cfg,"_settings")
        return cfg

    def encode(self,texts,cfg=None):
        cfg=cfg or self.embedding_settings()
        if cfg["mode"]!="semantic": return None
        env={**os.environ,"HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1","DO_NOT_TRACK":"1","TOKENIZERS_PARALLELISM":"false"}
        worker=Path(__file__).with_name("embedding_worker.py")
        r=subprocess.run([cfg["python"],str(worker),cfg["model_dir"]],input=encode(texts),text=True,encoding="utf-8",capture_output=True,timeout=180,env=env)
        if r.returncode: raise ValueError("本地 embedding 未就绪，请检查独立运行环境")
        v=json.loads(r.stdout)
        if len(v)!=len(texts) or any(not isinstance(row,list) or not row or any(not isinstance(x,(float,int)) or not math.isfinite(x) for x in row) for row in v): raise ValueError("本地向量响应无效")
        return v

    def process_index(self):
        with self.s.connect(True) as db:
            jobs=[j for j in self.s._list(db,"outbox") if j["kind"]=="index" and j["status"]=="queued"]
            if not jobs: return False
            job=jobs[0]; job["status"]="running"; self.s._put(db,"outbox",job)
            k=self.s._get(db,"knowledge",job["knowledge_id"])
        try:
            cfg=self.embedding_settings(); vectors=self.encode([c["text"] for c in k["chunks"]],cfg) if k["chunks"] else []
            with self.s.connect(True) as db:
                latest=self.s._get(db,"knowledge",k["id"])
                latest.update(vectors=vectors,embedding_fingerprint=cfg["fingerprint"],index_status="semantic" if vectors else "keyword")
                self.s._put(db,"knowledge",latest); job["status"]="completed"; self.s._put(db,"outbox",job)
        except Exception:
            with self.s.connect(True) as db:
                k=self.s._get(db,"knowledge",k["id"]); k["index_status"]="failed"; self.s._put(db,"knowledge",k); job["status"]="failed"; self.s._put(db,"outbox",job)
        return True

    def reindex(self):
        with self.s.connect(True) as db:
            for k in self.s._list(db,"knowledge"):
                if k["status"]!="accepted": continue
                self.s._put(db,"outbox",{"id":uid(),"project_id":k["project_id"],"kind":"index","knowledge_id":k["id"],"status":"queued","created_at":now()})
        return {"queued":True}

    def search(self,pid,query,destination="internal",limit=8):
        if not query.strip() or len(query)>500 or not 1<=limit<=30: raise ValueError("查询无效")
        cfg=self.embedding_settings(); qv=None; error=None
        try:
            v=self.encode([query],cfg); qv=v[0] if v else None
        except Exception: error="语义检索暂不可用，当前使用关键词"
        q=terms(query); hits=[]
        with self.s.connect() as db:
            p=self.s._project(db,pid); policy.allow(p["classification"],destination)
            for raw in self.s._list(db,"knowledge"):
                try: k=self.usable(db,raw["id"],p); policy.allow(k["classification"],destination)
                except (PermissionError,Conflict): continue
                for i,c in enumerate(k["chunks"]):
                    lex=len(q&terms(c["text"]))/max(1,len(q))
                    sem=None
                    if qv and k.get("embedding_fingerprint")==cfg["fingerprint"] and k.get("vectors") and len(k["vectors"][i])==len(qv): sem=sum(a*b for a,b in zip(qv,k["vectors"][i]))
                    if lex or (sem is not None and sem>=.4): hits.append({"knowledge_id":k["id"],"title":k["title"],"sha256":k["sha256"],**c,"classification":k["classification"],"verification":k["verification"],"lexical":lex,"semantic":sem})
        lex=sorted([h for h in hits if h["lexical"]],key=lambda h:h["lexical"],reverse=True)[:20]
        sem=sorted([h for h in hits if h["semantic"] is not None],key=lambda h:h["semantic"],reverse=True)[:20]
        scores={}
        for ranklist in [lex,sem]:
            for rank,h in enumerate(ranklist,1):
                key=(h["knowledge_id"],h["location"]); scores[key]=scores.get(key,0)+1/(60+rank)
        hits.sort(key=lambda h:scores.get((h["knowledge_id"],h["location"]),0),reverse=True)
        semantic_used=any(h['semantic'] is not None for h in hits)
        if qv and not semantic_used and error is None: error='未找到当前版本的适用语义索引；当前结果来自关键词'
        return {"mode":"hybrid" if semantic_used else "keyword","warning":error,"hits":hits[:limit],"generative_answer":False}
