"""Evidence-first TT diagnostics and bounded serial-line discrete event scenarios."""
from __future__ import annotations
import csv
import io
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime

from .documents import decode

FIELDS = {"event_id","timestamp","station","equipment_id","glass_id","product","recipe","event","state"}
STATES = {"processing","waiting","blocked","starved","transfer","down"}


def percentile(values,p):
    values=sorted(values)
    pos=(len(values)-1)*p
    lo=int(pos)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(pos-lo)


def timestamp(value):
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    if result.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return result


def analyze(raw, *, terminal_station, window_start=None, window_end=None, parallel=None, synthetic=False):
    if not terminal_station:
        raise ValueError("必须指定统计产出的末站")
    reader=csv.DictReader(io.StringIO(decode(raw)))
    if not FIELDS <= set(reader.fieldnames or []):
        raise ValueError("TT 日志缺少字段: "+",".join(sorted(FIELDS-set(reader.fieldnames or []))))
    errors=[]
    warnings=[]
    events=[]
    seen=set()
    for n,row in enumerate(reader,2):
        if n>200002:
            raise ValueError("日志超过 200000 条事件，请分窗口分析")
        try:
            if any(not row.get(f,"").strip() for f in FIELDS):
                raise ValueError("必要字段为空")
            if row["event_id"] in seen:
                raise ValueError("重复 event_id")
            seen.add(row["event_id"])
            if row["event"] not in {"start","end"} or row["state"] not in STATES:
                raise ValueError("event/state 枚举不支持")
            events.append({**row,"time":timestamp(row["timestamp"]),"row":n})
        except (ValueError,TypeError) as e:
            errors.append({"row":n,"reason":str(e)})
    if not events:
        errors.append({"reason":"没有有效事件"})
    if errors:
        return {"quality":"failed","errors":errors[:100],"warnings":warnings,"predictions_allowed":False,"synthetic":synthetic}
    if len({(e["product"],e["recipe"]) for e in events})!=1:
        return {"quality":"failed","errors":[{"reason":"混产品/配方须先分组，禁止直接汇总 TT"}],"predictions_allowed":False,"synthetic":synthetic}
    start=timestamp(window_start) if window_start else min(e["time"] for e in events)
    end=timestamp(window_end) if window_end else max(e["time"] for e in events)
    if end<=start:
        raise ValueError("统计结束时间必须晚于开始时间")
    if not window_start or not window_end:
        warnings.append("统计窗口取日志最早到最晚事件，未证明覆盖完整班次")
    pairs=defaultdict(list)
    for e in events:
        key=tuple(e[f] for f in ["station","equipment_id","glass_id","product","recipe","state"])
        pairs[key].append(e)
    intervals=[]
    for key,group in pairs.items():
        group.sort(key=lambda e:(e["time"],e["row"]))
        opened=None
        for e in group:
            if e["event"]=="start":
                if opened is not None:
                    errors.append({"row":e["row"],"reason":"开始事件重复，缺少上一结束事件"})
                opened=e
            elif opened is None:
                errors.append({"row":e["row"],"reason":"结束事件无匹配开始，或时钟逆序"})
            else:
                duration=(e["time"]-opened["time"]).total_seconds()
                if duration<=0:
                    errors.append({"row":e["row"],"reason":"动作时长不为正"})
                intervals.append({"station":key[0],"equipment_id":key[1],"glass_id":key[2],"product":key[3],"recipe":key[4],
                                  "state":key[5],"start":opened["time"],"end":e["time"],"duration_seconds":duration,
                                  "source_rows":[opened["row"],e["row"]]})
                opened=None
        if opened:
            errors.append({"row":opened["row"],"reason":"开始事件缺少结束"})
    equipment=defaultdict(list)
    for x in intervals:
        equipment[x["equipment_id"]].append(x)
    for eq,spans in equipment.items():
        spans.sort(key=lambda x:x["start"])
        for a,b in zip(spans,spans[1:]):
            if b["start"]<a["end"]:
                errors.append({"row":b["source_rows"][0],"reason":f"设备 {eq} 状态/处理重叠；并行轴或批处理需独立标识和模型"})
    if terminal_station not in {e["station"] for e in events}:
        errors.append({"reason":"日志没有指定末站"})
    if errors:
        return {"quality":"failed","errors":errors[:100],"warnings":warnings,"predictions_allowed":False,"synthetic":synthetic}
    parallel=parallel or {}
    summary=[]
    for station in sorted({e["station"] for e in events}):
        spans=[x for x in intervals if x["station"]==station and x["state"]=="processing" and x["start"]>=start and x["end"]<=end]
        samples=[x["duration_seconds"] for x in spans]
        if not samples:
            warnings.append(station+" 缺少窗口内完整处理样本")
            continue
        machines=parallel.get(station)
        observed_machines=len({x["equipment_id"] for x in spans})
        if machines is None:
            machines=observed_machines
            warnings.append(station+" 并行数取日志出现设备数，未核实完整设备清单")
        if not isinstance(machines,int) or isinstance(machines,bool) or machines<observed_machines or machines>1000:
            raise ValueError("并行设备数不足、无效或超出限制")
        mean=statistics.mean(samples)
        summary.append({"station":station,"sample_count":len(samples),"parallel":machines,"mean_seconds":mean,
                        "p50_seconds":percentile(samples,.5),"p95_seconds":percentile(samples,.95),
                        "service_capacity_proxy_per_hour":3600*machines/mean,"effective_service_seconds":mean/machines})
    summary.sort(key=lambda x:x["effective_service_seconds"],reverse=True)
    completions={x["glass_id"] for x in intervals if x["station"]==terminal_station and x["state"]=="processing" and start<=x["end"]<end}
    seconds=(end-start).total_seconds()
    states={s:sum(max(0,(min(x["end"],end)-max(x["start"],start)).total_seconds()) for x in intervals if x["state"]==s and x["start"]<end and x["end"]>start) for s in STATES}
    warnings += ["最长有效服务时间仅为瓶颈候选，需阻塞/缺料、稼动和实际产出佐证",
                 "状态时长为设备秒合计，不作为整线互斥时间或 OEE",
                 "产出为末站完成数；未提供良率判定，不等同良品数"]
    return {"quality":"passed","evidence_type":"synthetic_log" if synthetic else "uploaded_log_not_field_attested",
            "synthetic":synthetic,"errors":[],"warnings":warnings,"predictions_allowed":False,
            "window":{"start":start.isoformat(),"end":end.isoformat(),"seconds":seconds,"boundary":"[start,end)"},
            "completed":len(completions),"throughput_per_hour":len(completions)*3600/seconds,"stations":summary,
            "bottleneck_candidate":summary[0]["station"] if summary else None,"state_equipment_seconds":states,
            "timeline":[{**x,"start":x["start"].isoformat(),"end":x["end"].isoformat()} for x in intervals[:5000]],
            "timeline_truncated":len(intervals)>5000}


