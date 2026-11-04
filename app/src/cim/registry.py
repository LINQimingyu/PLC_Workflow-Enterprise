from __future__ import annotations
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[2]


def agent_stage(agent):
    aid=agent["id"]
    return ("requirements" if aid in {"requirements","coordinator"} else "baseline" if aid=="baseline" else
            "proposal" if aid=="feasibility" else "archive" if aid=="archive" else
            "review" if agent["category"]=="assurance" else "analysis")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Registry:
    def __init__(self, root=APP):
        self.root = Path(root)
        self.agents = self._load("agents", "agent.json")
        self.skills = self._load("skills", "skill.json")
        self.packs = self._load("process-packs", "pack.json")
        self.validate()

    def _load(self, directory, filename):
        result = {}
        for path in sorted((self.root / directory).rglob(filename)):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["id"] in result:
                raise ValueError("重复目录 ID: " + value["id"])
            value["path"] = path.relative_to(self.root).as_posix()
            result[value["id"]] = value
        return result

    def validate(self):
        from jsonschema import Draft202012Validator
        for item in self.agents.values():
            if not set(item["skills"]) <= self.skills.keys():
                raise ValueError("Agent 引用了不存在的 Skill: " + item["id"])
            if item["execution"] not in {"manual_internal", "deterministic"}:
                raise ValueError("未验证的执行器")
            if not set(item["tools"]) <= {"knowledge.search","evidence.read","plc.inspect_csv","plc.compare_csv","tt.analyze","tt.simulate","business.estimate"}:
                raise ValueError("专家定义包含未开放的工具权限")
        for skill in self.skills.values():
            if not (self.root / skill["path"]).with_name("SKILL.md").is_file():
                raise ValueError("Skill 缺少入口")
        schema=json.loads((self.root/"process-packs/schema.json").read_text(encoding="utf-8"))
        for pack in self.packs.values():
            Draft202012Validator(schema).validate({k:v for k,v in pack.items() if k!="path"})
            if not set(pack["agents"])<=self.agents.keys():
                raise ValueError("工艺包引用了不存在的专家")
            source_ids={s["id"] for s in pack["sources"]}
            for section in ["constraints","steps","recipes","confirmed_facts"]:
                if any(row["source_id"] not in source_ids for row in pack[section]):
                    raise ValueError("工艺约束缺少包内明确来源")

    def snapshot(self, agent_id):
        agent = self.agents[agent_id]
        skills = [{**self.skills[x], "instructions": (self.root / self.skills[x]["path"]).with_name("SKILL.md").read_text(encoding="utf-8")} for x in agent["skills"]]
        return {"agent": agent, "skills": skills, "sha256": digest([agent, skills])}

    @staticmethod
    def scope_signature(project):
        return digest({key:project.get(key,"") for key in ("scenario","area","cpu","equipment")})

    def configuration(self,project,agent_ids=(),pack_ids=()):
        if not isinstance(agent_ids,list) or not isinstance(pack_ids,list) or len(agent_ids)>64 or len(pack_ids)>16:
            raise ValueError("专家和工艺包须为目录 ID 列表")
        for aid in agent_ids:
            if not isinstance(aid,str) or aid not in self.agents:
                raise ValueError("专家不在当前目录中")
            a=self.agents[aid]
            if a["category"]=="process" and project["area"] not in a["areas"] and "FA" not in a["areas"]:
                raise ValueError("工艺专家与项目工段不匹配")
            if aid in {"mitsubishi-q","mitsubishi-r"} and not project["cpu"].upper().startswith(aid[-1].upper()):
                raise ValueError("PLC 专家与 CPU 不匹配")
        for pack_id in pack_ids:
            if not isinstance(pack_id,str) or pack_id not in self.packs or self.packs[pack_id]["area"]!=project["area"]:
                raise ValueError("工艺包不在当前工段目录中")
        return {"agent_ids":list(dict.fromkeys(agent_ids)),"pack_ids":list(dict.fromkeys(pack_ids)),
                "scope_signature":self.scope_signature(project)}

    def route(self, project):
        """Deterministic eligibility before any specialist interpretation."""
        scenario, area, cpu = project["scenario"], project["area"], project["cpu"].upper()
        selected = ["coordinator", "requirements", "baseline", "feasibility", "archive"]
        if scenario == "fdc":
            selected += ["cim-fdc", "sequence", "pneumatic-vacuum"]
        elif scenario == "tt":
            selected += ["tt-capacity", "bottleneck", "buffer-flow", "dispatch", "uptime"]
        else:
            selected += ["sequence", "electrical", "hmi"]
        if cpu.startswith("Q"):
            selected.append("mitsubishi-q")
        elif cpu.startswith("R"):
            selected.append("mitsubishi-r")
        candidates = [a for a in self.agents.values() if a["category"] == "process" and (area in a["areas"] or "FA" in a["areas"])]
        # A named equipment match chooses experts; otherwise ask for equipment, no arbitrary routing.
        matches = [a["id"] for a in candidates if any(k.lower() in project.get("equipment", "").lower() for k in a["equipment_keywords"])]
        selected += matches
        selected += ["program-review", "process-review", "evidence-review"]
        missing=([] if matches else ["设备类型不足：工艺专家暂未自动选定"])
        packs=[]
        configuration=project.get("configuration")
        if configuration:
            if configuration.get("scope_signature")==self.scope_signature(project):
                self.configuration(project,configuration["agent_ids"],configuration["pack_ids"])
                selected+=configuration["agent_ids"]
                packs=[self.packs[pid] for pid in configuration["pack_ids"]]
            else:
                missing.append("项目设备或 CPU 已变化，原项目创建配置已失效；当前采用基础路由")
        snapshots=[self.snapshot(x) for x in dict.fromkeys(selected)]
        if packs:
            for snapshot in snapshots:
                snapshot["process_packs"]=packs
                snapshot["sha256"]=digest({k:v for k,v in snapshot.items() if k!="sha256"})
        return {"agents":snapshots,"process_packs":packs,
                "missing":missing+(["R/GX Works3 适配未验证：仅允许离线分析任务"] if cpu.startswith("R") else []),
                "policy": "manual_internal; no native write or live PLC permission"}
