"""Synthetic member service + real HTTP boundary/assets for browser checks.

Standalone mode binds only 127.0.0.1:8763. No database, cloud calls, real identity,
photos or external requests. The SDK is synthetic and is served locally.
"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from ygc.cloud_account_page import install
from ygc.cloud_follow_routes import follow_router
from ygc.cloud_follows import FollowTargetMissing
from ygc.cloud_avatar import AvatarMissing, normalize_image
from io import BytesIO
from PIL import Image, ImageDraw
from ygc.db.postgres_operations import ServiceRestricted
from ygc.identity_platform import VerifiedIdentity
from browser_cloud_favorites_visibility import SDK_WITH_CONTROLS

STATIC = Path(__file__).resolve().parents[1] / 'src/ygc/static'

class FollowFixture:
    def __init__(self):
        self.people = {i: {'id': str(i), 'display_name': 'Member %02d' % i, 'icon': None} for i in range(1, 63)}
        self.people[1]['display_name'] = 'Alice'
        self.people[2]['display_name'] = 'Bob'
        self.people[3]['display_name'] = 'Other'
        self.people[4]['display_name'] = self.people[5]['display_name'] = 'Same name'
        self.people[6]['display_name'] = '<img src=x onerror=window.fixtureXss=true>'
        self.people[7]['display_name'] = 'Literal %_ name'
        self.follows = {(i,2) for i in range(10,40)}
        self.mode = 'normal'
        self.writes = []
        self.drop_after_write = False
        self.accounts = self
        self.visibility = {1:'Private',2:'Followers',3:'Members',4:'Public',5:'Private'}
        self.images = {}
        for key,color in [(1,'teal'),(2,'orange'),(3,'purple'),(4,'royalblue'),(5,'green')]:
            with Image.new('RGB',(64,64),color) as image:
                ImageDraw.Draw(image).rectangle((16,16,48,48),fill='white')
                buffer=BytesIO();image.save(buffer,format='PNG')
                self.images[key]=normalize_image(buffer.getvalue(),'image/png')

    def verify(self, *, bearer_token):
        if bearer_token.startswith('fixture-verified-'):
            return VerifiedIdentity('synthetic-follow', bearer_token[len('fixture-verified-'):], '', True)
        if bearer_token.startswith('fixture-'):
            return VerifiedIdentity('synthetic-follow', bearer_token[len('fixture-'):], '', False)
        raise PermissionError()

    def resolve_identity(self, *, issuer, subject, tenant):
        key = {'alice@example.invalid': 1, 'bob@example.invalid': 2, 'other@example.invalid': 3}.get(subject)
        if key is None: raise PermissionError()
        return {'id': str(key), 'app_user_id': 'synthetic-'+str(key), 'display_name': self.people[key]['display_name'], 'status':'active', 'role':'member', 'account_type':'user'}

    def gate(self, actor, write=False):
        if actor not in ('synthetic-1','synthetic-2','synthetic-3'): raise PermissionError()
        if self.mode in ('offline','admin_only') or write and self.mode=='read_only': raise ServiceRestricted()
        return int(actor.split('-')[-1])

    def member(self, target):
        if target not in self.people: raise FollowTargetMissing()
        return self.people[target]

    def page(self, ids, after, limit):
        page = sorted(i for i in ids if i>after)[:limit+1]
        more = len(page)>limit; page=page[:limit]
        return {'items':[self.people[i].copy() for i in page], 'total':str(len(ids)), 'next_after':str(page[-1]) if more else None}

    def search(self, actor, *, q='', after=0, limit=25):
        self.gate(actor)
        return self.page([i for i,p in self.people.items() if q.strip().lower() in p['display_name'].lower()],after,limit)

    def profile(self, actor, target):
        viewer=self.gate(actor)
        return {'person':self.member(target).copy(),'is_self':viewer==target,'following':(viewer,target) in self.follows,
                'followers_count':str(sum(b==target for a,b in self.follows)), 'following_count':str(sum(a==target for a,b in self.follows)), 'can_write':self.mode=='normal'}

    def connections(self, actor, target, *, direction, after=0, limit=25):
        self.gate(actor);self.member(target)
        ids=[a for a,b in self.follows if b==target] if direction=='followers' else [b for a,b in self.follows if a==target]
        return self.page(ids,after,limit)

    def avatar(self, actor, target):
        viewer=self.gate(actor);self.member(target)
        policy=self.visibility.get(target,'Private')
        if viewer!=target and policy not in ('Public','Members') and not (policy=='Followers' and (viewer,target) in self.follows):
            raise AvatarMissing()
        if target not in self.images: raise AvatarMissing()
        return self.images[target]

    def set_following(self, actor, target, following):
        viewer=self.gate(actor,True);self.member(target)
        if viewer==target: raise ValueError()
        self.writes.append((viewer,target,following))
        if following:self.follows.add((viewer,target))
        else:self.follows.discard((viewer,target))
        if self.drop_after_write:
            self.drop_after_write=False
            raise RuntimeError('Synthetic dropped response')
        return {'target_id':str(target),'following':following}

    def app(self, *, manual=False):
        app=FastAPI()
        app.include_router(follow_router(self,self))
        @app.get('/api/auth/me')
        def me(request: Request):
            try:
                identity=self.verify(bearer_token=request.headers.get('authorization','').removeprefix('Bearer '))
                user=self.resolve_identity(issuer=identity.issuer,subject=identity.subject,tenant=identity.tenant)
                return {'user':user,'identity':{'email_verified':identity.email_verified}}
            except PermissionError:return JSONResponse({'detail':'Synthetic identity required'},status_code=401)
        @app.get('/assets/cloud-auth-loader.js')
        def loader():
            return Response((STATIC/'cloud-auth-loader.js').read_text().replace('https://www.gstatic.com/firebasejs/','/firebasejs/'),media_type='text/javascript')
        @app.get('/firebasejs/{version}/{name}')
        def sdk(version:str,name:str):
            return Response('export const initializeApp=config=>config;' if name=='firebase-app.js' else SDK_WITH_CONTROLS,media_type='text/javascript')
        @app.get('/favicon.ico')
        def icon():return Response(status_code=204)
        if manual:
            @app.post('/fixture/avatar-policy')
            async def policy(request:Request):
                data=await request.json()
                if data.get('target') not in (1,2,3,4,5) or data.get('visibility') not in ('Public','Members','Followers','Private'):
                    return JSONResponse({},status_code=400)
                self.visibility[data['target']]=data['visibility']
                return {'saved':True}
        install(app,{'firebase':{'apiKey':'fixture','projectId':'fixture','authDomain':'fixture.firebaseapp.com'},'tenant':''})
        @app.middleware('http')
        async def local_only(request,call_next):
            response=await call_next(request)
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'"
            if manual and request.url.path.startswith('/members') and not request.url.path.startswith('/api/'):
                body=b''.join([part async for part in response.body_iterator]).decode()
                boot="<script>if(!sessionStorage.getItem('follow-fixture-ready')){sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true');sessionStorage.setItem('follow-fixture-ready','true')}</script>"
                controls="""<div style="padding:8px;background:#fff1c2">LOCAL TEST · Synthetic members · No live accounts / DB / cloud writes
<label>Test viewer <select id="fixtureViewer" onchange="sessionStorage.setItem('verified-'+this.value,'true');favoritesFixtureSwitchUser(this.value)"><option value="alice@example.invalid">Alice</option><option value="bob@example.invalid">Bob</option><option value="other@example.invalid">Other</option></select></label>
<label>Bob icon policy <select id="fixturePolicy"><option>Followers</option><option>Public</option><option>Members</option><option>Private</option></select></label>
<button type="button" id="fixtureApply" onclick="fetch('/fixture/avatar-policy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:2,visibility:document.getElementById('fixturePolicy').value})}).then(()=>{const c=new BroadcastChannel('ygc-member-avatar');c.postMessage('invalidate');c.close();document.getElementById('fixtureSaved').textContent='Synthetic policy saved'})">Apply synthetic policy</button><span id="fixtureSaved"></span></div>"""
                body=body.replace('<head>','<head>'+boot).replace('<body>','<body>'+controls)
                headers=dict(response.headers);headers.pop('content-length',None)
                return Response(body,headers=headers,media_type='text/html')
            return response
        return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(FollowFixture().app(manual=True),host='127.0.0.1',port=8763,log_level='warning')
