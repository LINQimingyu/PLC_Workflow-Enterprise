"""Vendor task boundary. Only the separately launched local worker touches GX."""
import argparse,json,os
from pathlib import Path
from .db import now
from .catalog import canonical
from .service import EnterpriseService

class VendorTasks:
    def __init__(self,service):self.s=service

    def request(self,actor,project,run_id,candidate_id,stage,coverage,request_id,program=None):
        if stage not in {'compile','simulation'} or not coverage or not request_id:raise ValueError('工具任务需阶段、覆盖和幂等键')
        with self.s.db.tx() as c:
            p=self.s._p(c,actor,project,{'validator','owner'})
            r=self.s.db.get(c,run_id,'run');self.s._check_run(c,r)
            if r['project_id']!=project or r['module']!='validation' or 'vendor.'+('compile' if stage=='compile' else 'simulate') not in r['contract']['tools']:
                raise PermissionError('需已授权的真实工具验证模块')
            if candidate_id not in {x['id'] for x in r['contract']['inputs']}:raise PermissionError('候选不在工具任务合同内')
            if actor not in {r['contract']['executor'],r['author']}:raise PermissionError('需执行者或项目授权人')
            candidate=self.s.db.get(c,candidate_id,'artifact')
            if candidate['type']!='CodeBundle' or not candidate['active']:raise ValueError('需当前候选工程')
            if not self.s._gate_status(c,p,'plan')['approved']:raise ValueError('需方案锁')
            prior=[j for j in self.s.db.rows(c,'job',project) if j.get('request_id')==request_id]
            if prior:
                j=prior[-1]
                if any(j[k]!=v for k,v in {'candidate_id':candidate_id,'stage':stage,'run_id':run_id,'program':program}.items()):
                    raise ValueError('同一幂等键不能变更工具任务')
                return prior[-1]
            if r['spent']['tool_calls']>=r['contract']['budget']['tool_calls']:raise ValueError('工具调用预算耗尽')
            r['spent']['tool_calls']+=1;self.s.db.put(c,'run',r)
            j=self.s._record(c,'job',project,actor,run_id=run_id,candidate_id=candidate_id,stage=stage,status='queued',
                coverage=coverage,context=self.s._tool_context(c,p,candidate),origin='tool',provenance='real',failure_kind='environment',
                request_id=request_id,program=program,candidate_sha256=candidate['sha256'])
            self.s.db.event(c,project,actor,'vendor.queue',{'id':j['id'],'stage':stage,'candidate_sha256':candidate['sha256']})
            return j

    def recover_unknown(self):
        with self.s.db.tx() as c:
            for j in self.s.db.rows(c,'job'):
                if j['origin']=='tool' and j['status']=='running':
                    j['status']='unknown';self.s.db.put(c,'job',j)
                    self.s.db.event(c,j['project_id'],'system','vendor.unknown',{'id':j['id']})

    def reconcile(self,actor,ident,note,log_id):
        with self.s.db.tx() as c:
            j=self.s.db.get(c,ident,'job');self.s._p(c,actor,j['project_id'],{'owner'})
            if j['origin']!='tool' or j['status'] not in {'unknown','running','late','queued'} or not note.strip():raise ValueError('该工具任务不可核查或缺少依据')
            log=self.s.db.get(c,log_id,'artifact')
            if log['project_id']!=j['project_id'] or log['type']!='Original' or log['payload'].get('purpose')!='evidence':raise ValueError('需本项目原始核查记录')
            self.s._bytes(log)
            j.update(status='reconciled',previous_status=j['status'],reconciled_by=actor,reconciliation_note=note,reconciliation_log=log_id)
            self.s.db.put(c,'job',j);self.s.db.event(c,j['project_id'],actor,'vendor.reconcile',{'id':ident,'log_id':log_id});return j

    def execute(self,ident,adapter=None):
        with self.s.db.tx() as c:
            j=self.s.db.get(c,ident,'job')
            if j['status']!='queued':raise ValueError('工具任务已执行或结果不明，不能重复运行')
            r=self.s.db.get(c,j['run_id'],'run');p=self.s._check_run(c,r)
            a=self.s.db.get(c,j['candidate_id'],'artifact')
            if j['context']!=self.s._tool_context(c,p,a) or not a['active']:raise ValueError('候选或工具链已变化')
            raw=self.s._bytes(a)
            profile=next(a for a in self.s._latest(c,p['id']).values() if a['type']=='ToolchainProfile')
            j.update(status='running',started_at=now());self.s.db.put(c,'job',j)
            self.s.db.event(c,p['id'],'worker','vendor.intent',{'id':ident})
        # This call is outside DB transactions. A crash leaves running intent, never an automatic retry.
        result=(adapter or native_compile)(j,raw,profile['payload'])
        if result.get('status') not in {'passed','failed','unavailable'} or not result.get('raw_log'):
            raise ValueError('厂商执行器缺少原始日志或确定结果，保留未知状态')
        with self.s.db.tx() as c:
            current=self.s.db.get(c,ident,'job');r=self.s.db.get(c,j['run_id'],'run')
            try:
                p=self.s._check_run(c,r);a=self.s.db.get(c,j['candidate_id'],'artifact')
                if not a['active'] or current['context']!=self.s._tool_context(c,p,a):raise ValueError('版本已变更')
            except (ValueError,PermissionError):
                current.update(status='late',untrusted_result=result);self.s.db.put(c,'job',current)
                self.s.db.event(c,j['project_id'],'worker','vendor.late',{'id':ident});return current
            log=self.s._artifact(c,p,'worker','Original','厂商工具原始日志',
                {'source':'受控 GX 工具执行器','classification':'internal','purpose':'evidence'},result['raw_log'].encode(),slot=ident+'-log',filename='vendor-log.json')
            current.update(status=result['status'],log_id=log['id'],result={k:v for k,v in result.items() if k!='raw_log'},
                           failure_kind=result.get('failure_kind','environment'),finished_at=now())
            self.s.db.put(c,'job',current);self.s._repair_result(c,p,current)
            atype='CompileResult' if j['stage']=='compile' else 'SimulationReport'
            a=self.s._artifact(c,p,'worker',atype,atype,{'job_id':ident},slot=ident)
            if current['status'] in {'passed','failed'}:
                r.update(status='candidate',results=[a['id']],basis=self.s._basis(c,p),summary='真实厂商工具结果：'+current['status'])
                self.s.db.put(c,'run',r)
            self.s.db.event(c,p['id'],'worker','vendor.complete',{'id':ident,'status':current['status']})
            return current

