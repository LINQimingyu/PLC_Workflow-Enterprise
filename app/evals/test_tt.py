import csv
import io
from datetime import datetime,timedelta,timezone
import pytest
from cim.tt import analyze,simulate,compare


def log_rows():
    start=datetime(2026,11,2,8,tzinfo=timezone(timedelta(hours=8)))
    rows=[]
    for i in range(5):
        for station,delay,duration in [("S1",0,10),("S2",10,20)]:
            for event,seconds in [("start",i*30+delay),("end",i*30+delay+duration)]:
                rows.append({"event_id":f"{i}-{station}-{event}","timestamp":(start+timedelta(seconds=seconds)).isoformat(),
                             "station":station,"equipment_id":station+"-M1","glass_id":str(i),"product":"P1","recipe":"R1","event":event,"state":"processing"})
    return rows


def raw(rows):
    out=io.StringIO()
    writer=csv.DictWriter(out,fieldnames=list(log_rows()[0]))
    writer.writeheader();writer.writerows(rows)
    return out.getvalue().encode()


def test_valid_ct_candidates_do_not_claim_causality_or_good_output():
    r=analyze(raw(log_rows()),terminal_station="S2",synthetic=True)
    assert r["quality"]=="passed" and r["bottleneck_candidate"]=="S2"
    assert r["stations"][0]["p95_seconds"]==20
    assert not r["predictions_allowed"] and r["synthetic"]
    assert r["completed"]==4 # [start,end) excludes exact upper boundary
    assert r["warnings"]


@pytest.mark.parametrize("damage",["duplicate","no_timezone","missing_end","reverse","mixed_recipe","overlap"])
def test_data_errors_block_analysis(damage):
    rows=log_rows()
    if damage=="duplicate": rows.append(dict(rows[0]))
    if damage=="no_timezone": rows[0]["timestamp"]="2026-11-02T08:00:00"
    if damage=="missing_end": rows.pop(1)
    if damage=="reverse": rows[1]["timestamp"]="2026-11-02T07:59:00+08:00"
    if damage=="mixed_recipe": rows[0]["recipe"]="R2"
    if damage=="overlap":
        rows[4]["timestamp"]="2026-11-02T08:00:05+08:00"
        rows[5]["timestamp"]="2026-11-02T08:00:15+08:00"
    r=analyze(raw(rows),terminal_station="S2")
    assert r["quality"]=="failed" and r["errors"] and not r["predictions_allowed"]


def config():
    return {"stations":[{"id":"S1","process_seconds":10},{"id":"S2","process_seconds":20}],
            "buffers":[1],"duration_seconds":1000,"release_interval_seconds":10}


def test_serial_simulation_conserves_glass_and_upstream_improvement_does_not_lift_bottleneck():
    base=simulate(config())
    faster_upstream={"stations":[{"id":"S1","process_seconds":5},{"id":"S2","process_seconds":20}]}
    r=compare(config(),faster_upstream,observed_completed=base["completed"])
    assert base["released_total"]==base["completed_total"]+base["wip_at_end"]
    assert r["calibrated"] and abs(r["delta_completed"])<=1
    faster_bottleneck={"stations":[{"id":"S1","process_seconds":10},{"id":"S2","process_seconds":15}]}
    r=compare(config(),faster_bottleneck,observed_completed=base["completed"])
    assert r["delta_completed"]>0 and not r["field_verified"]


def test_uncalibrated_baseline_never_returns_improvement_prediction():
    r=compare(config(),{},observed_completed=500)
    assert not r["calibrated"] and r["scenario"] is None and "improvement_fraction" not in r


@pytest.mark.parametrize("bad",[0,float("nan"),-1,True])
def test_invalid_simulation_times_rejected(bad):
    c=config();c["release_interval_seconds"]=bad
    with pytest.raises(ValueError): simulate(c)


def test_parallel_capacity_and_finite_buffer_affect_actual_model():
    c=config();c["stations"][1]["parallel"]=2
    assert simulate(c)["completed"]>simulate(config())["completed"]
    c=config();c["buffers"]=[0]
    with pytest.raises(ValueError): simulate(c)
