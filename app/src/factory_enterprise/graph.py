"""One LangGraph project graph with a nested module/tool loop and PostgreSQL checkpoints."""
from typing import TypedDict
import psycopg
from psycopg.rows import dict_row
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.postgres import PostgresSaver
from .catalog import digest

class State(TypedDict, total=False):
    project_id:str
    run_id:str
    next:str
    step:int
    response:dict

class EnterpriseGraph:
    def __init__(self,service,operations):self.s,self.ops=service,operations

    def _read(self,ident):
        with self.s.db.tx(False) as c:
            r=self.s.db.get(c,ident,'run');self.s._check_run(c,r,False);return r

    def _module_graph(self):
        def guard(state):
            r=self._read(state['run_id'])
            if r['status'] in {'cancelled','stale','rework'}:raise ValueError('模块已停止或需重新建立合同')
            return {'next':'act' if r['status'] in {'authorized','running'} and r['mode']=='api' else 'wait_result'}

        def act(state):
            r=self._read(state['run_id'])
            if r['status'] in {'candidate','accepted','waiting_input'}:return {'next':'wait_result'}
            if not r.get('model_id'):raise ValueError('尚未绑定模型')
            result=self.ops.model(r['id'],state.get('step',0),r['model_id'])
            if result.get('rejected'):raise ValueError(result['reason'])
            if result.get('action')=='tool':return {'response':result,'next':'tool'}
            if result.get('action')!='final':raise ValueError('模型返回不符合模块合同')
            out=self.s.submit_run('agent:'+r['id'],r['id'],result.get('summary',''),result.get('deliverables',[]),result.get('needs_info'))
            if out.get('rejected'):raise ValueError(out['reason'])
            return {'response':result,'next':'wait_result'}

        def tool(state):
            r=self._read(state['run_id']);response=state['response'];step=state.get('step',0)
            result=self.ops.tool(r['id'],'tool-'+str(step),response['tool'],response.get('arguments',{}))
            if result.get('rejected'):raise ValueError(result['reason'])
            return {'step':step+1,'next':'act'}

        def wait_result(state):
            r=self._read(state['run_id'])
            if r['status'] not in {'candidate','accepted'}:
                interrupt({'kind':'module_input','run_id':r['id'],'mode':r['mode'],'missing':r.get('missing',[]),'contract_hash':r['contract_hash']})
                r=self._read(state['run_id'])
            return {'next':'review' if r['status'] in {'candidate','accepted'} else 'wait_result'}

        def review(state):
            r=self._read(state['run_id'])
            if r['status']!='accepted':
                interrupt({'kind':'module_review','run_id':r['id'],'reviewer':r['contract']['reviewer'],'results':r['results']})
                r=self._read(state['run_id'])
            return {'next':'done' if r['status']=='accepted' else 'review'}

        b=StateGraph(State)
        for name,call in [('guard',guard),('act',act),('tool',tool),('wait_result',wait_result),('review',review)]:b.add_node(name,call)
        b.add_edge(START,'guard')
        b.add_conditional_edges('guard',lambda s:s['next'],{'act':'act','wait_result':'wait_result'})
        b.add_conditional_edges('act',lambda s:s['next'],{'tool':'tool','wait_result':'wait_result'})
        b.add_edge('tool','act')
        b.add_conditional_edges('wait_result',lambda s:s['next'],{'review':'review','wait_result':'wait_result'})
        b.add_conditional_edges('review',lambda s:s['next'],{'done':END,'review':'review'})
        return b.compile()

    def _build(self,saver):
        def inspect(state):
            with self.s.db.tx(False) as c:
                p=self.s.db.get(c,state['project_id'],'project')
                if p['stopped']:raise ValueError('项目已进入人工接管')
                released=any(r['signature']==self.s._gate_signature(c,p,'release') and self.s._gate_status(c,p,'release')['approved'] for r in self.s.db.rows(c,'release',p['id']))
                if released:return {'next':'done'}
                runs=[r for r in self.s.db.rows(c,'run',p['id']) if r['status'] in {'authorized','running','waiting_input','candidate'}]
                return {'next':'module' if runs else 'wait','run_id':runs[0]['id'] if runs else '', 'step':0}
        def human_wait(state):
            with self.s.db.tx(False) as c:
                p=self.s.db.get(c,state['project_id'],'project')
                gates={g:self.s._gate_status(c,p,g) for g in ['input','plan','engineering','risk','release']}
            interrupt({'kind':'business_decision','project_id':p['id'],'gates':gates})
            return {}
        b=StateGraph(State);b.add_node('inspect',inspect);b.add_node('module',self._module_graph());b.add_node('human_wait',human_wait)
        b.add_edge(START,'inspect');b.add_conditional_edges('inspect',lambda s:s['next'],{'done':END,'module':'module','wait':'human_wait'})
        b.add_edge('module','inspect');b.add_edge('human_wait','inspect')
        return b.compile(checkpointer=saver)

    def advance(self,actor,project):
        with self.s.db.tx(False) as c:
            p=self.s._p(c,actor,project,{'owner','engineer','reviewer','validator','knowledge'})
        config={'configurable':{'thread_id':'enterprise-'+project+'-'+str(p.get('flow_epoch',1))},'recursion_limit':120}
        # A session advisory lock prevents two processes from resuming the same checkpoint.
        lockkey=int(digest(project)[:15],16)
        with psycopg.connect(self.s.db.dsn,autocommit=True,row_factory=dict_row,prepare_threshold=0) as conn:
            if not conn.execute('SELECT pg_try_advisory_lock(%s) AS ok',(lockkey,)).fetchone()['ok']:
                raise ValueError('该项目图正在执行，请稍后刷新')
            try:
                saver=PostgresSaver(conn);saver.setup();graph=self._build(saver)
                snapshot=graph.get_state(config,subgraphs=True)
                # User input cannot supply approvals into checkpoints; only DB decisions count.
                if snapshot.values:
                    if not snapshot.next:
                        with self.s.db.tx(False) as c:
                            p=self.s.db.get(c,project,'project')
                            valid=any(r['signature']==self.s._gate_signature(c,p,'release') and self.s._gate_status(c,p,'release')['approved'] for r in self.s.db.rows(c,'release',project))
                        if valid:return {'completed':True,'state':snapshot.values,'waiting':[]}
                    def interrupted(s):
                        return bool(s.interrupts) or any(t.interrupts or (t.state and not isinstance(t.state,dict) and interrupted(t.state)) for t in s.tasks)
                    incoming=Command(resume={'recheck_business_records':True}) if interrupted(snapshot) else (None if snapshot.next else {'project_id':project,'step':0})
                else:incoming={'project_id':project,'step':0}
                graph.invoke(incoming,config)
                after=graph.get_state(config,subgraphs=True)
                def waits(s):
                    out=[i.value for i in s.interrupts]
                    for t in s.tasks:
                        out.extend(i.value for i in t.interrupts)
                        if t.state and not isinstance(t.state,dict):out.extend(waits(t.state))
                    return out
                pending=list({digest(w):w for w in waits(after)}.values())
                return {'completed':not bool(after.next),'state':after.values,'waiting':pending,'checkpoint_id':after.config.get('configurable',{}).get('checkpoint_id')}
            finally:conn.execute('SELECT pg_advisory_unlock(%s)',(lockkey,))
