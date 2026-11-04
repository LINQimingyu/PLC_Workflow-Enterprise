"""Versioned Agent/Skill/tool configuration. Metadata never grants execution rights."""
import re
from .catalog import MODULES,method,digest
from .db import uid,now

KINDS={'agent','skill','tool'}

def builtin_id(kind,key):return 'builtin-'+kind+'-'+key

class Maintenance:
    def __init__(self,service):self.s=service

    def _admin(self,c,actor):
        if not self.s.auth.user(c,actor)['admin']:raise PermissionError('维护配置需要系统管理员')

    def builtins(self):
        out=[]
        for module,(name,role,outputs,tools) in MODULES.items():
            for kind,text in [('agent',f'在{module}模块合同范围内协助{name}。现实责任岗位：{role}。交付：'+'、'.join(outputs)+'。遇到缺项停止并说明；不能扩大权限、自行审核、豁免风险或发布工程。'),('skill',method(module)['instructions'])]:
                out.append(self._builtin(kind,module,name+(' Agent' if kind=='agent' else ' Skill'),[module],text))
        for tool in sorted({t for m in MODULES.values() for t in m[3]}):
            modules=[m for m,v in MODULES.items() if tool in v[3]]
            out.append(self._builtin('tool',tool,tool,modules,'使用平台已实现的受控工具；仍需模块合同和执行授权。',tool))
        return {x['id']:x for x in out}

    @staticmethod
    def _builtin(kind,key,name,modules,instructions,implementation=''):
        payload={'name':name,'modules':modules,'instructions':instructions,'implementation':implementation}
        return {'id':builtin_id(kind,key),'kind':kind,'key':key,'version':0,'status':'published','builtin':True,
                'payload':payload,'sha256':digest(payload),'author':'source','created_at':None}

    def _get(self,c,ident,all_builtins=None):
        if not isinstance(ident,str) or len(ident)>200:raise ValueError('能力版本标识无效')
        if ident.startswith('builtin-'):
            builtins=all_builtins if all_builtins is not None else self.builtins()
            if ident not in builtins:raise KeyError('内置能力不存在')
            return builtins[ident]
        return self.s.db.get(c,ident,'capability_version')

    def _enabled(self,c,ident):
        try:return self.s.db.get(c,'capability-control-'+ident,'capability_control')['enabled']
        except KeyError:return True

    def _usable(self,c,ident,kind,module,builtins=None):
        v=self._get(c,ident,builtins)
        if v['kind']!=kind or module not in v['payload']['modules']:raise ValueError('能力类型或适用模块不匹配')
        if v['sha256']!=digest(v['payload']):raise ValueError('能力版本摘要损坏')
        if v['status']!='published' or not self._enabled(c,ident):raise ValueError('能力未发布或已停用：'+v['payload']['name'])
        return v

    def binding(self,c,module):
        if module not in MODULES:raise ValueError('工作模块无效')
        try:b=self.s.db.get(c,'capability-binding-'+module,'capability_binding')
        except KeyError:
            b={'module':module,'agent_id':builtin_id('agent',module),'skill_id':builtin_id('skill',module),
               'tool_ids':[builtin_id('tool',t) for t in MODULES[module][3]],'author':'source'}
        return {**b,'revision':digest(b)}

    def effective_catalog(self,actor):
        from .catalog import catalog
        result=catalog()
        with self.s.db.tx(False) as c:
            self.s.auth.user(c,actor);builtins=self.builtins()
            for module in result['modules']:
                b=self.binding(c,module['id']);module['tools']=[];module['configuration_available']=True
                for kind in ['agent','skill']:
                    try:
                        v=self._usable(c,b[kind+'_id'],kind,module['id'],builtins)
                        module[kind+'_version']={'id':v['id'],'name':v['payload']['name'],'version':v['version']}
                    except (ValueError,PermissionError,KeyError):module['configuration_available']=False
                for ident in b['tool_ids']:
                    try:tool=self._usable(c,ident,'tool',module['id'],builtins)
                    except (ValueError,PermissionError,KeyError):continue
                    module['tools'].append(tool['payload']['implementation'])
        return result

    def listing(self,actor):
        with self.s.db.tx(False) as c:
            self._admin(c,actor)
            versions=[*self.builtins().values(),*self.s.db.rows(c,'capability_version')]
            items=[{k:v for k,v in x.items() if k!='payload'}|{'name':x['payload']['name'],'modules':x['payload']['modules'],
                    'implementation':x['payload']['implementation'],'enabled':self._enabled(c,x['id'])} for x in versions]
            return {'items':items,'bindings':[self.binding(c,m) for m in MODULES],
                    'modules':[{'id':m,'name':v[0],'tools':v[3]} for m,v in MODULES.items()]}

    def read(self,actor,ident):
        with self.s.db.tx(False) as c:
            self._admin(c,actor);v=self._get(c,ident)
            history=[x for x in [*self.builtins().values(),*self.s.db.rows(c,'capability_version')] if (x['kind'],x['key'])==(v['kind'],v['key'])]
            return {**v,'enabled':self._enabled(c,ident),'events':c.execute("SELECT seq,actor,action,data,created_at FROM ep_events WHERE action LIKE %s AND data->>'id'=%s ORDER BY seq DESC LIMIT 50",('capability.%',ident)).fetchall(),'history':[{'id':x['id'],'version':x['version'],'status':x['status'],'sha256':x['sha256']} for x in sorted(history,key=lambda x:x['version'])]}

    def _payload(self,kind,name,modules,instructions,implementation):
        if not isinstance(kind,str) or kind not in KINDS:raise ValueError('能力类型无效')
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('需填写名称（最多100字）')
        if not isinstance(modules,list) or not modules or len(modules)>len(MODULES) or any(not isinstance(m,str) or m not in MODULES for m in modules):raise ValueError('请选择有效工作模块')
        if not isinstance(instructions,str) or not instructions.strip() or len(instructions)>50000:raise ValueError('需填写方法或职责说明（最多50000字）')
        if kind=='tool':
            if not isinstance(implementation,str) or not implementation or any(implementation not in MODULES[m][3] for m in modules):
                raise ValueError('工具只能绑定适用模块中已准入的实现；新代码适配器需单独集成')
        elif implementation:raise ValueError('Agent／Skill 不能声明工具执行实现')
        return {'name':name.strip(),'modules':sorted(set(modules)),'instructions':instructions,'implementation':implementation}

    def create(self,actor,kind,key,name,modules,instructions,implementation='',base_id=None,expected_sha=None,note=''):
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9._-]{1,79}',key):raise ValueError('标识需2～80位小写字母、数字、点、横线或下划线')
        payload=self._payload(kind,name,modules,instructions,implementation)
        if not isinstance(note,str) or not note.strip():raise ValueError('需填写本次维护原因')
        with self.s.db.tx() as c:
            self._admin(c,actor);all_versions=[*self.builtins().values(),*self.s.db.rows(c,'capability_version')]
            history=[v for v in all_versions if (v['kind'],v['key'])==(kind,key)]
            if history and not base_id:raise ValueError('标识已存在，请从现有版本派生新版本')
            if base_id:
                base=self._get(c,base_id)
                if (base['kind'],base['key'])!=(kind,key) or base['sha256']!=expected_sha:raise ValueError('派生来源或摘要已变化')
            v={'id':uid('cap'),'project_id':'','kind':kind,'key':key,'version':max([x['version'] for x in history],default=0)+1,
               'status':'draft','builtin':False,'payload':payload,'sha256':digest(payload),'base_id':base_id,'author':actor,'created_at':now()}
            self.s.db.put(c,'capability_version',v);self.s.db.event(c,'',actor,'capability.create',{'id':v['id'],'sha256':v['sha256'],'note':note})
            return v

    def edit(self,actor,ident,expected_sha,name,modules,instructions,implementation='',note=''):
        with self.s.db.tx() as c:
            self._admin(c,actor);v=self._get(c,ident)
            if v['builtin'] or v['status']!='draft':raise ValueError('已发布版本不可改写，请派生新版本')
            if v['sha256']!=expected_sha:raise ValueError('草稿已变化，请重新读取')
            if not isinstance(note,str) or not note.strip():raise ValueError('需填写维护原因')
            payload=self._payload(v['kind'],name,modules,instructions,implementation)
            v.update(payload=payload,sha256=digest(payload),edited_at=now(),edited_by=actor)
            self.s.db.put(c,'capability_version',v);self.s.db.event(c,'',actor,'capability.edit',{'id':ident,'sha256':v['sha256'],'note':note});return v

    def publish(self,actor,ident,expected_sha,note):
        with self.s.db.tx() as c:
            self._admin(c,actor);v=self._get(c,ident)
            if v['builtin'] or v['status']!='draft' or v['sha256']!=expected_sha or v['sha256']!=digest(v['payload']):raise ValueError('需选择摘要一致的草稿版本')
            if not isinstance(note,str) or not note.strip():raise ValueError('需填写发布依据')
            v.update(status='published',published_by=actor,published_at=now())
            self.s.db.put(c,'capability_version',v);self.s.db.event(c,'',actor,'capability.publish',{'id':ident,'sha256':v['sha256'],'note':note});return v

    def enable(self,actor,ident,enabled,note):
        if not isinstance(enabled,bool) or not isinstance(note,str) or not note.strip():raise ValueError('需明确启停决定和依据')
        with self.s.db.tx() as c:
            self._admin(c,actor);v=self._get(c,ident)
            if v['status']!='published':raise ValueError('只能启停已发布版本')
            state={'id':'capability-control-'+ident,'project_id':'','version_id':ident,'enabled':enabled,'author':actor,'updated_at':now()}
            self.s.db.put(c,'capability_control',state);self.s.db.event(c,'',actor,'capability.enable',{'id':ident,'enabled':enabled,'note':note});return state

    def bind(self,actor,module,agent_id,skill_id,tool_ids,expected_revision,note):
        if not isinstance(tool_ids,list) or len(tool_ids)>30 or any(not isinstance(t,str) for t in tool_ids) or len(tool_ids)!=len(set(tool_ids)):raise ValueError('工具绑定需为不重复的版本列表')
        if not isinstance(note,str) or not note.strip():raise ValueError('需填写绑定依据')
        with self.s.db.tx() as c:
            self._admin(c,actor);old=self.binding(c,module)
            if old['revision']!=expected_revision:raise ValueError('模块绑定已变化，请刷新后重新确认')
            builtins=self.builtins();self._usable(c,agent_id,'agent',module,builtins);self._usable(c,skill_id,'skill',module,builtins)
            implementations=[]
            for ident in tool_ids:implementations.append(self._usable(c,ident,'tool',module,builtins)['payload']['implementation'])
            if len(implementations)!=len(set(implementations)):raise ValueError('同一个工具实现不能重复绑定')
            value={'id':'capability-binding-'+module,'project_id':'','module':module,'agent_id':agent_id,'skill_id':skill_id,
                   'tool_ids':tool_ids,'author':actor,'updated_at':now()}
            self.s.db.put(c,'capability_binding',value);self.s.db.event(c,'',actor,'capability.bind',{'module':module,'binding':value,'note':note});return value

    def resolve(self,c,module,tools):
        b=self.binding(c,module);builtins=self.builtins()
        agent=self._usable(c,b['agent_id'],'agent',module,builtins);skill=self._usable(c,b['skill_id'],'skill',module,builtins)
        available={}
        for ident in b['tool_ids']:
            v=self._get(c,ident,builtins)
            if v['status']=='published' and self._enabled(c,ident):available[v['payload']['implementation']]=v
        selected=[]
        for name in tools:
            if name not in available:raise PermissionError('工具未绑定或已停用：'+name)
            selected.append(self._usable(c,available[name]['id'],'tool',module,builtins))
        refs=[{'id':v['id'],'sha256':v['sha256']} for v in [agent,skill,*selected]]
        skill_snapshot={'id':module,'instructions':skill['payload']['instructions'],'sha256':digest(skill['payload']['instructions'].encode()),
                        'version_id':skill['id'],'version':skill['version'],'name':skill['payload']['name']}
        agent_snapshot={'id':agent['id'],'version':agent['version'],'name':agent['payload']['name'],'instructions':agent['payload']['instructions'],'sha256':agent['sha256']}
        return agent_snapshot,skill_snapshot,refs

    def check_refs(self,c,contract):
        refs=contract.get('capability_refs')
        builtins=self.builtins()
        if refs is None:
            # Old task contracts stay immutable; emergency stop still covers their built-ins.
            ids=[builtin_id('agent',contract['module']),builtin_id('skill',contract['module']),*[builtin_id('tool',t) for t in contract['tools']]]
            if any(not self._enabled(c,i) for i in ids):raise PermissionError('任务依赖的内置能力已停用')
            return
        for ref in refs:
            v=self._get(c,ref['id'],builtins)
            if v['sha256']!=ref['sha256'] or v['sha256']!=digest(v['payload']) or v['status']!='published' or not self._enabled(c,v['id']):
                raise PermissionError('任务依赖的能力版本已停用或失效：'+v['payload']['name'])
