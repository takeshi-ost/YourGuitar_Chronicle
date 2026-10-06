"""Dedicated-worker OIDC gate for diagnostics and optional review queues."""
import json
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from ygc.cloud_account_routes import bearer_token

TOOL='ygc_review_connection_check'


def review_gateway(verifier, service=None):
    router=APIRouter();headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    @router.post('/api/review/mcp')
    async def endpoint(request:Request):
        try:await run_in_threadpool(verifier.verify,bearer_token(request))
        except HTTPException:raise
        except PermissionError:raise HTTPException(401,'Review identity required.',headers=headers) from None
        except Exception:raise HTTPException(503,'Review identity unavailable.',headers=headers) from None
        if request.query_params or request.headers.get('content-encoding') or request.headers.get('content-type','').split(';')[0]!='application/json':raise HTTPException(400,'Invalid MCP request.',headers=headers)
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>100000:raise HTTPException(413,'MCP request too large.',headers=headers)
            chunks.append(chunk)
        try:message=json.loads(b''.join(chunks))
        except (ValueError,UnicodeError):raise HTTPException(400,'Invalid MCP JSON.',headers=headers) from None
        if (not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str) or set(message)-{'jsonrpc','id','method','params'}
            or not isinstance(message.get('params',{}),dict) or ('id' in message and type(message['id']) not in (str,int))):raise HTTPException(400,'Invalid MCP message.',headers=headers)
        method=message['method'];params=message.get('params',{})
        if 'id' not in message:
            if method!='notifications/initialized':raise HTTPException(400,'Unsupported notification.',headers=headers)
            return Response(status_code=202,headers=headers)
        def reply(**body):return JSONResponse(dict(jsonrpc='2.0',id=message['id'],**body),headers=headers)
        if method=='initialize':return reply(result=dict(protocolVersion='2025-03-26',capabilities={'tools':{}},serverInfo=dict(name='ygc-cloud-review',version='1')))
        if method=='ping':return reply(result={})
        if method=='tools/list':return reply(result={'tools':([] if service is None else service.tools())+[dict(name=TOOL,description='Check review connection only. Does not read images, claim applications or update data.',inputSchema=dict(type='object',properties={},additionalProperties=False))]})
        if method=='tools/call' and params.get('name')==TOOL and set(params)<={'name','arguments'} and params.get('arguments',{})=={}:
            return reply(result={'content':[dict(type='text',text=json.dumps(dict(status='ok',authentication='google_oidc',queues_connected=service is not None,data_changed=False)))]})
        if method=='tools/call' and service is not None and set(params)<={'name','arguments'} and isinstance(params.get('name'),str) and params.get('name') in {t['name'] for t in service.tools()}:
            try:
                result=await run_in_threadpool(service.call_tool,params['name'],params.get('arguments',{}))
                return reply(result=result if 'content' in result else {'content':[dict(type='text',text=json.dumps(result))]})
            except (ValueError,TypeError,PermissionError):
                return reply(error=dict(code=-32602,message='Review request rejected. Check state, lease and arguments.'))
            except Exception:
                return reply(error=dict(code=-32603,message='Review unavailable. Refresh state before retrying.'))
        return reply(error=dict(code=-32602 if method=='tools/call' else -32601,message='Unsupported tool or method.'))
    return router
