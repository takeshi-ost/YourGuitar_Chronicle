"""Loopback-only formal UI fixture: synthetic SDK, people, guitars and state.

No database, cloud authentication, external photo or cloud mutations.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from follow_browser_fixture import FollowFixture

class FormalUIFixture(FollowFixture):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.favorites = set()
        self.rows = [{'id':str(i),'manufacturer':'Fender' if i%2 else 'Gibson',
                      'model':('Stratocaster' if i%2 else 'ES-335')+' · Fixture '+str(i),
                      'finish':'Sunburst' if i%2 else 'Cherry','year':str(1958+i%8),
                      'serial_number':'DEMO-'+str(i).zfill(4),'photo':None} for i in range(1,31)]
        self.reject_identity = False

    def app(self, *, manual=False):
        app=super().app(manual=False)
        @app.middleware('http')
        async def record(request,call_next):
            self.calls.append((request.method,request.url.path))
            if self.reject_identity and (request.url.path=='/api/auth/me' or request.url.path.startswith('/api/public/')):
                return JSONResponse({'detail':'Synthetic revoked identity'},status_code=401)
            if request.url.path.startswith('/api/auth/') and request.url.path not in ('/api/auth/config','/api/auth/me','/api/auth/registration'):
                if self.mode in ('offline','admin_only') or request.method not in ('GET','HEAD') and self.mode=='read_only':
                    return JSONResponse({'detail':{'code':'service_restricted'}},status_code=403)
            response=await call_next(request)
            if manual and request.url.path.endswith('/firebase-auth.js'):
                from fastapi.responses import Response
                body=b''.join([part async for part in response.body_iterator]).decode()
                body=body.replace("sessionStorage.getItem('verified-'+email)==='true'", "true")
                return Response(body,media_type='text/javascript')
            return response
        @app.get('/api/service/status')
        def mode():return {'mode':self.mode,'message':''}
        def restricted(request):
            if self.mode=='offline' or self.mode=='admin_only':return JSONResponse({'detail':{'code':'service_restricted'}},status_code=403)
        @app.get('/api/public/guitars')
        def guitars(request:Request,q:str='',sort:str='newest',page:int=1,limit:int=24):
            denied=restricted(request)
            if denied:return denied
            rows=[r for r in self.rows if q.lower() in ' '.join(str(r[k]) for k in ('manufacturer','model','serial_number')).lower()]
            rows=sorted(rows,key=lambda r:r['manufacturer' if sort=='maker' else 'model'] if sort in ('maker','model') else int(r['id']),reverse=sort=='newest')
            return {'items':rows[(page-1)*limit:page*limit],'total':str(len(rows)),'page':page,'page_size':limit,'total_pages':(len(rows)+limit-1)//limit}
        @app.get('/api/public/guitars/{individual}')
        def detail(individual:str,request:Request):
            denied=restricted(request)
            if denied:return denied
            row=next((r for r in self.rows if r['id']==individual),None)
            if row is None:return JSONResponse({},status_code=404)
            return {**row,'specifications':[{'field_name':'body','value_text':'Alder'},{'field_name':'pickups','value_text':'Original fixture pickups'}]}
        @app.get('/api/public/guitars/{individual}/chronicle')
        def chronicle(individual:str,request:Request):
            denied=restricted(request)
            if denied:return denied
            return {'items':[{'id':'101','claim_type':'listing','ownership_kind':None,'occurred_at':'2026-01-01','created_at':'2026-01-01T12:00:00Z','verification_status':'positive','items':[{'field_name':'model','value_text':'Synthetic listing'}],'source_url':None}], 'next_after':None}
        @app.api_route('/api/auth/favorites/{individual}',methods=['GET','PUT'])
        async def favorite(individual:str,request:Request):
            try:
                identity=self.verify(bearer_token=request.headers.get('authorization','').removeprefix('Bearer '))
                actor=self.resolve_identity(issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)['app_user_id']
                self.gate(actor,request.method=='PUT')
            except Exception:return JSONResponse({},status_code=403)
            pair=(actor,individual)
            if request.method=='PUT':
                data=await request.json()
                if data['favorite']:self.favorites.add(pair)
                else:self.favorites.discard(pair)
            return {'individual_id':individual,'favorite':pair in self.favorites}
        from ygc.cloud_registration import DOCUMENTS
        from fastapi.responses import Response
        if manual:
            @app.get('/fixture')
            def controls():
                from fastapi.responses import HTMLResponse
                return HTMLResponse('<h1>Synthetic local QA only</h1><form method="post" action="/fixture/mode"><select name="mode"><option>normal</option><option>read_only</option><option>offline</option></select><button>Apply synthetic mode</button></form><a href="/ui/profile">Formal profile</a>')
            @app.post('/fixture/mode')
            async def set_mode(request:Request):
                from urllib.parse import parse_qs
                from fastapi.responses import RedirectResponse
                mode=parse_qs((await request.body()).decode()).get('mode',['normal'])[0]
                if mode not in ('normal','read_only','offline'):return JSONResponse({},status_code=400)
                self.mode=mode
                return RedirectResponse('/ui/profile',status_code=303)
        profiles={}
        visibility={}
        def actor(request,write=False):
            identity=self.verify(bearer_token=request.headers.get('authorization','').removeprefix('Bearer '))
            key=self.resolve_identity(issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)['app_user_id']
            return self.gate(key,write)
        @app.get('/api/auth/registration')
        def documents():return {'backend':'identity_platform','documents':DOCUMENTS}
        @app.api_route('/api/auth/profile',methods=['GET','PUT'])
        async def profile(request:Request):
            key=actor(request,request.method=='PUT')
            value=profiles.setdefault(key,{'profile_revision':'1','fields':{'display_name':self.people[key]['display_name'],'location_country':'','location_region':'','bio':'Synthetic profile'}})
            if request.method=='PUT':
                data=await request.json()
                if data['revision']!=value['profile_revision']:return JSONResponse({},status_code=409)
                value['fields']=data['fields'];value['profile_revision']=str(int(value['profile_revision'])+1)
                self.people[key]['display_name']=value['fields']['display_name']
                self.writes.append(('profile',key))
            return value
        @app.api_route('/api/auth/profile/visibility',methods=['GET','PUT'])
        async def prefs(request:Request):
            key=actor(request,request.method=='PUT')
            value=visibility.setdefault(key,{'profile_revision':'1','fields':dict.fromkeys(('birth_visibility','residence_visibility','bio_visibility','avatar_visibility'),'Private')})
            if request.method=='PUT':
                data=await request.json()
                if data['revision']!=value['profile_revision']:return JSONResponse({},status_code=409)
                value={'profile_revision':str(int(value['profile_revision'])+1),'fields':data['fields']};visibility[key]=value
                self.visibility[key]=value['fields']['avatar_visibility'];self.writes.append(('visibility',key))
            return value
        @app.get('/api/auth/guitars')
        def own(request:Request,kind:str='owned'):
            key=actor(request);row=dict(self.rows[key-1 if kind=='owned' else key+1]);row.pop('photo')
            return {'items':[row],'total':'1','next_after':None}
        @app.get('/api/auth/favorites')
        def favorites(request:Request):
            key=actor(request);rows=[r for r in reversed(self.rows) if ('synthetic-'+str(key),r['id']) in self.favorites]
            return {'items':rows,'total':str(len(rows)),'next_after':None}
        @app.api_route('/api/auth/avatar',methods=['GET','PUT','DELETE'])
        async def avatar(request:Request):
            key=actor(request,request.method!='GET')
            if request.method=='PUT':self.images[key]=await request.body();self.writes.append(('avatar',key))
            if request.method=='DELETE':self.images.pop(key,None);return {}
            if key not in self.images:return Response(status_code=404)
            return Response(self.images[key],media_type='image/jpeg')
        @app.get('/api/auth/notifications')
        def notifications(request:Request):
            actor(request);return {'items':[],'next_after':None,'unread_count':'0','can_write':self.mode=='normal'}
        @app.get('/api/auth/ownership-disputes')
        @app.get('/api/auth/ownership-disputes/options')
        @app.get('/api/auth/ownership-transfers')
        @app.get('/api/auth/identity-corrections')
        @app.get('/api/auth/applications')
        def empty(request:Request):
            key=actor(request);return {'items':[],'next_after':None,'viewer_user_id':str(key),'can_write':self.mode=='normal'}
        @app.get('/api/auth/guitars/{individual}/claims')
        def claims(request:Request,individual:str):
            actor(request);return {'individual':next(r for r in self.rows if r['id']==individual),'items':[],'next_after':None,'can_write':self.mode=='normal'}
        return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(FormalUIFixture().app(manual=True),host='127.0.0.1',port=8764,log_level='error')