def number(value,name,minimum=0.0,maximum=1e9):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError(name+" 超出允许范围")
    return value


def simulate(config):
    import simpy
    stations=config["stations"]
    if not isinstance(stations,list) or not 1<=len(stations)<=30 or len({s["id"] for s in stations})!=len(stations):
        raise ValueError("站点列表无效或 ID 重复")
    interval=number(config["release_interval_seconds"],"投料间隔",.01,86400)
    horizon=number(config["duration_seconds"],"统计时长",1,604800)
    warmup=number(config.get("warmup_seconds",0),"预热",0,604800)
    if (horizon+warmup)/interval>100_000:
        raise ValueError("事件规模过大，请缩短窗口")
    capacities=config.get("buffers",[1]*(len(stations)-1))
    if len(capacities)!=len(stations)-1 or any(type(c)!=int or not 1<=c<=1000 for c in capacities):
        raise ValueError("串行站间缓存须为 1..1000；零缓存需专门的同步交接模型")
    for s in stations:
        if type(s.get("parallel",1))!=int or not 1<=s.get("parallel",1)<=100:
            raise ValueError("并行机数量无效")
        number(s["process_seconds"],"处理时长",.01,86400)
    env=simpy.Environment()
    queues=[simpy.Store(env)] + [simpy.Store(env,capacity=c) for c in capacities]
    completed=[]
    released=0
    blocked={s["id"]:0.0 for s in stations}
    starved={s["id"]:0.0 for s in stations}
    waiting_now={}
    blocked_now={}
    def source():
        nonlocal released
        while True:
            yield queues[0].put(released)
            released+=1
            yield env.timeout(interval)
    def worker(index):
        s=stations[index]
        token=object()
        while True:
            waiting_now[token]=(s["id"],env.now)
            item=yield queues[index].get()
            _,since=waiting_now.pop(token)
            starved[s["id"]]+=max(0,env.now-max(since,warmup))
            yield env.timeout(s["process_seconds"])
            if index==len(stations)-1:
                completed.append(env.now)
            else:
                t=env.now
                blocked_now[token]=(s["id"],t)
                yield queues[index+1].put(item)  # blocking after service, machine remains occupied
                blocked[s["id"]]+=max(0,env.now-max(t,warmup))
                blocked_now.pop(token)
    env.process(source())
    for i,s in enumerate(stations):
        for _ in range(s.get("parallel",1)):
            env.process(worker(i))
    env.run(until=warmup+horizon)
    for station,t in waiting_now.values():
        starved[station]+=max(0,env.now-max(t,warmup))
    for station,t in blocked_now.values():
        blocked[station]+=max(0,env.now-max(t,warmup))
    observed=sum(warmup<=t<warmup+horizon for t in completed)
    return {"completed":observed,"throughput_per_hour":observed*3600/horizon,"released_total":released,
            "completed_total":len(completed),"wip_at_end":released-len(completed),"blocked_machine_seconds":blocked,"starved_machine_seconds":starved,
            "model":"serial_parallel_constant_time_blocking_after_service","warmup_seconds":warmup,"duration_seconds":horizon,
            "limitations":["未建模故障、良率、配方切换、批处理、重入和搬送路径","恒定服务时间，仅用于经校准的对应工况","单次确定性结果，无置信区间"]}


