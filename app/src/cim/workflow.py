"""Read-only, version-bound navigation over the existing business records.

The graph is a projection, never an execution engine or a second progress store.
"""
from __future__ import annotations
import json

from . import policy
from .records import now


STAGE_INFO = {
    "requirements": ("需求澄清", "工程师 / 项目协同专家", "说清现状、目标、纳入与排除范围，并确认验收要求。", "overview", "当前需求已人工确认，且本阶段专家任务全部审查通过。"),
    "baseline": ("资料基线", "工程师 / 基线专家", "核对来源资料、分级及关联工程的明确版本。", "documents", "本阶段专家任务全部审查通过；关联工程版本有效。"),
    "analysis": ("专业分析", "工艺 / 电气 / 改善专家", "按真实依赖执行专业任务，形成有来源的分析与候选成果。", "analysis", "本阶段所有专家任务回传并审查通过。"),
    "proposal": ("方案评估", "可行性专家 / 工程师", "评估方案、BOM、人天与收益依据，保留未知项。", "business", "方案评估专家任务审查通过；测算记录供方案决策参考。"),
    "review": ("专业审查", "程序 / 工艺 / 证据审查专家", "分别检查候选程序、工艺约束与证据。", "tasks", "本阶段各审查任务均已审查通过。"),
    "verification": ("工程与现场验证", "工程师 / 验证执行人", "分别登记静态检查、编译、模拟、现场及效果证据。", "delivery", "静态、编译、模拟、现场均通过或有理由豁免；效果可在归档时注明观察中。"),
    "archive": ("归档对照", "归档专家 / 归档责任人", "整理前后对照与实施结局，完成项目正式归档。", "delivery", "正式归档已保存；未实施或取消也须记录原因与责任人。"),
}
PHASES = {"static": "静态检查", "compile": "编译", "simulation": "模拟", "field": "现场", "benefit": "效果"}
TASK_ACTIONS = {"review": "审查当前回传", "waiting_return": "载入任务回传", "needs_info": "补充资料并处理任务", "rework": "查看返修意见", "failed": "检查失败原因并重试", "queued": "查看任务并创建批次", "approved": "查看已审查成果", "stale": "查看过期任务", "cancelled": "查看取消原因"}
ACTION_NAMES = {"project.created": "建立项目", "project.inputs_changed": "更新需求或项目输入", "requirements.confirmed": "确认当前需求", "document.added": "导入资料", "document.classified": "更新资料分级", "document.revoked": "撤销资料", "engineering.linked": "关联工程版本", "tasks.planned": "生成专家任务", "attempt.started": "创建执行批次", "result.returned": "收到任务回传", "task.reviewed": "记录人工审查", "project.status": "更新项目状态", "analysis.created": "保存分析结果", "estimate.saved": "保存方案测算", "verification.recorded": "登记验证记录", "project.archived": "记录项目归档", "shared.approved": "批准共享案例", "shared.withdrawn": "撤回共享案例", "tool.executed": "执行确定性工具"}
ACTION_NAMES.update({"document.source_added": "导入来源资料（输入新版本）", "document.classification_changed": "资料分级使旧任务过期",
                     "knowledge.shared": "批准共享案例", "knowledge.withdrawn": "撤回共享案例", "knowledge.source_withdrawn": "引用案例撤回（输入新版本）",
                     "archive.source_withdrawn": "归档来源被撤回，需复查", "tool.started": "开始执行确定性工具", "tool.completed": "确定性工具执行完成", "tool.failed": "确定性工具执行失败"})


def action(label, tab, **target):
    return {"label": label, "tab": tab, **target}


def node(key, kind, stage, label, status, *, role, purpose, inputs, completion, outputs=None, blockers=None, target=None, **extra):
    return {"id": key, "kind": kind, "stage": stage, "label": label, "status": status,
            "role": role, "purpose": purpose, "inputs": inputs, "completion": completion,
            "outputs": outputs or [], "blockers": blockers or [], "previous": [], "next": [],
            "action": target or action("查看本步", STAGE_INFO[stage][3]), **extra}


