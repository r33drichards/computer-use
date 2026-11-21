import hashlib,json

import httpx

from checkpoint_gateway import create_app

async def run(actor, no_runtime):
    token="a"*64
    app=create_app("app-bearer", hashlib.sha256(token.encode()).hexdigest(), open_runtime=no_runtime,
                   exchange=actor.stream.remote_gen.aio)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://private-check.invalid") as client:
        basic={"authorization":"Bearer "+token,"accept":"application/json, text/event-stream"}
        assert (await client.post("/mcp")).status_code==401
        assert (await client.post("/exec",headers=basic)).status_code==404
        assert (await client.get("/mcp",headers=basic)).status_code==405
        assert not await actor.idle_checkpoint.remote.aio()
        async def call(h,i,method,params=None):
            obj={"jsonrpc":"2.0","method":method}
            if i is not None:obj["id"]=i
            if params is not None:obj["params"]=params
            r=await client.post("/mcp",headers=h,json=obj)
            assert r.status_code==(200 if i is not None else 202), (r.status_code,r.text[:150])
            if i is None:return r,{}
            if r.headers.get("content-type","").startswith("text/event-stream"):
                for l in r.text.splitlines():
                    if l.startswith("data: ") and l[6:].strip():
                        value=json.loads(l[6:])
                        if value.get("id")==i:return r,value
                raise RuntimeError("missing response frame")
            return r,r.json()
        async def exercise():
            r,initialized=await call(basic,1,"initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"disk-check","version":"1"}})
            assert "result" in initialized
            h={**basic,"mcp-session-id":r.headers["mcp-session-id"],"mcp-protocol-version":"2025-03-26"}
            await call(h,None,"notifications/initialized")
            _,tools=await call(h,2,"tools/list",{})
            assert "run_js" in {v["name"] for v in tools["result"]["tools"]}
            js="const p=r=>JSON.parse(r.content.find(x=>x.type==='text').text);const j=p(await mcp.callTool('exec','exec',{bin:'id',args:['-u'],timeout:4}));for(let i=0;i<30;i++){const s=p(await mcp.callTool('exec','stream_logs',{id:j.id,offset:0}));if(s.status==='completed:0'){console.log('UID-PROOF-'+s.logs.trim());break;}await new Promise(r=>setTimeout(r,100));}"
            _,out=await call(h,3,"tools/call",{"name":"run_js","arguments":{"code":js,"execution_timeout_secs":15}})
            assert "UID-PROOF-1000" in json.dumps(out)
            return h["mcp-session-id"]
        a=await exercise()
        assert await actor.idle_checkpoint.remote.aio()
        b=await exercise()
        assert a!=b
        assert await actor.idle_checkpoint.remote.aio()
    print("PASS: authenticated gateway exercised real exec before and after idle checkpoint, and denied anonymous MCP/direct exec.")