def compare(config, scenario, *, observed_completed, tolerance=.1):
    if type(observed_completed)!=int or observed_completed<=0:
        raise ValueError("需提供同窗口实测完成数作为校准依据")
    number(tolerance,"校准误差阈值",0,.5)
    baseline=simulate(config)
    error=abs(baseline["completed"]-observed_completed)/observed_completed
    result={"evidence_type":"model_prediction","observed_completed":observed_completed,"baseline":baseline,
            "relative_error":error,"tolerance":tolerance,"calibrated":error<=tolerance,
            "field_verified":False,"assumptions":baseline["limitations"],
            "calibration_scope":"仅同窗口完成数误差；不证明 WIP、稼动、质量或所有行为已校准"}
    if error>tolerance:
        result.update(scenario=None,reason="基线未复现，禁止发布改善预测")
        return result
    # Same observation window and release rule; scenario changes only physical station/buffer configuration.
    permitted={"stations","buffers"}
    if scenario.keys()-permitted:
        raise ValueError("情景仅允许改变站点或缓存，统计窗口与投料规则保持一致")
    proposed=simulate({**config,**scenario})
    result.update(scenario=proposed,delta_completed=proposed["completed"]-baseline["completed"],
                  improvement_fraction=(proposed["completed"]-baseline["completed"])/max(1,baseline["completed"]))
    return result
