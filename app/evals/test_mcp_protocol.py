import hashlib
import json
import os
import sys
from pathlib import Path
import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
from cim.service import FactoryService


def test_actual_stdio_mcp_handshake_scope_search_and_pagination(tmp_path):
    s=FactoryService(tmp_path/"business")
    p=s.create_project("MCP stdio test",classification="internal")
    d=s.add_document(p["id"],1,"evidence.md","马达负载上报规范：单位待确认".encode(),classification="internal")
    root=Path(__file__).resolve().parents[1]
    params=StdioServerParameters(command=sys.executable,args=["-m","cim.mcp","--workspace",str(s.root),"--project",p["id"],"--trusted-internal"],
                                cwd=str(root),env={**os.environ,"PYTHONPATH":str(root/"src"),"PYTHONUTF8":"1"})
    async def exercise():
        with anyio.fail_after(25):
            with (tmp_path/"mcp-stderr.log").open("w",encoding="utf-8") as errors:
                async with stdio_client(params,errlog=errors) as streams:
                    async with ClientSession(*streams,read_timeout_seconds=10) as client:
                        result=await client.initialize()
                        assert result.server_info.name=="tft-lcd-factory"
                        names={t.name for t in (await client.list_tools()).tools}
                        assert "factory_submit_result" in names and not any("native" in name for name in names)
                        found=await client.call_tool("factory_search",{"query":"马达负载"})
                        assert not found.is_error
                        body=json.loads(found.content[0].text)
                        assert json.loads(body["json_chunk"])["citations"][0]["source_id"]==d["id"]
                        pieces=[];offset=0;checksum=None
                        while True:
                            page=await client.call_tool("factory_catalog",{"offset":offset})
                            assert not page.is_error
                            item=json.loads(page.content[0].text)
                            pieces.append(item["json_chunk"]);checksum=item["sha256"]
                            if item["complete"]: break
                            offset=item["next_offset"]
                        text="".join(pieces)
                        assert len(pieces)>1 and hashlib.sha256(text.encode()).hexdigest()==checksum
                        assert len(json.loads(text)["agents"])==34
                        invalid=await client.call_tool("archive",{})
                        assert invalid.is_error
    anyio.run(exercise)