def native_compile(job,raw,profile):
    if job['stage']!='compile':
        return {'status':'unavailable','failure_kind':'environment','raw_log':json.dumps({'reason':'首期仿真由厂商环境人工执行，导入完整日志并独立核验。'})}
    from gxworks2.workspace_adapter import NativeWorkspaceValidation
    adapter=NativeWorkspaceValidation()
    if os.name!='nt' or not adapter.executable.is_file() or not adapter.installation:
        return {'status':'unavailable','failure_kind':'environment','raw_log':json.dumps({'reason':'未检测到 GX Works2 与 workspace adapter；未执行编译。'},ensure_ascii=False)}
    from application.native_validation import validate_native_snapshot
    result=validate_native_snapshot(raw,project_id=job['project_id'],version_id=job['candidate_id'],program=job['program'],expected_cpu=profile['cpu'])
    compilation=result.get('compilation',{})
    if compilation.get('completed') is True and compilation.get('acceptance') in {'accepted','rejected'}:
        status='passed' if compilation['acceptance']=='accepted' else 'failed'
    else:status='unavailable'
    return {'status':status,'failure_kind':'program' if status=='failed' else 'environment','tool_version':profile['ide_version'],
            'raw_log':json.dumps(result,ensure_ascii=False,default=str)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--job',required=True);a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text(encoding='utf-8'))
    s=EnterpriseService(cfg['dsn'],cfg['root'],cfg.get('environment','production'))
    result=VendorTasks(s).execute(a.job)
    print(json.dumps({'job_id':result['id'],'status':result['status']},ensure_ascii=False))
if __name__=='__main__':main()