class WorkflowMixin:
    def workflow(self, pid):
        with self.connect() as db:
            # Keep all record reads in one SQLite snapshot, including guard checks.
            db.execute("BEGIN")
            p = self._project(db, pid)
            records = {kind: self._list(db, kind, pid) for kind in
                       ("task", "document", "attempt", "result", "analysis", "verification", "estimate", "archive")}
            current = lambda kind: [r for r in records[kind] if r.get("revision") == p["revision"]]
            tasks = sorted(current("task"), key=lambda t: (list(STAGE_INFO).index(t["stage"]), t["created_at"], t["id"]))
            docs = [d for d in records["document"] if not d["revoked"]]
            engineering_current = self._engineering_current(p)
            terminal = p["status"] in {"archived", "cancelled"}
            blockers = []
            if self.read_only:
                blockers.append("工作区只读，操作需在可写工作区完成")
            if p["status"] == "paused":
                blockers.append("项目已暂停，请先恢复项目")
            if not engineering_current:
                blockers.append("关联工程的版本或来源指纹已变化，需重新绑定基线")
            shared = self._shared_documents(db, p)
            if policy.inherited(p["classification"], *(d["classification"] for d in docs + shared)) == "pending":
                blockers.append("项目或任务资料待分级，请先核对资料分级")

            nodes, edges = [], []
            for index, (stage, info) in enumerate(STAGE_INFO.items()):
                label, role, purpose, tab, completion = info
                group = [t for t in tasks if t["stage"] == stage]
                done = sum(t["status"] == "approved" and engineering_current for t in group)
                total = len(group)
                complete = bool(group) and done == total
                if stage == "requirements":
                    total += 1
                    done += int(p["requirements_confirmed"])
                    complete = complete and p["requirements_confirmed"]
                if stage == "baseline":
                    complete = complete and engineering_current
                outputs = []
                if stage == "baseline":
                    outputs = [action(d["name"], "documents", document_id=d["id"]) for d in docs if d["kind"] == "source"]
                elif stage == "analysis":
                    outputs = [action(a["kind"] + " 分析记录", "analysis", record_id=a["id"]) for a in current("analysis")]
                elif stage == "proposal":
                    outputs = [action("方案测算记录", "business", record_id=e["id"]) for e in current("estimate")]
                if stage == "verification":
                    latest = self._latest_verification(current("verification"))
                    # Match implemented-archive guards: benefit may be pending observation.
                    total = 4
                    done = sum(latest.get(k, {}).get("status") in {"passed", "not_applicable"} for k in list(PHASES)[:4])
                    complete = done == total and engineering_current
                if stage == "archive":
                    total += 1
                    done += int(terminal)
                    complete = terminal
                status = "completed" if complete else "queued"
                if not complete and any(t["status"] == "failed" for t in group):
                    status = "failed"
                elif not complete and any(t["status"] == "rework" for t in group):
                    status = "rework"
                elif not complete and any(t["status"] == "needs_info" for t in group):
                    status = "needs_info"
                elif not complete and any(t["status"] == "review" for t in group):
                    status = "review"
                elif not complete and any(t["status"] == "waiting_return" for t in group):
                    status = "waiting_return"
                nodes.append(node("stage:" + stage, "stage", stage, label, status, role=role, purpose=purpose,
                                  inputs=["当前输入版本 r" + str(p["revision"]), "已确认的前置成果与来源资料"],
                                  completion=completion, outputs=outputs, target=action("前往" + label, tab),
                                  completed=done, total=total, blockers=blockers if not complete and not terminal else []))
                if index:
                    prior = list(STAGE_INFO)[index - 1]
                    edges.append({"id": "route:" + stage, "source": "stage:" + prior, "target": "stage:" + stage, "kind": "route"})

            nodes.append(node("requirements:confirm", "step", "requirements", "人工确认当前需求",
                              "completed" if p["requirements_confirmed"] else "queued", role="需求确认人",
                              purpose="明确目标、范围与验收条件后确认当前需求。", inputs=[p["requirements"] or "需求尚未填写"],
                              completion="当前输入版本已由具名工程师确认。", outputs=[action("确认人：" + p["confirmed_by"], "overview")] if p.get("requirements_confirmed") else [],
                              target=action("前往需求确认", "overview", focus="requirements")))
            for t in tasks:
                definition = t["definition"]["agent"]
                task_blockers = self._task_blockers(db, t, p) if t["status"] != "approved" or not engineering_current else []
                if t["status"] in {"queued", "rework", "needs_info", "failed"}:
                    task_blockers += [b for b in blockers if b not in task_blockers]
                result = sorted([r for r in records["result"] if r["task_id"] == t["id"] and
                                 not r["stale"] and r["attempt_id"] == t["current_attempt"]], key=lambda r: r["created_at"])
                outputs = [action(r["summary"] or "任务回传", "tasks", task_id=t["id"], record_id=r["id"]) for r in result]
                review = t.get("review")
                if review:
                    outputs.append(action("审查：" + review["actor"] + " · " + review["note"], "tasks", task_id=t["id"]))
                display_status = "stale" if t["status"] == "approved" and not engineering_current else t["status"]
                item = node("task:" + t["id"], "task", t["stage"], definition["name"], display_status,
                            role=definition["name"] + " / 人工审查人", purpose=definition.get("responsibility", "按任务合同执行并回传成果。"),
                            inputs=["当前版本来源与前置任务已接受成果", "厂内任务包；回传后须人工审查"],
                            completion="当前批次回传已由工程师审查通过。", outputs=outputs,
                            blockers=task_blockers, target=action(TASK_ACTIONS.get(t["status"], "查看任务"), "tasks", task_id=t["id"]),
                            ready=not task_blockers and not terminal and t["status"] in {"queued", "rework", "needs_info", "failed", "review", "waiting_return"})
                nodes.append(item)
                for dependency in t["dependencies"]:
                    edges.append({"id": dependency + ":" + t["id"], "source": "task:" + dependency, "target": item["id"], "kind": "dependency"})

            latest = self._latest_verification(current("verification"))
            for phase, label in PHASES.items():
                record = latest.get(phase)
                status = record["status"] if record else "not_run"
                stale_evidence = bool(record) and any(not any(d["id"] == source["source_id"] and d["sha256"] == source["sha256"] for d in docs) for source in record["sources"])
                phase_blockers = [] if engineering_current else ["关联工程版本已变化，需重新验证"]
                if p["status"] == "paused":
                    phase_blockers.append("项目已暂停，请先恢复项目")
                if self.read_only:
                    phase_blockers.append("工作区只读，无法登记新记录")
                if stale_evidence:
                    phase_blockers.append("验证证据已撤销或来源指纹已变化")
                # Do not promote missing or superseded evidence to a passing node.
                if (not engineering_current or stale_evidence) and status in {"passed", "not_applicable"}:
                    status = "stale"
                outputs = [action(record["actor"] + "：" + record["record"], "delivery", phase=phase, record_id=record["id"])] if record else []
                if record:
                    outputs += [action("查看验证证据", "documents", document_id=s["source_id"]) for s in record["sources"]]
                nodes.append(node("verification:" + phase, "verification", "verification", label, status,
                                  role=record["actor"] if record else "验证执行人", purpose="登记" + label + "的步骤、预期、实际结果及证据。",
                                  inputs=["当前工程版本", "原始 evidence 资料与执行记录"],
                                  completion="通过须附原始证据；不适用须记录理由。" + ("效果可注明仍在观察。" if phase == "benefit" else ""),
                                  outputs=outputs, blockers=phase_blockers, target=action("前往" + label + "登记", "delivery", phase=phase)))
            verification_nodes = [n for n in nodes if n["kind"] == "verification" and n["id"] != "verification:benefit"]
            verification_stage = next(n for n in nodes if n["id"] == "stage:verification")
            verification_stage["completed"] = sum(n["status"] in {"passed", "not_applicable"} for n in verification_nodes)
            verification_stage["status"] = ("completed" if verification_stage["completed"] == 4 else
                                             "failed" if any(n["status"] == "failed" for n in verification_nodes) else
                                             "stale" if any(n["status"] == "stale" for n in verification_nodes) else "not_run")

            archives = sorted(current("archive"), key=lambda a: a["created_at"])
            archive = archives[-1] if archives else None
            outcome = None
            if archive:
                outcome = {"outcome": archive["outcome"], "effect_status": archive["comparison"].get("effect_status"), "reason": archive["reason"], "actor": archive["actor"]}
            archive_blockers, _ = self._implemented_archive_checks(db, p)
            nodes.append(node("archive:formal", "step", "archive", "项目正式归档", "completed" if terminal else "queued",
                              role=archive["actor"] if archive else "归档责任人", purpose="记录实施结局、同口径对照及剩余事项。",
                              inputs=["当前审查与验证记录", "实施结局、原因、投入与前后对照"],
                              completion="归档记录已保存；实施归档遵循现有验收规则。",
                              blockers=[] if terminal else ["已实施归档：" + b for b in archive_blockers],
                              outputs=[action(archive["reason"], "delivery", focus="archive")] if archive else [],
                              target=action("查看归档结局" if terminal else "前往归档", "delivery", focus="archive")))

            by_id = {n["id"]: n for n in nodes}
            for stage in [n for n in nodes if n["kind"] == "stage"]:
                children = [n for n in nodes if n["kind"] != "stage" and n["stage"] == stage["stage"]]
                if stage["status"] != "completed" and not terminal:
                    stage["blockers"] = list(dict.fromkeys(stage["blockers"] + [b for n in children for b in n["blockers"]]))
                    if stage["stage"] == "requirements" and not p["requirements_confirmed"]:
                        stage["blockers"].insert(0, "当前需求尚未人工确认")
                    if not tasks and stage["stage"] != "verification":
                        stage["blockers"].append("当前版本尚未生成专家任务")
                stage["outputs"] += [output for child in children if child["kind"] == "task" for output in child["outputs"]]
            for edge in edges:
                if edge["source"] in by_id and edge["target"] in by_id:
                    by_id[edge["source"]]["next"].append(edge["target"])
                    by_id[edge["target"]]["previous"].append(edge["source"])
            stages = [n for n in nodes if n["kind"] == "stage"]
            current_stage = "archive" if terminal else next((n["stage"] for n in stages if n["status"] != "completed"), "archive")
            todo = [n for n in nodes if n["stage"] == current_stage and n["kind"] != "stage" and
                    n["status"] not in {"completed", "approved", "passed", "not_applicable"}]
            priority = {"review": 0, "rework": 1, "needs_info": 1, "failed": 1, "queued": 2, "waiting_return": 3}
            candidates = sorted([n for n in nodes if n["kind"] == "task" and n.get("ready")],
                                key=lambda n: (list(STAGE_INFO).index(n["stage"]), priority.get(n["status"], 9), n["label"]))
            if terminal:
                recommended = action("查看归档结局与完整记录", "delivery", focus="archive")
            elif self.read_only or p["status"] == "paused":
                recommended = action("查看项目状态并恢复" if not self.read_only else "查看只读项目", "overview", focus="project")
            elif not engineering_current:
                recommended = action("重新关联工程基线", "overview", focus="engineering")
            elif any("待分级" in b for b in blockers):
                recommended = action("核对项目及资料分级", "documents", focus="classification")
            elif not p["requirements_confirmed"]:
                recommended = action("补齐并确认当前需求", "overview", focus="requirements")
            elif not tasks:
                recommended = action("生成当前版本专家任务", "tasks", focus="plan")
            elif candidates:
                recommended = candidates[0]["action"]
            else:
                remaining = [n for n in todo if n["status"] != "cancelled"]
                recommended = remaining[0]["action"] if remaining else action("查看阻塞与取消任务，核对需求范围", "overview", focus="requirements")
            # Verification is actionable even while an archive expert remains queued;
            # the route must never invent a new dependency absent from the contract.
            if current_stage == "verification" and not terminal and not blockers and not any(t["stage"] != "archive" and t["status"] != "approved" for t in tasks):
                pending = [n for n in verification_nodes if n["status"] not in {"passed", "not_applicable"}]
                if pending:
                    recommended = pending[0]["action"]
            last = db.execute("SELECT * FROM audit WHERE project=? AND (action='task.reviewed' OR action='requirements.confirmed' OR action='verification.recorded' OR action='project.archived') ORDER BY seq DESC", (pid,)).fetchall()
            recent = None
            for row in last:
                data = json.loads(row["data"])
                if (row["action"] == "task.reviewed" and data.get("decision") == "approve") or row["action"] in {"requirements.confirmed", "project.archived"} or (row["action"] == "verification.recorded" and data.get("status") in {"passed", "not_applicable"}):
                    recent = self._workflow_event(db, dict(row))
                    break
            return {"project_id": pid, "revision": p["revision"], "project_status": p["status"],
                    "generated_at": now(), "current_stage": current_stage, "nodes": nodes, "edges": edges,
                    "blockers": [] if terminal else blockers, "todo": [] if terminal else [n["id"] for n in todo],
                    "recommended": recommended, "recent_completed": recent, "outcome": outcome,
                    "historical_tasks": len(records["task"]) - len(tasks)}

    @staticmethod
    def _latest_verification(records):
        latest = {}
        for record in sorted(records, key=lambda r: r["created_at"]):
            latest[record["phase"]] = record
        return latest

    def _workflow_event(self, db, row):
        """Enrich only from records that this event explicitly identifies."""
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        event = {**row, "data": data, "label": ACTION_NAMES.get(row["action"], row["action"]),
                 "actor": data.get("actor"), "revision": data.get("revision"), "target": None}
        mapping = {"attempt.started": ("attempt", data.get("attempt")), "result.returned": ("result", data.get("result")),
                   "task.reviewed": ("task", data.get("task")), "verification.recorded": ("verification", data.get("id")),
                   "document.added": ("document", data.get("id")), "document.source_added": ("document", data.get("id")),
                   "document.revoked": ("document", data.get("id")), "document.classified": ("document", data.get("document")),
                   "analysis.created": ("analysis", data.get("id")), "estimate.saved": ("estimate", data.get("id")),
                   "project.archived": ("archive", data.get("archive"))}
        if row["action"] in mapping:
            kind, key = mapping[row["action"]]
            record = None
            if key:
                try:
                    record = self._get(db, kind, key)
                except KeyError:
                    pass
            if record and record["project_id"] == row["project"]:
                event["revision"] = event["revision"] or record.get("revision", record.get("input_revision"))
                # Do not infer an old event's actor from a later task review.
                event["actor"] = event["actor"] or (record.get("actor") if kind in {"verification", "archive"} else None)
                if kind in {"task", "result", "attempt"}:
                    event["target"] = action("查看任务", "tasks", task_id=record["id"] if kind == "task" else record["task_id"])
                    task = record if kind == "task" else self._get(db, "task", record["task_id"])
                    if row["action"] == "task.reviewed":
                        event["label"] = {"approve": "审查通过", "rework": "退回返修", "cancel": "取消任务"}.get(data.get("decision"), event["label"])
                    event["label"] += " · " + task["definition"]["agent"]["name"]
                elif kind == "document":
                    event["target"] = action("查看资料", "documents", document_id=record["id"])
                    event["label"] += " · " + record["name"]
                else:
                    event["target"] = action("查看记录", {"verification": "delivery", "archive": "delivery", "estimate": "business", "analysis": "analysis"}[kind], record_id=record["id"], **({"phase": record["phase"]} if kind == "verification" else {"focus": "archive"} if kind == "archive" else {}))
                    if kind == "verification":
                        event["label"] += " · " + PHASES[record["phase"]]
        if row["action"] == "requirements.confirmed":
            event["target"] = action("查看需求", "overview", focus="requirements")
        return event

    def workflow_history(self, pid, *, limit=20, before_seq=None):
        events = self.audit(pid, limit=limit, before_seq=before_seq)
        with self.connect() as db:
            return [self._workflow_event(db, row) for row in events]
