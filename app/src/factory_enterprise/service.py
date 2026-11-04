"""Business authority. Graph checkpoints and model text never authorize transitions."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zipfile import ZipFile, ZIP_DEFLATED
from io import BytesIO
import base64
import secrets
from psycopg.types.json import Jsonb
from .db import Database, uid, now
from .auth import Auth
from .catalog import ARTIFACTS, MODULES, GATES, STAGES, canonical, digest, method,legacy_support

INPUT_TYPES = {'ToolchainProfile', 'RequirementSpec', 'EngineeringPlan', 'Original', 'CodeBundle',
               'ElectricalDesignPackage', 'DiagnosisCase', 'ImprovementPackage', 'EnergyBaseline'}
DELIVERABLE_TYPES={'CodeBundle','ElectricalDesignPackage','DiagnosisCase','ImprovementPackage','EnergyBaseline','AnalysisDelivery','RiskFinding'}

def is_intake_plan(a):
    # Compatibility for the first guide-to-project intake snapshot. It is never an
    # executable module result or a substitute for a formal AnalysisDelivery.
    return a['type']=='IntakePlan' or (a['type']=='AnalysisDelivery' and a.get('slot')=='project-intake' and not a.get('run_id'))

class EnterpriseService:
    def __init__(self, dsn, root, environment='production'):
        self.db, self.root, self.environment = Database(dsn), Path(root).resolve(), environment
        self.root.mkdir(parents=True, exist_ok=True)
        binding_file=self.root/'.storage-id'
        with self.db.tx() as c:
            try:binding=self.db.get(c,'enterprise-storage-binding','storage_binding')
            except KeyError:binding=None
            if binding:
                if binding['environment']!=environment or not binding_file.exists() or binding_file.read_text(encoding='utf-8')!=binding['store_id']:
                    raise ValueError('数据库与制品存储不配套，禁止启动；请使用完整备份恢复')
            else:
                store_id=secrets.token_hex(24);binding_file.write_text(store_id,encoding='utf-8')
                self.db.put(c,'storage_binding',{'id':'enterprise-storage-binding','project_id':'','store_id':store_id,'environment':environment})
        self.auth = Auth(self.db)

    def _p(self, c, actor, project, roles=None):
        self.auth.require(c, actor, project, roles)
        return self.db.get(c, project, 'project')

    def _record(self, c, record_kind, project, actor, **fields):
        return self.db.put(c, record_kind, {'id': uid(record_kind), 'project_id': project, 'author': actor,
                                    'created_at': now(), **fields})

    def _blob(self, data):
        if not isinstance(data, bytes) or len(data) > 24 * 1024 * 1024:
            raise ValueError('制品文件最多 24 MiB')
        sha = digest(data); path = self.root / 'blobs' / sha[:2] / sha
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as f: f.write(data)
        except FileExistsError:
            if digest(path.read_bytes()) != sha: raise ValueError('制品存储摘要损坏')
        return sha

    def _bytes(self, a):
        data = (self.root / 'blobs' / a['sha256'][:2] / a['sha256']).read_bytes()
        if digest(data) != a['sha256']: raise ValueError('制品文件摘要不一致，停止使用与导出')
        if digest({k:v for k,v in a.items() if k not in {'record_hash','active'}}) != a['record_hash']:
            raise ValueError('制品记录摘要不一致')
        return data

    def _latest(self, c, project):
        result = {}
        for a in self.db.rows(c, 'artifact', project):
            if a['active']: result[a['slot']] = a
        return result

    def _basis(self, c, p, types=None):
        rows = self._latest(c, p['id']).values()
        return digest({'epoch': p['auth_epoch'], 'controller': p['controller'],
                       'artifacts': sorted((a['id'], a['record_hash']) for a in rows if a['type'] in (types or INPUT_TYPES)
                                           and not (a['type']=='Original' and a['payload'].get('purpose')=='evidence'))})

    def create_project(self, actor, name, goal, modules, controller='human', delivery='engineering'):
        if not name.strip() or not goal.strip(): raise ValueError('需填写项目名称与目标')
        if set(modules) - MODULES.keys() or not modules: raise ValueError('请选择工作模块')
        if controller not in {'human','agent'} or delivery not in {'engineering','analysis'}: raise ValueError('无效总控或交付类型')
        with self.db.tx() as c:
            self.auth.user(c, actor)
            p = self._record(c, 'project', '', actor, name=name.strip(), goal=goal, modules=list(dict.fromkeys(['control',*modules,'review','validation','delivery','knowledge'])),
                             controller=controller, delivery=delivery, auth_epoch=1, stopped=False, failure_streak=0,
                             environment_failures=0, lifecycle={'release':'not_released','implementation':'not_recorded','site':'not_recorded','benefit':'not_recorded'})
            p['project_id'] = p['id']; self.db.put(c,'project',p)
            c.execute('INSERT INTO ep_members VALUES(%s,%s,%s)', (p['id'],actor,Jsonb(['owner','engineer','reviewer','validator','knowledge','viewer'])))
            self.db.event(c,p['id'],actor,'project.create',{'modules':p['modules'],'delivery':delivery})
            return p

    def projects(self, actor):
        with self.db.tx(False) as c:
            self.auth.user(c,actor)
            ids = {r['project_id'] for r in c.execute('SELECT project_id FROM ep_members WHERE user_id=%s AND roles<>\'[]\'::jsonb',(actor,)).fetchall()}
            return [p for p in self.db.rows(c,'project') if p['id'] in ids]

    def controller(self, actor, project, mode):
        if mode not in {'human','agent'}: raise ValueError('总控选项无效')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner'});p['controller']=mode;p['auth_epoch']+=1
            self.db.put(c,'project',p);self.db.event(c,project,actor,'controller.update',{'mode':mode})
            return p

    def detail(self, actor, project):
        with self.db.tx(False) as c:
            p=self._p(c,actor,project)
            kinds=['artifact','run','grant','decision','job','risk','release','knowledge','intervention','patch','lifecycle','metric','operation','late_result','legacy_mapping','component']
            rows={kind:self.db.rows(c,kind,project) for kind in kinds}
            for grant in rows['grant']: grant.pop('token_hash',None)
            return {'project':p, **rows, 'gates':{g:self._gate_status(c,p,g) for g in GATES},
                    'basis':self._basis(c,p), 'members':c.execute('SELECT u.id,u.display_name,m.roles FROM ep_members m JOIN ep_users u ON u.id=m.user_id WHERE m.project_id=%s',(project,)).fetchall(),
                    'events':c.execute('SELECT seq,actor,action,data,created_at FROM ep_events WHERE project_id=%s ORDER BY seq DESC LIMIT 100',(project,)).fetchall()}

    def _artifact(self,c,p,actor,atype,title,payload,data=None,slot=None,filename=None,run_id=None,repair=False):
        if atype not in ARTIFACTS: raise ValueError('未知制品类型')
        if atype=='AnalysisDelivery' and slot=='project-intake' and not run_id:
            raise ValueError('前置任务计划请使用 IntakePlan 类型与新制品序列')
        if not isinstance(payload,dict): raise ValueError('制品字段必须是对象')
        if atype=='Original' and (payload.get('classification') not in {'public','internal','restricted'} or payload.get('purpose','reference') not in {'reference','evidence'}):
            raise ValueError('原件资料分级或用途无效')
        missing=[k for k in ARTIFACTS[atype] if k not in payload or payload[k] is None or payload[k]=='']
        if missing: raise ValueError('缺少参数：'+', '.join(missing))
        if atype=='ToolchainProfile':
            if not str(payload['cpu']).upper().startswith('Q') or payload['ide']!='GX Works2':
                raise ValueError('首期工具链仅 Q／GX Works2；其他厂商需独立准入')
            for ident in payload['original_ids']:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=p['id'] or a['type']!='Original' or not a['active']: raise ValueError('原件引用无效')
        slot=slot or atype
        if len(str(title))>160 or not str(title).strip(): raise ValueError('需填写制品标题')
        if filename and (Path(filename).name!=filename or any(x in filename for x in '/\\:') or any(ord(x)<32 for x in filename)): raise ValueError('文件名不能包含路径或控制字符')
        old=[a for a in self.db.rows(c,'artifact',p['id']) if a['slot']==slot]
        if old and any(a['type']!=atype for a in old): raise ValueError('同一制品序列不能改变类型')
        if atype=='CodeBundle' and not repair:
            if data is None:raise ValueError('缺少候选代码／工程文件，不能只用摘要作为候选程序包')
            if not self._gate_status(c,p,'plan')['approved']:raise ValueError('方案锁通过后才能建立候选程序')
            if p['stopped']: raise ValueError('项目已停止修复，需人工接管')
            for prior in old:
                if prior['active'] and any(j['candidate_id']==prior['id'] and j['stage']=='compile' and j['status']=='failed'
                                           and j['failure_kind']=='program' and j['context']==self._tool_context(c,p,prior)
                                           for j in self.db.rows(c,'job',p['id'])):
                    raise ValueError('该候选编译失败，必须逐轮使用补丁人工确认流程')
        refs=[]
        if atype in DELIVERABLE_TYPES:
            selected=[self.db.get(c,x['id'],'artifact') for x in self.db.get(c,run_id,'run')['contract']['inputs']] if run_id else [a for a in self._latest(c,p['id']).values() if a['type'] in {'Original','ToolchainProfile','RequirementSpec','EngineeringPlan'}]
            refs=[{'id':ref['id'],'record_hash':ref['record_hash']} for ref in selected
                  if ref['slot']!=slot and ref['type'] in INPUT_TYPES and ref['payload'].get('purpose')!='evidence']
        context=self._gate_signature(c,p,'plan') if atype in DELIVERABLE_TYPES else None
        levels={'public':0,'internal':1,'restricted':2}
        classification=payload['classification'] if atype=='Original' else max(
            ['internal']+[ref.get('classification','internal') for ref in self._latest(c,p['id']).values() if ref['type'] in INPUT_TYPES],key=levels.get)
        for a in old:
            if a['active']:
                a['active']=False;self.db.put(c,'artifact',a)
        # Lifecycle metadata is separately hashed; immutable file content remains content-addressed.
        a=self._record(c,'artifact',p['id'],actor,type=atype,title=title,payload=payload,slot=slot,version=len(old)+1,
                       sha256=self._blob(data if data is not None else canonical(payload)),filename=filename or f'{atype}.json',
                       active=True,run_id=run_id,environment=self.environment,engineering_context=context,provenance_refs=refs,classification=classification)
        a['record_hash']=digest({k:v for k,v in a.items() if k!='active'});self.db.put(c,'artifact',a)
        if atype=='RiskFinding':
            if payload['severity'] not in {'critical','high','medium','low'}:raise ValueError('风险等级无效')
            self._record(c,'risk',p['id'],actor,severity=payload['severity'],description=payload['description'],
                         mitigation=payload['mitigation'],rollback=payload['rollback'],source_id=a['id'],status='open')
        self.db.event(c,p['id'],actor,'artifact.create',{'id':a['id'],'type':atype,'version':a['version'],'sha256':a['sha256']})
        return a

    def artifact(self,actor,project,atype,title,payload,data=None,slot=None,filename=None):
        if atype in {'CompileResult','SimulationReport','ManualInterventionRecord','EngineeringReleaseManifest','PatchProposal'}:
            raise ValueError('该制品须通过对应业务流程生成')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'engineer','owner'})
            return self._artifact(c,p,actor,atype,title,payload,data,slot,filename)

    def read_artifact(self,actor,ident):
        with self.db.tx(False) as c:
            a=self.db.get(c,ident,'artifact');self._p(c,actor,a['project_id'])
            return a,self._bytes(a)

    def _gate_signature(self,c,p,gate):
        input_sig=self._basis(c,p,{'ToolchainProfile','RequirementSpec','Original'})
        plan_sig=digest([input_sig,self._basis(c,p,{'EngineeringPlan'})])
        if gate=='input': return input_sig
        if gate=='plan': return plan_sig
        engineering=digest([plan_sig,self._basis(c,p),[(j['id'],j['status'],j.get('verified_by')) for j in self.db.rows(c,'job',p['id'])],
                            [(r['id'],r['status']) for r in self.db.rows(c,'run',p['id'])]])
        if gate=='engineering': return engineering
        risks=digest([engineering,[digest(r) for r in self.db.rows(c,'risk',p['id'])]])
        if gate=='risk': return risks
        if gate=='release': return digest([risks, self._gate_status(c,p,'risk')['decision']])
        return digest([(k['id'],k['status'],k.get('approvers',[])) for k in self.db.rows(c,'knowledge',p['id'])])

    def _gate_status(self,c,p,gate):
        cache=getattr(c,'ep_gate_cache',None);key=(p['id'],gate)
        if cache is not None and key in cache:return cache[key]
        signature=self._gate_signature(c,p,gate)
        decisions=[d for d in self.db.rows(c,'decision',p['id']) if d['gate']==gate and d['signature']==signature]
        latest=decisions[-1] if decisions else None
        blockers=self._gate_blockers(c,p,gate)
        status={'approved':bool(latest and latest['approved'] and not blockers), 'signature':signature, 'decision':latest,'blockers':blockers}
        if cache is not None:cache[key]=status
        return status

    def _gate_blockers(self,c,p,gate):
        current=list(self._latest(c,p['id']).values());types={a['type'] for a in current if not is_intake_plan(a)};b=[]
        if gate=='input':
            b += [f'缺少 {t}' for t in ['Original','ToolchainProfile','RequirementSpec'] if t not in types]
            for a in current:
                if a['type']=='ToolchainProfile' and not a['payload']['original_ids']: b.append('未绑定原始工程')
                if a['type']=='ToolchainProfile':
                    for ref in a['payload']['original_ids']:
                        try:
                            source=self.db.get(c,ref,'artifact')
                            if not source['active'] or source['project_id']!=p['id']:b.append('工具链绑定原件已变化，需更新基线')
                        except KeyError:b.append('工具链原件引用缺失')
                if a['type'] in {'ToolchainProfile','RequirementSpec','Original'} and a['payload'].get('purpose')!='evidence':
                    try:self._bytes(a)
                    except (ValueError,FileNotFoundError):b.append('输入制品摘要损坏：'+a['title'])
        elif gate=='plan':
            if not self._gate_status(c,p,'input')['approved']: b.append('输入锁尚未通过')
            if 'EngineeringPlan' not in types: b.append('缺少工程方案')
        elif gate=='engineering':
            if not self._gate_status(c,p,'plan')['approved']: b.append('方案锁尚未通过')
            if p['stopped']: b.append('连续三轮失败，待人工接管')
            for a in current:
                if a['type'] in INPUT_TYPES:
                    try:self._bytes(a)
                    except (ValueError,FileNotFoundError):b.append('工程制品摘要损坏：'+a['title'])
                if a['type'] in DELIVERABLE_TYPES and not is_intake_plan(a):
                    if a.get('engineering_context')!=self._gate_signature(c,p,'plan'):b.append('交付对应需求或方案已变化：'+a['title'])
                    for ref in a.get('provenance_refs',[]):
                        source=self.db.get(c,ref['id'],'artifact')
                        if not source['active'] or source['record_hash']!=ref['record_hash']:b.append('交付依赖版本已变化：'+a['title'])
            if p['delivery']=='engineering':
                bundles=[a for a in current if a['type']=='CodeBundle']
                if not bundles: b.append('缺少候选工程')
                for a in bundles:
                    for stage in ['static','compile','simulation']:
                        if not self._valid_evidence(c,p,a,stage): b.append(f'{a["title"]} 缺少当前版本真实{stage}证据')
            elif 'AnalysisDelivery' not in types: b.append('缺少分析交付与局限说明')
            for run in self.db.rows(c,'run',p['id']):
                if run['status'] not in {'accepted','cancelled','stale'}: b.append('存在未完成模块交付')
                if run['status']=='accepted' and any(self.db.get(c,i,'artifact')['active'] for i in run['results']):
                    from .maintenance import Maintenance
                    try:Maintenance(self).check_refs(c,run['contract'])
                    except (PermissionError,ValueError,KeyError):b.append('模块依据能力版本已停用或失效')
                    for ref in run['contract']['knowledge']:
                        try:
                            knowledge=self._use_knowledge(c,run['author'],ref['id'],p['id'],formal=True)
                            if digest(knowledge)!=ref['hash']:b.append('正式工程依据知识版本已变化')
                        except (ValueError,PermissionError,KeyError):b.append('正式工程依据知识已失效或无权限')
        elif gate=='risk':
            if not self._gate_status(c,p,'engineering')['approved']: b.append('工程锁尚未通过')
            for risk in self.db.rows(c,'risk',p['id']):
                if risk['status'] not in {'closed','waived'}: b.append('风险尚未处置：'+risk['description'])
                if risk['severity'] in {'critical','high'} and risk['status']!='closed': b.append('严重／高风险必须关闭')
                if risk['status'] in {'closed','waived'} and risk.get('disposition_context')!=self._basis(c,p): b.append('风险处置对应工程或权限已变化，需重新审核')
        elif gate=='release':
            if not self._gate_status(c,p,'risk')['approved']: b.append('风险锁尚未通过')
        elif gate=='knowledge':
            if not any(k['domain']=='production' and k['status']=='published' and self._knowledge_valid(c,k) for k in self.db.rows(c,'knowledge',p['id'])):
                b.append('尚无审核发布的生产知识')
        return list(dict.fromkeys(b))

    def decide_gate(self,actor,project,gate,signature,approved,note):
        if gate not in GATES or not isinstance(approved,bool) or not str(note).strip(): raise ValueError('请选择门禁、决定并填写依据')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner','reviewer'});status=self._gate_status(c,p,gate)
            if status['signature']!=signature: raise ValueError('审核对象已变化，请重新审查')
            if approved and status['blockers']: raise ValueError('；'.join(status['blockers']))
            for a in self._latest(c,project).values(): self._bytes(a)
            d=self._record(c,'decision',project,actor,gate=gate,signature=signature,approved=approved,note=note)
            self.db.event(c,project,actor,'gate.decide',{'decision_id':d['id'],'gate':gate,'approved':approved,'signature':signature})
            return d

    def create_run(self,actor,project,module,goal,scope,inputs,outputs,acceptance,executor,reviewer,mode='manual',
                   tools=None,budget=None,knowledge_ids=None,ordinary_review=False,legacy_context=None):
        if module not in MODULES or mode not in {'manual','bundle','api'}: raise ValueError('模块或执行方式无效')
        if not isinstance(ordinary_review,bool):raise ValueError('普通关口委托需明确布尔决定')
        if not goal or not scope or not acceptance or not outputs: raise ValueError('模块合同缺少目标、范围、交付或验收')
        if set(outputs)-ARTIFACTS.keys(): raise ValueError('交付类型无效')
        if set(outputs)-(set(MODULES[module][2])|{'AnalysisDelivery'}):raise PermissionError('交付超出工作模块职责')
        tools=tools or [];budget=budget or {'model_calls':3,'tool_calls':8,'tokens':12000}
        if set(tools)-set(MODULES[module][3]): raise PermissionError('工具不属于模块允许能力')
        if set(budget)!={'model_calls','tool_calls','tokens'} or any(not isinstance(v,int) or v<0 for v in budget.values()): raise ValueError('预算无效')
        if budget['model_calls']>8 or budget['tool_calls']>20 or budget['tokens']>64000: raise ValueError('超出单任务预算')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner'})
            if module not in p['modules']: raise PermissionError('尚未授权该工作模块')
            self.auth.require(c,executor,project,{'engineer','validator','knowledge','owner'})
            self.auth.require(c,reviewer,project,{'reviewer','owner'})
            if executor==reviewer: raise ValueError('执行者与审核人必须为不同实名用户')
            if module not in {'control','knowledge'} and not self._gate_status(c,p,'input')['approved']: raise ValueError('请先通过输入锁')
            selected=[]
            for ident in inputs:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=project or not a['active']: raise ValueError('输入不属于当前项目或版本已过期')
                self._bytes(a);selected.append({'id':ident,'sha256':a['sha256'],'record_hash':a['record_hash']})
            know=[]
            for ident in knowledge_ids or []:
                k=self._use_knowledge(c,actor,ident,project,formal=True)
                self._use_knowledge(c,executor,ident,project,formal=True)
                self._use_knowledge(c,reviewer,ident,project,formal=True)
                know.append({'id':ident,'hash':digest(k)})
            from .maintenance import Maintenance
            agent_profile,skill,capability_refs=Maintenance(self).resolve(c,module,tools)
            profile=next((a for a in self._latest(c,project).values() if a['type']=='ToolchainProfile'),None)
            support=legacy_support(module,legacy_context,profile['payload']['cpu'] if profile else None)
            contract={'module':module,'goal':goal,'scope':scope,'inputs':selected,'outputs':outputs,'acceptance':acceptance,
                      'owner':actor,'executor':executor,'reviewer':reviewer,'skill':skill,'agent':agent_profile,'capability_refs':capability_refs,'tools':tools,'budget':budget,
                      'knowledge':know,'human_points':['成果审核','工程门禁','每轮补丁确认','发布终审'],
                      'stop_conditions':['撤权','版本变化','预算耗尽','未知执行结果','连续三轮修复失败'],
                      'ordinary_review_delegable':bool(ordinary_review and module not in {'review','validation','delivery','knowledge'}),
                      'legacy_support':support}
            contract['toolchain']=({'id':profile['id'],'record_hash':profile['record_hash'],'baseline':profile['payload']} if profile else None)
            r=self._record(c,'run',project,actor,module=module,contract=contract,contract_hash=digest(contract),basis=self._basis(c,p),
                           status='draft',mode=mode,spent={'model_calls':0,'tool_calls':0,'tokens':0},results=[],grant_id=None)
            self.db.event(c,project,actor,'run.create',{'id':r['id'],'contract_hash':r['contract_hash']})
            return r

    def authorize_run(self,actor,ident):
        with self.db.tx() as c:
            r=self.db.get(c,ident,'run');p=self._p(c,actor,r['project_id'],{'owner'})
            if r['status']!='draft' or r['basis']!=self._basis(c,p): raise ValueError('任务已授权或基线已变更')
            from .maintenance import Maintenance
            Maintenance(self).check_refs(c,r['contract'])
            if r['mode']=='api':
                if not r.get('model_id') or self.db.get(c,r['model_id'],'model')['capability']!='verified':raise ValueError('API 任务须先绑定通过合成探针的厂内模型')
            token=secrets.token_urlsafe(36)
            grant=self._record(c,'grant',p['id'],actor,run_id=ident,token_hash=digest(token.encode()),revoked=False,
                               epoch=p['auth_epoch'],expires=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
            r['grant_id']=grant['id'];r['status']='authorized';self.db.put(c,'run',r)
            self.db.event(c,p['id'],actor,'run.authorize',{'run_id':ident,'grant_id':grant['id']})
            return {'run':r,'agent_token':token}

    def _check_run(self,c,r,working=True):
        p=self.db.get(c,r['project_id'],'project')
        from .maintenance import Maintenance
        Maintenance(self).check_refs(c,r['contract'])
        self.auth.require(c,r['contract']['executor'],p['id'],{'engineer','validator','knowledge','owner'})
        g=self.db.get(c,r['grant_id'],'grant') if r['grant_id'] else None
        if not g or g['revoked'] or datetime.fromisoformat(g['expires'])<=datetime.now(timezone.utc) or g['epoch']!=p['auth_epoch']:
            raise PermissionError('模块授权已过期或被撤回')
        self.auth.require(c,g['author'],p['id'],{'owner'})
        if p['stopped'] or r['basis']!=self._basis(c,p): raise ValueError('项目暂停或模块输入已变化')
        if r['module'] not in {'control','knowledge'} and not self._gate_status(c,p,'input')['approved']:
            raise PermissionError('输入锁批准已失效或被撤回')
        if working and r['status'] not in {'authorized','running','waiting_input'}: raise ValueError('模块当前不可执行')
        if digest(r['contract'])!=r['contract_hash']: raise ValueError('任务合同摘要异常')
        for a in r['contract']['inputs']:
            current=self.db.get(c,a['id'],'artifact')
            replaced_by_own_output = not working and any(self.db.get(c,i,'artifact')['slot']==current['slot'] for i in r['results'])
            if (not current['active'] and not replaced_by_own_output) or current['record_hash']!=a['record_hash']: raise ValueError('模块输入版本失效')
            self._bytes(current)
        for k in r['contract']['knowledge']:
            current=self._use_knowledge(c,r['contract']['executor'],k['id'],p['id'],formal=True)
            if digest(current)!=k['hash']: raise ValueError('知识版本已变化')
        return p

    def revoke_run(self,actor,ident):
        with self.db.tx() as c:
            r=self.db.get(c,ident,'run');p=self._p(c,actor,r['project_id'],{'owner'})
            if r['grant_id']:
                g=self.db.get(c,r['grant_id'],'grant');g['revoked']=True;self.db.put(c,'grant',g)
            r['status']='cancelled';self.db.put(c,'run',r)
            self.db.event(c,p['id'],actor,'run.revoke',{'run_id':ident});return r

    def agent_identity(self,ident,token):
        with self.db.tx(False) as c:
            r=self.db.get(c,ident,'run');self._check_run(c,r)
            g=self.db.get(c,r['grant_id'],'grant')
            if not secrets.compare_digest(g['token_hash'],digest(token.encode())): raise PermissionError('Agent 凭据无效')
            return 'agent:'+ident

    def submit_run(self,actor,ident,summary,deliverables,needs_info=None):
        if not isinstance(deliverables,list) or (needs_info is not None and (not isinstance(needs_info,list) or any(not isinstance(i,str) for i in needs_info))):raise ValueError('交付与缺项需符合模块合同结构')
        if not isinstance(summary,str) or len(summary)>20000 or len(deliverables)>32 or len(needs_info or [])>64:raise ValueError('模块回传大小或结构超出边界')
        for item in deliverables:
            if not isinstance(item,dict) or set(item)-{'type','title','payload','slot','filename','data_base64'} or not {'type','title','payload'}<=item.keys() or not isinstance(item['payload'],dict):
                raise ValueError('候选交付须包含 type、title 与 payload，且只能使用合同交付字段')
        with self.db.tx() as c:
            r=self.db.get(c,ident,'run')
            if actor not in {r['contract']['executor'],'agent:'+ident}: raise PermissionError('只能由授权执行者提交')
            try: p=self._check_run(c,r)
            except (ValueError,PermissionError) as e:
                late=self._record(c,'late_result',r['project_id'],actor,run_id=ident,summary=summary,reason=str(e),payload=deliverables)
                self.db.event(c,r['project_id'],actor,'result.rejected',{'id':late['id'],'run_id':ident})
                return {'rejected':True,'reason':str(e),'id':late['id']}
            if not summary.strip(): raise ValueError('成果说明不能为空')
            if needs_info:
                r['status']='waiting_input';r['missing']=needs_info;self.db.put(c,'run',r);return r
            if not deliverables: raise ValueError('需提交至少一项合同约定交付')
            created=[]
            for item in deliverables:
                if item['type'] not in r['contract']['outputs'] or item['type'] in {'CompileResult','SimulationReport','EngineeringReleaseManifest','PatchProposal','ManualInterventionRecord'}:
                    raise PermissionError('交付超出模块合同或需专用业务流程')
                raw=base64.b64decode(item['data_base64'],validate=True) if item.get('data_base64') else None
                a=self._artifact(c,p,actor,item['type'],item['title'],item['payload'],raw,item.get('slot'),item.get('filename'),ident)
                created.append(a['id'])
            r.update(status='candidate',summary=summary,results=created,basis=self._basis(c,p));self.db.put(c,'run',r)
            self.db.event(c,p['id'],actor,'run.submit',{'id':ident,'results':created});return r

    def review_run(self,actor,ident,accepted,note,agent_grant=None):
        if not isinstance(accepted,bool):raise ValueError('审核决定必须为明确的布尔值')
        if actor=='agent:'+ident:raise PermissionError('Agent 不能批准自己的产物')
        with self.db.tx() as c:
            r=self.db.get(c,ident,'run');p=self._check_run(c,r,False)
            if r['status']!='candidate': raise ValueError('尚无可审查成果')
            if actor.startswith('agent:'):
                controller=self.db.get(c,actor[6:],'run');self._check_run(c,controller)
                if controller['project_id']!=p['id'] or controller['module']!='control' or p['controller']!='agent' or not r['contract']['ordinary_review_delegable'] or controller['id']==ident:
                    raise PermissionError('该关口不可委托总控 Agent')
                reviewer_identity=controller['contract']['executor']
            else:
                self.auth.require(c,actor,p['id'],{'reviewer','owner'})
                if actor!=r['contract']['reviewer'] or actor==r['contract']['executor']: raise PermissionError('需要合同指定的独立审核人')
                reviewer_identity=actor
            for ref in r['contract']['knowledge']:self._use_knowledge(c,reviewer_identity,ref['id'],p['id'],formal=True)
            if not note.strip(): raise ValueError('需填写审核依据')
            r.update(status='accepted' if accepted else 'rework',review={'by':actor,'accepted':bool(accepted),'note':note,'at':now()})
            self.db.put(c,'run',r);self.db.event(c,p['id'],actor,'run.review',{'id':ident,'accepted':accepted});return r

    def dispatch_run(self,controller_id,target_id):
        with self.db.tx() as c:
            controller=self.db.get(c,controller_id,'run');p=self._check_run(c,controller)
            if controller['module']!='control' or p['controller']!='agent':raise PermissionError('需要已授权总控 Agent')
            target=self.db.get(c,target_id,'run');self._check_run(c,target)
            if target['project_id']!=p['id'] or target_id==controller_id:raise PermissionError('只能分派本项目已有授权任务')
            target['dispatched_by']='agent:'+controller_id;self.db.put(c,'run',target)
            self.db.event(c,p['id'],'agent:'+controller_id,'controller.dispatch',{'run_id':target_id})
            return {'run_id':target_id,'status':'authorized','scope_unchanged':True}

    def renew_run(self,actor,ident,note):
        if not note.strip():raise ValueError('需填写续期依据')
        with self.db.tx() as c:
            r=self.db.get(c,ident,'run');p=self._p(c,actor,r['project_id'],{'owner'})
            if r['status'] not in {'authorized','running','waiting_input','candidate'}:raise ValueError('只有未撤回的当前任务可续期')
            old=self.db.get(c,r['grant_id'],'grant');old['revoked']=True;self.db.put(c,'grant',old)
            token=secrets.token_urlsafe(36)
            grant=self._record(c,'grant',p['id'],actor,run_id=ident,token_hash=digest(token.encode()),revoked=False,epoch=p['auth_epoch'],
                               expires=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
            r['grant_id']=grant['id'];self.db.put(c,'run',r);self._check_run(c,r,False)
            self.db.event(c,p['id'],actor,'run.renew',{'run_id':ident,'grant_id':grant['id'],'note':note})
            return {'run':r,'agent_token':token}

    def contract_bundle(self,actor,ident):
        with self.db.tx(False) as c:
            r=self.db.get(c,ident,'run');self._p(c,actor,r['project_id']);self._check_run(c,r)
            f=BytesIO()
            with ZipFile(f,'w',ZIP_DEFLATED) as z:
                z.writestr('contract.json',canonical(r['contract']));z.writestr('contract.sha256',r['contract_hash'])
                z.writestr('result-template.json',canonical({'summary':'','deliverables':[],'needs_info':[]}))
                for ref in r['contract']['inputs']:
                    a=self.db.get(c,ref['id'],'artifact');z.writestr('inputs/'+a['id']+'/'+a['filename'],self._bytes(a))
            return f.getvalue()

    def _tool_context(self,c,p,a):
        return digest([a['id'],a['sha256'],self._gate_signature(c,p,'plan')])

    def _valid_evidence(self,c,p,a,stage):
        for j in self.db.rows(c,'job',p['id']):
            if j['candidate_id']==a['id'] and j['stage']==stage and j['status']=='passed' and j['context']==self._tool_context(c,p,a):
                if j['origin']=='imported' and not j.get('verified_by'): continue
                try:
                    log=self.db.get(c,j['log_id'],'artifact');self._bytes(log)
                    if j.get('provenance')!='real': continue
                except (ValueError,FileNotFoundError,KeyError): continue
                return j
        return None

    def import_evidence(self,actor,project,candidate_id,stage,outcome,log_id,coverage,provenance='real',failure_kind='program',run_id=None):
        if stage not in STAGES or outcome not in {'passed','failed','unavailable'}: raise ValueError('验证阶段或结果无效')
        if provenance not in {'real','synthetic'} or failure_kind not in {'program','environment'}: raise ValueError('证据来源或失败类型无效')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'validator'});a=self.db.get(c,candidate_id,'artifact');log=self.db.get(c,log_id,'artifact')
            if a['project_id']!=project or not a['active'] or a['type'] not in INPUT_TYPES: raise ValueError('候选版本无效')
            if log['project_id']!=project or log['type']!='Original' or log['slot']==a['slot'] or log['payload'].get('purpose')!='evidence': raise ValueError('需关联用途为 evidence 的独立原始日志制品')
            if not self._bytes(log) or not coverage: raise ValueError('需提供原始日志及测试覆盖')
            if run_id:
                run=self.db.get(c,run_id,'run');self._check_run(c,run)
                if run['module']!='validation' or run['project_id']!=project or candidate_id not in {x['id'] for x in run['contract']['inputs']}:
                    raise PermissionError('验证证据不属于该模块合同')
                run['status']='waiting_input';self.db.put(c,'run',run)
            j=self._record(c,'job',project,actor,candidate_id=candidate_id,stage=stage,status='reported',reported_outcome=outcome,
                           log_id=log_id,coverage=coverage,context=self._tool_context(c,p,a),origin='imported',provenance=provenance,failure_kind=failure_kind,
                           run_id=run_id,candidate_sha256=a['sha256'])
            self.db.event(c,project,actor,'evidence.import',{'id':j['id'],'stage':stage,'origin':'operator_reported','provenance':provenance});return j

    def verify_evidence(self,actor,ident,note):
        with self.db.tx() as c:
            j=self.db.get(c,ident,'job');p=self._p(c,actor,j['project_id'],{'reviewer'})
            if j['status']!='reported' or actor==j['author'] or not note.strip(): raise ValueError('原始日志需另一实名审核人核验')
            run=self.db.get(c,j['run_id'],'run') if j.get('run_id') else None
            if run:self._check_run(c,run)
            a=self.db.get(c,j['candidate_id'],'artifact')
            if not a['active'] or j['context']!=self._tool_context(c,p,a): raise ValueError('证据对应工程或工具链已变化')
            self._bytes(self.db.get(c,j['log_id'],'artifact'))
            if j['provenance']!='real' and j['reported_outcome']=='passed': raise ValueError('合成证据不能成为真实验证成功')
            j.update(status=j['reported_outcome'],verified_by=actor,verification_note=note)
            self.db.put(c,'job',j);self._repair_result(c,p,j)
            atype={'compile':'CompileResult','simulation':'SimulationReport'}.get(j['stage'])
            if atype:
                artifact=self._artifact(c,p,actor,atype,f'{j["stage"]} 原始日志核验',{'job_id':j['id']},slot=j['id'])
                if run:
                    if atype not in run['contract']['outputs']:raise PermissionError('验证结果类型不属于模块合同')
                    run.update(status='candidate',results=[artifact['id']],basis=self._basis(c,p),summary='原始日志经独立人工核验；自动验证未执行')
                    self.db.put(c,'run',run)
            self.db.event(c,p['id'],actor,'evidence.verify',{'id':ident,'status':j['status']});return j

    def _repair_result(self,c,p,job):
        if job['stage']!='compile': return
        if job.get('failure_counted'):return
        if job['status']=='unavailable' or (job['status']=='failed' and job.get('failure_kind')=='environment'):
            p['environment_failures']+=1;job['failure_counted']=True
            self.db.put(c,'job',job);self.db.put(c,'project',p);return
        # A repair round is counted once, only after a confirmed patch candidate is recompiled.
        patches=[x for x in self.db.rows(c,'patch',p['id']) if x.get('candidate_id')==job['candidate_id'] and x['status']=='applied']
        if not patches: return
        patch=patches[-1]
        if patch.get('counted_job'): return
        if job['status']=='failed':
            p['failure_streak']+=1;patch['counted_job']=job['id']
        elif job['status']=='passed':
            p['failure_streak']=0;patch['counted_job']=job['id']
        self.db.put(c,'patch',patch)
        job['failure_counted']=True;self.db.put(c,'job',job)
        if p['failure_streak']>=3:
            p['stopped']=True
            proof=self._artifact(c,p,'system','ManualInterventionRecord','连续三轮失败转人工',{'reason':'连续三轮程序修复重编译失败','failed_rounds':3})
            self._record(c,'intervention',p['id'],job.get('verified_by',job['author']),type='ManualInterventionRecord',artifact_id=proof['id'],reason='连续三轮程序修复重编译失败',failed_rounds=3,closed=False)
        self.db.put(c,'project',p)

    def propose_patch(self,actor,project,base_id,failure_job_id,reason,rollback,data,filename,payload):
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'engineer'});a=self.db.get(c,base_id,'artifact');j=self.db.get(c,failure_job_id,'job')
            if p['stopped']: raise ValueError('已停止修复，需人工接管')
            if a['project_id']!=project or a['type']!='CodeBundle' or not a['active']: raise ValueError('补丁必须绑定当前候选')
            if j['project_id']!=project or j['candidate_id']!=base_id or j['status']!='failed' or j['stage']!='compile' or j['failure_kind']!='program': raise ValueError('需绑定该版本真实编译失败证据')
            if not reason or not rollback or not filename or not data: raise ValueError('需填写原因、回退与候选文件')
            if digest(data)==a['sha256']:raise ValueError('补丁候选未发生变化')
            self._bytes(a)
            patch=self._record(c,'patch',project,actor,base_id=base_id,failure_job_id=failure_job_id,reason=reason,rollback=rollback,
                               sha256=self._blob(data),filename=filename,payload=payload,status='proposed',context=self._tool_context(c,p,a))
            self.db.event(c,project,actor,'patch.propose',{'id':patch['id'],'sha256':patch['sha256']});return patch

    def approve_patch(self,actor,ident,sha256,note):
        with self.db.tx() as c:
            patch=self.db.get(c,ident,'patch');p=self._p(c,actor,patch['project_id'],{'owner','reviewer'})
            a=self.db.get(c,patch['base_id'],'artifact')
            if p['stopped'] or not a['active'] or patch['context']!=self._tool_context(c,p,a): raise ValueError('补丁基线已过期或已停止')
            if patch['status']!='proposed' or patch['sha256']!=sha256 or not note.strip(): raise ValueError('补丁批准对象已变化或缺少依据')
            if actor==patch['author']: raise PermissionError('需独立人工审核补丁')
            patch.update(status='approved',approved_by=actor,approval_note=note);self.db.put(c,'patch',patch)
            self.db.event(c,p['id'],actor,'patch.approve',{'id':ident,'sha256':sha256});return patch

    def apply_patch(self,actor,ident):
        with self.db.tx() as c:
            patch=self.db.get(c,ident,'patch');p=self._p(c,actor,patch['project_id'],{'engineer'})
            if patch['status']=='applied': return patch
            a=self.db.get(c,patch['base_id'],'artifact')
            if p['stopped'] or patch['status']!='approved' or not a['active'] or patch['context']!=self._tool_context(c,p,a): raise ValueError('补丁未获有效批准')
            data=(self.root/'blobs'/patch['sha256'][:2]/patch['sha256']).read_bytes()
            if digest(data)!=patch['sha256']: raise ValueError('补丁摘要不一致')
            # A complete reviewed candidate snapshot is installed as a NEW version; no source file is overwritten.
            new=self._artifact(c,p,actor,'CodeBundle',a['title'],patch['payload'],data,a['slot'],patch['filename'],repair=True)
            patch.update(status='applied',candidate_id=new['id']);self.db.put(c,'patch',patch)
            self.db.event(c,p['id'],actor,'patch.apply',{'id':ident,'candidate_id':new['id']});return patch

    def take_over(self,actor,project,note):
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner'})
            if not p['stopped'] or not note.strip(): raise ValueError('需人工接管说明')
            p['stopped']=False;p['failure_streak']=0;p['auth_epoch']+=1;self.db.put(c,'project',p)
            for i in self.db.rows(c,'intervention',project):
                if not i['closed']: i.update(closed=True,by=actor,note=note);self.db.put(c,'intervention',i)
            self.db.event(c,project,actor,'repair.takeover',{'note':note});return p

    def reset_flow(self,actor,project,note):
        if not note.strip():raise ValueError('需填写重新立案与交接说明')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner'})
            for r in self.db.rows(c,'run',project):
                if r['status'] not in {'accepted','cancelled','stale'}:
                    if r['grant_id']:
                        g=self.db.get(c,r['grant_id'],'grant');g['revoked']=True;self.db.put(c,'grant',g)
                    r['status']='cancelled';self.db.put(c,'run',r)
            p['flow_epoch']=p.get('flow_epoch',1)+1;self.db.put(c,'project',p)
            self.db.event(c,project,actor,'graph.reset',{'flow_epoch':p['flow_epoch'],'note':note});return p

    def risk(self,actor,project,severity,description,mitigation,rollback):
        if severity not in {'critical','high','medium','low'} or not all([description,mitigation,rollback]): raise ValueError('风险信息不完整')
        with self.db.tx() as c:
            self._p(c,actor,project,{'engineer','reviewer','owner'})
            r=self._record(c,'risk',project,actor,severity=severity,description=description,mitigation=mitigation,rollback=rollback,status='open')
            self.db.event(c,project,actor,'risk.create',{'id':r['id'],'severity':severity});return r

    def dispose_risk(self,actor,ident,action,note,evidence_ids):
        if action not in {'closed','waived'} or not note.strip() or not evidence_ids: raise ValueError('需处置决定、依据和证据')
        with self.db.tx() as c:
            r=self.db.get(c,ident,'risk');self._p(c,actor,r['project_id'],{'reviewer'} if action=='closed' else {'owner'})
            if actor==r['author']: raise PermissionError('风险处置需独立审核')
            if r['severity'] in {'critical','high'} and action!='closed': raise PermissionError('严重／高风险不能豁免')
            for ident in evidence_ids:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=r['project_id'] or not a['active']: raise ValueError('风险证据不属于当前项目版本')
                self._bytes(a)
            r.update(status=action,note=note,evidence_ids=evidence_ids,decision_by=actor,disposition_context=self._basis(c,self.db.get(c,r['project_id'],'project')));self.db.put(c,'risk',r)
            self.db.event(c,r['project_id'],actor,'risk.dispose',{'id':r['id'],'status':action});return r

    def release(self,actor,project,signature):
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner'});s=self._gate_status(c,p,'release')
            if not s['approved'] or s['signature']!=signature or s['blockers']: raise ValueError('需对当前工程完成发布锁终审')
            arts=list(self._latest(c,project).values())
            manifest={'schema':'EngineeringReleaseManifest/v1','project_id':project,'delivery':p['delivery'],'environment':self.environment,'created_at':now(),
                      'artifacts':[{'id':a['id'],'type':a['type'],'version':a['version'],'sha256':a['sha256'],'filename':a['filename']} for a in arts],
                      'gate_decisions':{g:self._gate_status(c,p,g)['decision'] for g in GATES[:5]},
                      'jobs':self.db.rows(c,'job',project),'risks':self.db.rows(c,'risk',project),'signature':signature,
                      'module_contracts':self.db.rows(c,'run',project),'knowledge_versions':[]}
            for run in self.db.rows(c,'run',project):
                if run['status']!='accepted' or not any(self.db.get(c,i,'artifact')['active'] for i in run['results']):continue
                for ref in run['contract']['knowledge']:
                    knowledge=self._use_knowledge(c,actor,ref['id'],project,formal=True)
                    if digest(knowledge)!=ref['hash']:raise ValueError('工程依据知识已变化，需重新审核')
                    manifest['knowledge_versions'].append(knowledge)
            # Include the exact evidence closure, even when a historical log/candidate is no longer latest.
            included={a['id']:a for a in arts};references=[]
            for job in manifest['jobs']:
                references.extend([job['candidate_id']]);references.extend([job['log_id']] if job.get('log_id') else [])
                if job.get('reconciliation_log'):references.append(job['reconciliation_log'])
            for risk in manifest['risks']:references.extend(risk.get('evidence_ids',[]))
            for run in manifest['module_contracts']:
                references.extend(x['id'] for x in run['contract']['inputs']);references.extend(run['results'])
            for knowledge in manifest['knowledge_versions']:references.extend(knowledge['sources'])
            for ident in references:
                if ident not in included:included[ident]=self.db.get(c,ident,'artifact')
            for a in included.values():
                self.auth.require(c,actor,a['project_id']);self._bytes(a)
            manifest['artifacts']=[{'id':a['id'],'type':a['type'],'version':a['version'],'sha256':a['sha256'],'filename':a['filename'],
                                    'record_hash':a['record_hash'],'current_at_release':a['active']} for a in included.values()]
            r=self._record(c,'release',project,actor,manifest=manifest,manifest_hash=digest(manifest),signature=signature,status='locked')
            p['lifecycle']['release']='released';self.db.put(c,'project',p)
            self.db.event(c,project,actor,'release.lock',{'id':r['id'],'manifest_hash':r['manifest_hash']});return r

    def export_release(self,actor,ident):
        with self.db.tx(False) as c:
            r=self.db.get(c,ident,'release');p=self._p(c,actor,r['project_id'])
            if r['manifest_hash']!=digest(r['manifest']) or r['signature']!=self._gate_signature(c,p,'release') or not self._gate_status(c,p,'release')['approved']:
                raise ValueError('工程、权限、证据或摘要已变化，旧发布包不可导出')
            f=BytesIO()
            with ZipFile(f,'w',ZIP_DEFLATED) as z:
                z.writestr('EngineeringReleaseManifest.json',canonical(r['manifest']))
                z.writestr('manifest.sha256',r['manifest_hash'])
                for ref in r['manifest']['artifacts']:
                    a=self.db.get(c,ref['id'],'artifact');data=self._bytes(a)
                    self.auth.require(c,actor,a['project_id'])
                    if a['sha256']!=ref['sha256']: raise ValueError('锁定制品摘要不一致')
                    z.writestr('artifacts/'+a['id']+'/'+a['filename'],data)
            return f.getvalue()

    def lifecycle(self,actor,project,stage,note,evidence_ids):
        if stage not in {'implementation','site','benefit'} or not note.strip() or not evidence_ids: raise ValueError('需独立记录实施／现场／效果及依据')
        with self.db.tx() as c:
            p=self._p(c,actor,project,{'owner','validator'})
            if p['lifecycle']['release']!='released': raise ValueError('尚未形成发布工程包')
            for ident in evidence_ids:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=project: raise PermissionError('证据跨项目')
                self._bytes(a)
            p['lifecycle'][stage]='recorded';self.db.put(c,'project',p)
            r=self._record(c,'lifecycle',project,actor,stage=stage,note=note,evidence_ids=evidence_ids,kind_of_evidence='operator_reported')
            self.db.event(c,project,actor,'lifecycle.record',{'id':r['id'],'stage':stage});return r

    def _knowledge_valid(self,c,k,seen=None):
        if k['status'] in {'withdrawn','retired'}:return False
        seen=set() if seen is None else seen
        if k['id'] in seen:return False
        seen=seen|{k['id']}
        try:
            if k['domain']=='production' and k['status']=='published':
                if len(set(k['approvers']))<2:return False
                for reviewer in k['approvers']:self.auth.require(c,reviewer,k['project_id'],{'reviewer'})
            for ident in k['sources']:
                a=self.db.get(c,ident,'artifact')
                if not a['active']:return False
                self._bytes(a)
            for ident in k.get('dependencies',[]):
                if not self._knowledge_valid(c,self.db.get(c,ident,'knowledge'),seen):return False
        except (KeyError,ValueError,FileNotFoundError,PermissionError):return False
        return True

    def knowledge(self,actor,project,title,domain,sources,applicability,validation_depth,dependencies=None,classification='internal'):
        if domain not in {'personal','production'} or classification not in {'internal','restricted','public'} or not title or not sources or not applicability or not validation_depth:
            raise ValueError('需知识域、来源、适用性和验证深度')
        if not isinstance(applicability,dict) or any(value is None or value=='' for value in applicability.values()):raise ValueError('适用性不能包含未知设备或 CPU')
        with self.db.tx() as c:
            self._p(c,actor,project,{'knowledge','engineer','owner'})
            for ident in sources:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=project or not a['active']:raise ValueError('知识来源无效')
                self._bytes(a)
                levels={'public':0,'internal':1,'restricted':2}
                if levels[classification]<levels[a.get('classification','internal')]:raise PermissionError('知识发布不能降低来源资料分级')
            for ident in dependencies or []:self._use_knowledge(c,actor,ident,project,formal=False)
            k=self._record(c,'knowledge',project,actor,type='KnowledgeVersion',title=title,domain=domain,sources=sources,applicability=applicability,
                           validation_depth=validation_depth,dependencies=dependencies or [],classification=classification,status='candidate',approvers=[],checks={})
            self.db.event(c,project,actor,'knowledge.candidate',{'id':k['id'],'domain':domain});return k

    def knowledge_review(self,actor,ident,action,note,evidence_ids=None):
        if action not in {'accept','redaction','domain_review','regression','approve','publish','withdraw','retire'} or not note.strip():raise ValueError('知识审核动作或依据无效')
        with self.db.tx() as c:
            k=self.db.get(c,ident,'knowledge');self._p(c,actor,k['project_id'],{'knowledge','reviewer','owner'})
            if action in {'withdraw','retire'}:
                k.update(status='withdrawn' if action=='withdraw' else 'retired',withdrawal_note=note)
            else:
                if not self._knowledge_valid(c,k):raise ValueError('来源或依赖知识已失效')
                if k['status'] in {'published','accepted'}:raise ValueError('已发布版本不可原地修改')
                if k['domain']=='personal':
                    if action!='accept' or actor!=k['author']:raise PermissionError('个人知识需本人明确接受')
                    k['status']='accepted'
                elif action in {'redaction','domain_review','regression'}:
                    if not evidence_ids:raise ValueError('需关联脱敏／领域审核／回归证据')
                    for ident in evidence_ids:
                        a=self.db.get(c,ident,'artifact')
                        if a['project_id']!=k['project_id'] or not a['active']:raise ValueError('知识审核证据无效')
                        if action=='regression' and (a['type']!='Original' or a['payload'].get('purpose')!='evidence'):
                            raise ValueError('样板回归须绑定独立原始测试记录')
                        self._bytes(a)
                    k['checks'][action]={'by':actor,'note':note,'evidence_ids':evidence_ids}
                elif action=='approve':
                    if set(k['checks'])!={'redaction','domain_review','regression'}:raise ValueError('尚未完成脱敏、领域审核与样板回归')
                    if actor==k['author'] or actor in k['approvers']:raise PermissionError('需两名不同的独立实名审核人')
                    person=self.auth.require(c,actor,k['project_id'],{'reviewer'})
                    names={self.auth.user(c,who)['display_name'].strip().casefold() for who in [k['author'],*k['approvers']]}
                    if person['display_name'].strip().casefold() in names:raise PermissionError('审核人实名标识必须与作者和另一审核人不同')
                    k['approvers'].append(actor)
                elif action=='publish':
                    if len(set(k['approvers']))<2:raise ValueError('需两名不同实名审核人批准')
                    for reviewer in k['approvers']:self.auth.require(c,reviewer,k['project_id'],{'reviewer'})
                    for dep in k['dependencies']:self._use_knowledge(c,actor,dep,k['project_id'],formal=True)
                    k['status']='published'
                else:raise ValueError('生产知识不能走个人接受流程')
            self.db.put(c,'knowledge',k)
            impacted={k['id']}
            all_knowledge=self.db.rows(c,'knowledge')
            while True:
                extra={x['id'] for x in all_knowledge if set(x['dependencies']) & impacted}
                if extra<=impacted:break
                impacted|=extra
            affected=[r for r in self.db.rows(c,'run') if any(x['id'] in impacted for x in r['contract']['knowledge'])]
            affected_ids=[r['id'] for r in affected];projects=sorted({r['project_id'] for r in affected})
            self.db.event(c,k['project_id'],actor,'knowledge.'+action,{'id':k['id'],'affected_runs':affected_ids,'affected_projects':projects,'note':note})
            return {**k,'affected_runs':affected_ids,'affected_projects':projects}

    def _use_knowledge(self,c,actor,ident,target_project,formal):
        k=self.db.get(c,ident,'knowledge')
        self.auth.require(c,actor,k['project_id'])
        if k['domain']=='personal' and actor!=k['author']:raise PermissionError('个人参考库仅知识所有者可用')
        if not self._knowledge_valid(c,k):raise PermissionError('知识已撤回、替代或来源失效')
        if formal and (k['domain']!='production' or k['status']!='published'):raise PermissionError('正式工程依据必须为已发布生产知识')
        if not formal and k['status'] not in {'published','accepted'}:raise PermissionError('知识尚未接受或发布')
        p=self.db.get(c,target_project,'project')
        base=next((a for a in self._latest(c,p['id']).values() if a['type']=='ToolchainProfile'),None)
        for key,value in k['applicability'].items():
            if not base or base['payload'].get(key)!=value:raise ValueError('知识适用性不匹配：'+key)
        return k

    def knowledge_list(self,actor,project,formal=False):
        with self.db.tx(False) as c:
            self._p(c,actor,project);out=[]
            for k in self.db.rows(c,'knowledge'):
                try:self._use_knowledge(c,actor,k['id'],project,formal)
                except (ValueError,PermissionError,KeyError):continue
                out.append(k)
            return out

    def search_knowledge(self,actor,project,query,formal=True):
        import re
        if not str(query).strip():raise ValueError('请输入检索词')
        terms=re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]',query.lower())
        with self.db.tx(False) as c:
            self._p(c,actor,project);results=[]
            for candidate in self.db.rows(c,'knowledge'):
                try:k=self._use_knowledge(c,actor,candidate['id'],project,formal)
                except (ValueError,PermissionError,KeyError):continue
                citations=[];text=k['title']+' '+k['validation_depth']
                for ident in k['sources']:
                    a=self.db.get(c,ident,'artifact');raw=self._bytes(a)
                    text+=' '+raw[:60000].decode('utf-8',errors='replace')
                    citations.append({'artifact_id':ident,'sha256':a['sha256'],'version':a['version']})
                score=sum(text.lower().count(term) for term in terms)
                if score:results.append({'knowledge':k,'score':score,'citations':citations,'retrieval':'offline_keyword'})
            return sorted(results,key=lambda x:(-x['score'],x['knowledge']['id']))[:8]

    def legacy_mapping(self,actor,project,namespace,legacy_id,original_id,source_hash,note):
        if not all([namespace,legacy_id,note]):raise ValueError('需历史标识、命名域与复核说明')
        with self.db.tx() as c:
            self._p(c,actor,project,{'owner'});a=self.db.get(c,original_id,'artifact')
            if a['project_id']!=project or a['type']!='Original' or a['sha256']!=source_hash:raise ValueError('历史映射需绑定本项目原件与来源哈希')
            self._bytes(a)
            if any(m['namespace']==namespace and m['legacy_id']==legacy_id for m in self.db.rows(c,'legacy_mapping',project)):
                raise ValueError('历史标识已有映射，保留旧记录，不能原地改写')
            m=self._record(c,'legacy_mapping',project,actor,namespace=namespace,legacy_id=legacy_id,original_id=original_id,source_hash=source_hash,
                           note=note,status='requires_revalidation',legacy_contract_mutated=False)
            self.db.event(c,project,actor,'legacy.map',{'id':m['id'],'legacy_id':legacy_id});return m

    def component(self,actor,project,name,version,license,source_hash,network,permissions,regression_ids,decision):
        if not all([name,version,license,source_hash,network,permissions,regression_ids]) or decision not in {'candidate','approved','rejected'}:
            raise ValueError('组件准入需版本、许可、摘要、网络、权限与回归依据')
        if len(source_hash)!=64:raise ValueError('需完整 SHA-256')
        with self.db.tx() as c:
            self._p(c,actor,project,{'owner','reviewer'})
            for ident in regression_ids:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=project:raise ValueError('组件回归证据跨项目')
                self._bytes(a)
            record=self._record(c,'component',project,actor,name=name,version=version,license=license,source_hash=source_hash,
                                network=network,permissions=permissions,regression_ids=regression_ids,decision=decision)
            self.db.event(c,project,actor,'component.admission',{'id':record['id'],'decision':decision});return record

    def metric(self,actor,project,name,definition,value,unit,period,source_ids,kind='baseline'):
        if kind not in {'baseline','observation','target'} or not all([name,definition,unit,period,source_ids]):raise ValueError('需完整指标口径、窗口和证据')
        if not isinstance(value,(int,float)) or value<0:raise ValueError('指标值无效')
        with self.db.tx() as c:
            self._p(c,actor,project,{'owner','engineer'})
            if kind=='target' and not any(m['name']==name and m['kind']=='baseline' for m in self.db.rows(c,'metric',project)):
                raise ValueError('先建立真实人工基线，再设目标')
            for ident in source_ids:
                a=self.db.get(c,ident,'artifact')
                if a['project_id']!=project:raise ValueError('指标来源跨项目')
                self._bytes(a)
            r=self._record(c,'metric',project,actor,name=name,definition=definition,value=value,unit=unit,period=period,source_ids=source_ids,kind=kind)
            self.db.event(c,project,actor,'metric.record',{'id':r['id'],'kind':kind});return r
