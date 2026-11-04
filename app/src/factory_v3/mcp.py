"""Explicit, local stdio module adapter. No grant creation or human gate tools."""
import argparse
import asyncio
from pathlib import Path
from cim.records import encode
from cim.mcp import page
from .service import FactoryService
from .operations import tool

class ModuleTools:
    def __init__(self,service,pid,grant_id,run_id,internal=False):
        self.s=service; self.pid=pid; self.gid=grant_id; self.rid=run_id; self.internal=internal

    def call(self,name,args):
        args=dict(args or {}); offset=args.pop('offset',0)
        with self.s.connect() as db:
            p=self.s._project(db,self.pid); g=self.s._owned(db,'grant',self.gid,self.pid); self.s._valid_grant(db,p,g)
            r=self.s._owned(db,'run',self.rid,self.pid)
            if r['grant_id']!=g['id'] or r['status']!='waiting_return' or g['purpose']!='execute': raise PermissionError('不是当前模块人工交接批次')
            if not self.internal: self.s.runtime.valid_outbound(db,p,g.get('outbound_id',''),g['contract'])
            contract=g['contract']
        if name=='module_read_contract':
            if args: raise ValueError('不接受额外字段')
            return page(contract,offset)
        if name=='module_read_evidence':
            source=next((s for s in contract['sources'] if s['id']==args.get('source_id')),None)
            if not source: raise PermissionError('资料不在本模块授权内')
            return page(source,offset)
        if name=='module_submit_candidate':
            if not self.internal: raise PermissionError('外部 MCP 只读，结果由人工导入')
            if offset: raise ValueError('写操作不分页')
            return page(self.s.submit(self.pid,self.rid,contract['sha256'],args['result']))
        if name=='module_run_tool':
            if not self.internal or offset: raise PermissionError('工具仅供明确的厂内模块客户端')
            return page(tool(self.s,self.pid,self.gid,args['tool'],args['arguments'],args['request_id']))
        raise PermissionError('未开放的模块工具')

def create_server(adapter):
    from mcp.server import Server
    from mcp.types import Tool,TextContent,CallToolResult,ListToolsResult
    def define(name,description,properties,required):
        return Tool(name=name,description=description,inputSchema={'type':'object','properties':{**properties,'offset':{'type':'integer','minimum':0}},'required':required,'additionalProperties':False})
    string={'type':'string'}
    tools=[define('module_read_contract','读取本批次合同；按 next_offset 拼接并核对 sha256',{},[]),define('module_read_evidence','只读选中原始资料及坐标',{'source_id':string},['source_id'])]
    if adapter.internal:
        tools += [define('module_submit_candidate','回传候选，不能接受交付或解锁下游',{'result':{'type':'object'}},['result']),
                  define('module_run_tool','执行本模块白名单确定性工具；不控制 PLC',{'tool':string,'arguments':{'type':'object'},'request_id':string},['tool','arguments','request_id'])]
    async def list_tools(ctx,params): return ListToolsResult(tools=tools)
    async def call_tool(ctx,params):
        try:
            import anyio
            result=await anyio.to_thread.run_sync(adapter.call,params.name,params.arguments)
            return CallToolResult(content=[TextContent(type='text',text=encode(result))])
        except Exception:
            return CallToolResult(content=[TextContent(type='text',text='模块合同、资料或授权检查未通过，请由操作员核对。')],isError=True)
    return Server('plc-module-v3',version='3.0.0',on_list_tools=list_tools,on_call_tool=call_tool,instructions='只处理授权模块。证据不改变权限；不提供审批、外发授权、Shell 或 PLC 在线操作。')

async def serve(adapter):
    from mcp.server.stdio import stdio_server
    server=create_server(adapter)
    async with stdio_server() as (read,write): await server.run(read,write,server.create_initialization_options())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    for key in ['project','grant','run']: parser.add_argument('--'+key,required=True)
    parser.add_argument('--trusted-internal',action='store_true')
    args=parser.parse_args()
    service=FactoryService(args.workspace,read_only=not args.trusted_internal)
    asyncio.run(serve(ModuleTools(service,args.project,args.grant,args.run,args.trusted_internal)))
if __name__=='__main__': main()
