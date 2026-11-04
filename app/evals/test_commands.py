import pytest
from cim.commands import invoke
from cim.service import FactoryService
from test_tt import log_rows,raw


def test_simulation_is_bound_to_passed_log_and_cannot_invent_observed_output(tmp_path):
    s=FactoryService(tmp_path/"business")
    p=s.create_project("Log binding",scenario="tt",classification="internal")
    pid=p["id"]
    d=s.add_document(pid,1,"synthetic.csv",raw(log_rows()),classification="internal",metadata={"synthetic":True})
    args={"expected_revision":2,"source_ids":[d["id"]],"config":{"stations":[{"id":"S1","process_seconds":10},{"id":"S2","process_seconds":20}],"release_interval_seconds":30,"duration_seconds":150},"scenario":{},"observed_completed":999}
    with pytest.raises(ValueError,match="先对相同资料"):
        invoke(s,pid,"simulate",args)
    a=invoke(s,pid,"tt-analyze",{"expected_revision":2,"source_id":d["id"],"terminal_station":"S2","synthetic":False})
    assert a["result"]["synthetic"] is True
    with pytest.raises(ValueError,match="完成数"):
        invoke(s,pid,"simulate",args)
    args["observed_completed"]=None
    r=invoke(s,pid,"simulate",args)
    assert r["result"]["baseline_analysis_id"]==a["id"] and r["result"]["synthetic"]
    assert r["result"]["observed_completed"]==4
    args["config"]["duration_seconds"]=3600
    with pytest.raises(ValueError,match="统计时长"):
        invoke(s,pid,"simulate",args)
