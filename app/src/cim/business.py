"""Deterministic estimates and version-bound verification/archival."""
from __future__ import annotations
import io
import json
import zipfile
from pathlib import Path
from . import policy
from .records import Conflict, encode, now, uid
from .tt import number


class BusinessMixin:
    def _implemented_archive_checks(self,db,p):
        """Shared read-only checks for implemented archival and its navigation."""
        blockers=[]
        if not self._engineering_current(p):
            blockers.append("关联工程版本已变化，需重新验证")
        if not p["requirements_confirmed"]:
            blockers.append("需求尚未确认")
        tasks=[t for t in self._list(db,"task",p["id"]) if t["revision"]==p["revision"]]
        reviewers={t["agent_id"] for t in tasks if t["status"]=="approved" and t["stage"]=="review"}
        if not {"program-review","process-review","evidence-review"}<=reviewers:
            blockers.append("程序、工艺与证据审查尚未全部通过")
        latest={}
        for v in sorted(self._list(db,"verification",p["id"]),key=lambda v:v["created_at"]):
            if v["revision"]==p["revision"]:
                latest[v["phase"]]=v
        for phase in ["static","compile","simulation","field"]:
            if latest.get(phase,{}).get("status") not in {"passed","not_applicable"}:
                blockers.append("验证尚未完成: "+phase)
        return blockers,latest

    def save_estimate(self,pid,expected_revision,data):
        if not isinstance(data,dict) or set(data)!={"bom","labor","daily_rate","benefit","assumptions"}:
            raise ValueError("估算字段须为 bom/labor/daily_rate/benefit/assumptions")
        unknown=[]
        cost=0.0
        for row in data["bom"]:
            if row.get("action") not in {"new","reuse","replace"} or not row.get("spec"):
                raise ValueError("BOM 需要规格及 new/reuse/replace 类型")
            quantity=number(row["quantity"],"数量",0,1e7)
            price=row.get("unit_price")
            if price is None:
                unknown.append("BOM 价格未知: "+row["spec"])
            else:
                number(price,"单价",0,1e10)
                if not row.get("source"):
                    raise ValueError("已知单价必须提供报价来源与日期")
                cost+=quantity*price
        allowed={"investigation","design","programming","testing","onsite","documentation"}
        if set(data["labor"])-allowed:
            raise ValueError("人天类别不支持")
        labor_unknown=[key for key in sorted(allowed) if data["labor"].get(key) is None]
        labor_labels={"investigation":"调查与索资","design":"方案设计","programming":"程序修改","testing":"离线测试","onsite":"现场实施与联调","documentation":"文档归档"}
        unknown.extend("人天尚未评估: "+labor_labels[key] for key in labor_unknown)
        days=sum(number(v,"人天",0,100000) for v in data["labor"].values() if v is not None)
        rate=data["daily_rate"]
        if rate is None:
            unknown.append("人工费率未知")
        else:
            cost+=days*number(rate,"人天费率",0,1e9)
        benefit=data["benefit"]
        if benefit.get("kind") not in {"estimated","measured","nonmonetary"} or not benefit.get("basis"):
            raise ValueError("收益须区分 estimated/measured/nonmonetary 并说明计算依据")
        annual=benefit.get("annual_value")
        if annual is not None:
            number(annual,"年度收益",0,1e15)
            if benefit["kind"]=="nonmonetary":
                raise ValueError("非货币收益不能填写金额")
        result={"known_cost_subtotal":cost,"total_cost":None if unknown else cost,"unknowns":unknown,
                "person_days":None if labor_unknown else days,"known_person_days":days,
                "payback_years":cost/annual if not unknown and annual and benefit["kind"]!="nonmonetary" else None,
                "decision":"insufficient_cost_data" if unknown else "requires_business_decision",
                "note":"收益为人工填报依据，系统仅核算；不自动认定已实现或值得投资"}
        with self.connect(True) as db:
            p=self._project(db,pid,expected_revision)
            if p["status"]!="active":
                raise Conflict("项目不在执行状态")
            record={"id":uid(),"project_id":pid,"revision":p["revision"],"classification":p["classification"],
                    "input":data,"result":result,"created_at":now()}
            self._put(db,"estimate",record)
            self._audit(db,pid,"estimate.saved",{"id":record["id"]})
            return record

    def verification(self,pid,expected_revision, *, phase,status,actor,record,source_ids):
        if phase not in {"static","compile","simulation","field","benefit"} or status not in {"passed","failed","not_run","not_applicable"}:
            raise ValueError("验证阶段或状态无效")
        if not actor.strip() or not record.strip() or (status=="passed" and not source_ids):
            raise ValueError("验证需要执行人、记录；通过必须附原始证据资料")
        with self.connect(True) as db:
            p=self._project(db,pid,expected_revision)
            if p["status"]!="active":
                raise Conflict("项目不在执行状态")
            evidence=[]
            level=p["classification"]
            for sid in source_ids:
                doc=self._get(db,"document",sid)
                if doc["project_id"]!=pid or doc["revoked"] or doc["kind"]!="evidence":
                    raise ValueError("验证来源必须为本项目未撤销的 evidence 资料")
                evidence.append({"source_id":sid,"sha256":doc["sha256"]})
                level=policy.inherited(level,doc["classification"])
            value={"id":uid(),"project_id":pid,"revision":p["revision"],"engineering":p["engineering"],
                   "phase":phase,"status":status,"actor":actor,"record":record,"sources":evidence,"classification":level,
                   "evidence_type":"operator_attestation","created_at":now()}
            self._put(db,"verification",value)
            self._audit(db,pid,"verification.recorded",{"id":value["id"],"phase":phase,"status":status})
            return value

    def archive(self,pid,expected_revision, *, outcome,reason,comparison,actual_investment,remaining,actor):
        if outcome not in {"implemented","not_implemented","cancelled"} or not reason.strip() or not actor.strip():
            raise ValueError("需要实施状态、原因和归档人")
        with self.connect(True) as db:
            p=self._project(db,pid,expected_revision)
            if p["status"]!="active":
                raise Conflict("项目不在执行状态")
            if outcome=="implemented":
                blockers,latest=self._implemented_archive_checks(db,p)
                if blockers:
                    raise Conflict(blockers[0])
                required={"baseline","after","metric_definition","product_recipe","window","effect_status","confounders","source_ids"}
                if not isinstance(comparison,dict) or set(comparison)!=required or comparison["effect_status"] not in {"measured","pending_observation"}:
                    raise ValueError("实施归档需要同口径前后对照或明确观察中状态")
                if any(not comparison[k] for k in ["baseline","metric_definition","product_recipe","window"]) or not isinstance(comparison["source_ids"],list):
                    raise ValueError("改前基线、指标定义、产品配方与窗口必须有内容")
                if comparison["effect_status"]=="measured":
                    if latest.get("benefit",{}).get("status")!="passed" or not comparison["source_ids"] or not comparison["after"]:
                        raise Conflict("实测收益缺少当前版本验证及原始数据")
                for sid in comparison["source_ids"]:
                    d=self._get(db,"document",sid)
                    if d["project_id"]!=pid or d["revoked"]:
                        raise ValueError("前后对照引用无效")
            value={"id":uid(),"project_id":pid,"revision":p["revision"],"outcome":outcome,"reason":reason,"comparison":comparison,
                   "actual_investment":actual_investment,"remaining":remaining,"actor":actor,"created_at":now(),"project_snapshot":p}
            self._put(db,"archive",value)
            p["status"]="cancelled" if outcome=="cancelled" else "archived"
            p["stage"]="archive"
            self._put(db,"project",p)
            self._audit(db,pid,"project.archived",{"archive":value["id"],"outcome":outcome})
            return value

    def archive_bundle(self,pid,destination="internal"):
        with self.connect() as db:
            p=self._project(db,pid)
            if p["status"] not in {"archived","cancelled"}:
                raise Conflict("项目尚未归档")
            docs=[d for d in self._list(db,"document",pid) if not d["revoked"]]
            levels=[p["classification"]]+[d["classification"] for d in docs]
            for kind in ["attempt","result","analysis","verification","estimate"]:
                for item in self._list(db,kind,pid):
                    levels.append(item.get("classification",item.get("contract",{}).get("classification","pending")))
            level=policy.inherited(*levels)
            policy.allow(level,destination)
            out=io.BytesIO()
            with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
                manifest={"classification":level,"exported_at":now(),"project":p,"documents":[self._doc_meta(d) for d in docs]}
                z.writestr("manifest.json",encode(manifest))
                z.writestr("audit.json",encode([{**dict(row),"data":json.loads(row["data"])} for row in db.execute("SELECT * FROM audit WHERE project=? ORDER BY seq",(pid,))]))
                for kind in ["task","attempt","result","analysis","estimate","verification","archive"]:
                    z.writestr(kind+".json",encode(self._list(db,kind,pid)))
                for d in docs:
                    z.writestr("files/"+d["id"]+Path(d["name"]).suffix,bytes(db.execute("SELECT content FROM blobs WHERE sha=?",(d["sha256"],)).fetchone()[0]))
            return out.getvalue()

    def publish_case(self,pid,actor,note):
        if not actor.strip() or not note.strip():
            raise ValueError("需要知识复核人及适用说明")
        with self.connect(True) as db:
            p=self._project(db,pid)
            if p["status"]!="archived":
                raise Conflict("仅已归档案例可加入厂内共享检索")
            if not p.get("equipment"):
                raise ValueError("共享案例需明确设备类型/适用设备，不能按空范围匹配")
            policy.allow(p["classification"],"internal")
            value={"id":uid(),"project_id":pid,"source_project":pid,"source_revision":p["revision"],"area":p["area"],"cpu":p["cpu"],"equipment":p["equipment"],
                   "actor":actor,"note":note,"classification":p["classification"],"status":"approved_internal_case","created_at":now()}
            self._put(db,"shared",value)
            self._audit(db,pid,"knowledge.shared",{"id":value["id"],"actor":actor})
            return value

    def withdraw_case(self,pid,share_id,actor,reason):
        if not actor.strip() or not reason.strip():
            raise ValueError("撤回共享案例需要责任人和原因")
        with self.connect(True) as db:
            share=self._get(db,"shared",share_id)
            if share["source_project"]!=pid:
                raise PermissionError("共享条目不属于本项目")
            share.update(status="withdrawn",withdrawn_by=actor,withdraw_reason=reason)
            self._put(db,"shared",share)
            affected=set()
            for a in self._list(db,"attempt"):
                if any(d.get("shared_case",{}).get("approval_id")==share_id for d in a["contract"]["input_snapshot"]["sources"]):
                    affected.add(a["project_id"])
            for target in affected:
                p=self._project(db,target)
                if p["status"] in {"active","paused"}:
                    self._bump(db,p,"knowledge.source_withdrawn")
                else:
                    self._audit(db,target,"archive.source_withdrawn",{"share_id":share_id,"requires_review":True})
            self._audit(db,pid,"knowledge.withdrawn",{"share_id":share_id,"actor":actor,"reason":reason})
            return share
