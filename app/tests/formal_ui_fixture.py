"""Loopback-only formal UI fixture: synthetic SDK, people, guitars and state.

No database, cloud authentication, external photo or cloud mutations.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from collections import Counter
from datetime import datetime, timedelta, timezone
from follow_browser_fixture import FollowFixture

class FormalUIFixture(FollowFixture):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.favorites = set()
        self.rows = [{'id':str(i),'claim_count':'1','manufacturer':'Fender' if i%2 else 'Gibson',
                      'model':('Stratocaster' if i%2 else 'ES-335')+' · Fixture '+str(i),
                      'finish':'Sunburst' if i%2 else 'Cherry','year':str(1958+i%8),
                      'serial_number':'DEMO-'+str(i).zfill(4),'photo':None} for i in range(1,31)]
        self.reject_identity = False
        self.profile_all = False
        self.notices = []
        self.owner_rows = []
        self.own_claims = {}
        self.detail_actions = False
        self.insights_case = 'normal'
        self.prepublication = False
        self.votes = {}
        self.profile_cursor_gate = None

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
            if self.profile_cursor_gate is not None and request.url.path=='/api/auth/guitars' and request.query_params.get('after'):
                import asyncio
                await asyncio.to_thread(self.profile_cursor_gate.wait,15)
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
        @app.get('/api/public/guitars/discoveries')
        def discoveries(request:Request):
            denied=restricted(request)
            if denied:return denied
            return {'items':[] if self.insights_case=='empty' else [{**row,
                'activity_at':'2026-10-12T00:00:00+00:00','activity_type':'claim','claim_type':'listing'} for row in reversed(self.rows)]}
        @app.get('/api/public/guitars/statistics')
        def statistics(request:Request):
            denied=restricted(request)
            if denied:return denied
            if self.insights_case=='statistics_error':return JSONResponse({},status_code=503)
            rows=[] if self.insights_case=='empty' else self.rows
            models=Counter(row['model'].split(' · ')[0] for row in rows)
            years=Counter(row['year'] for row in rows)
            today=datetime.now(timezone.utc).date()
            return {'individuals':str(len(rows)),
                'models':[{'label':label,'count':str(models[label])} for label in sorted(models)],
                'years':[{'label':label,'count':str(years[label])} for label in sorted(years)],
                'listings_30d':[{'date':(today-timedelta(days=29-i)).isoformat(),'count':str(i%5 if rows else 0)} for i in range(30)]}
        @app.get('/api/public/guitars/world-map')
        def world_map(request:Request):
            denied=restricted(request)
            if denied:return denied
            return {'countries':[] if self.insights_case=='empty' else [{'country':'Japan','count':'17'},{'country':'USA','count':'11'},{'country':'Singapore','count':'2'}]}
        @app.get('/api/public/guitars')
        def guitars(request:Request,q:str='',sort:str='newest',page:int=1,limit:int=24):
            denied=restricted(request)
            if denied:return denied
            rows=[r for r in self.rows if q.lower() in ' '.join(str(r[k]) for k in ('manufacturer','model','finish','year','serial_number')).lower()]
            rows=sorted(rows,key=lambda r:r['manufacturer' if sort=='maker' else 'model'] if sort in ('maker','model') else int(r['id']),reverse=sort=='newest')
            if sort.rsplit('_',1)[-1] in ('asc','desc') and sort.rsplit('_',1)[0] in ('manufacturer','model','finish','year','serial_number'):
                rows=sorted(rows,key=lambda r:(r[sort.rsplit('_',1)[0]] or '').lower(),reverse=sort.endswith('_desc'))
            return {'items':rows[(page-1)*limit:page*limit],'total':str(len(rows)),'page':page,'page_size':limit,'total_pages':(len(rows)+limit-1)//limit}
        @app.get('/api/public/guitars/{individual}')
        def detail(individual:str,request:Request):
            denied=restricted(request)
            if denied:return denied
            row=next((r for r in self.rows if r['id']==individual),None)
            if row is None:return JSONResponse({},status_code=404)
            return {**row,**({'public_photo':'/api/public/guitars/'+individual+'/photo'} if self.prepublication and individual=='1' else {}),**({'presentation':{'owner':{'id':'1','display_name':'Alice'},'location':None,'source_owner_name':None}} if manual else {}),'specifications':[{'field_name':'body','value_text':'Alder'},{'field_name':'pickups','value_text':'Original fixture pickups'}]}
        @app.get('/api/public/guitars/{individual}/photo')
        def photo(individual:str):
            return Response(self.images[1],media_type='image/jpeg')
        @app.get('/api/public/guitars/{individual}/chronicle')
        def chronicle(individual:str,request:Request):
            denied=restricted(request)
            if denied:return denied
            items=[{'id':'101','claim_type':'listing','ownership_kind':None,'occurred_at':'2026-01-01','created_at':'2026-01-01T12:00:00Z','verification_status':'positive','items':[{'field_name':'model','value_text':'Synthetic listing'}],'source_url':None}]
            if self.detail_actions:
                for claim in [*self.owner_rows,*[r for (key,guitar),rows in own_claims.items() if guitar==individual for r in rows]]:
                    items.append({**{k:claim[k] for k in ('id','claim_type','occurred_at','created_at','verification_status')},'ownership_kind':claim.get('ownership_kind'),'items':claim.get('spec_items',[]) if claim['verification_status']=='positive' else [],'source_url':None})
            return {'items':items,'next_after':None}
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
                return HTMLResponse('<h1>Synthetic local QA only</h1><form method="post" action="/fixture/mode"><label>Service mode<select name="mode"><option>normal</option><option>read_only</option><option>offline</option></select></label><button>Apply synthetic mode</button></form><form method="post" action="/fixture/insights"><label>Insights data<select name="case"><option>normal</option><option>empty</option><option>statistics_error</option></select></label><button>Apply synthetic insights</button></form><a href="/ui">Formal Top</a><a href="/ui/profile">Formal profile</a>')
            @app.post('/fixture/insights')
            async def set_insights(request:Request):
                from urllib.parse import parse_qs
                from fastapi.responses import RedirectResponse
                case=parse_qs((await request.body()).decode()).get('case',['normal'])[0]
                if case not in ('normal','empty','statistics_error'):return JSONResponse({},status_code=400)
                self.insights_case=case
                return RedirectResponse('/ui',status_code=303)
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
        @app.get('/api/auth/profile/bootstrap')
        def bootstrap(request:Request):
            key=actor(request)
            def inventory(kind):
                rows=self.rows if self.profile_all and kind=='owned' and key==1 else [] if self.profile_all else [self.rows[key-1 if kind=='owned' else key+1]]
                page=[{k:v for k,v in row.items() if k!='photo'} for row in rows[:25]]
                return {'items':page,'total':str(len(rows)),'next_after':page[-1]['id'] if len(rows)>25 else None}
            rows=[{k:v for k,v in row.items() if k!='claim_count'} for row in reversed(self.rows) if ('synthetic-'+str(key),row['id']) in self.favorites]
            p=profiles.setdefault(key,{'profile_revision':'1','fields':{'display_name':self.people[key]['display_name'],'location_country':'','location_region':'','bio':'Synthetic profile'}})
            fields=settings_values.setdefault(key,{**p['fields'],'account_type':'user','date_of_birth':'','theme':'sunburst_3ply',**dict.fromkeys(('birth_visibility','residence_visibility','bio_visibility','avatar_visibility'),'Private')})
            profile={'id':str(key),'profile_revision':p['profile_revision'],'fields':fields}
            return {'settings':profile,'summary':{'owned_count':inventory('owned')['total'],'former_count':inventory('formerly_owned')['total'],'claim_count':'30' if key==1 else '0'},'signature':{'individual_id':signatures.get(key)},'owned':inventory('owned'),'formerly_owned':inventory('formerly_owned'),'favorites':{'items':rows,'total':str(len(rows)),'next_after':None}}
        @app.get('/api/auth/profile/chronicle')
        def profile_chronicle(request:Request):
            actor(request);return {'items':[]}
        @app.get('/api/auth/profile/summary')
        def profile_summary(request:Request):
            key=actor(request);return {'owned_count':('30' if key==1 else '0') if self.profile_all else '1','former_count':'0' if self.profile_all else '1','claim_count':'30' if key==1 else '0'}
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
        settings_values={};signatures={}
        @app.api_route('/api/auth/settings',methods=['GET','PUT'])
        async def settings(request:Request):
            key=actor(request,request.method=='PUT')
            profile=profiles.setdefault(key,{'profile_revision':'1','fields':{'display_name':self.people[key]['display_name'],'location_country':'','location_region':'','bio':'Synthetic profile'}})
            fields=settings_values.setdefault(key,{**profile['fields'],'account_type':'user','date_of_birth':'','theme':'sunburst_3ply',**dict.fromkeys(('birth_visibility','residence_visibility','bio_visibility','avatar_visibility'),'Private')})
            if request.method=='PUT':
                from ygc.cloud_profile import validate_settings
                data=await request.json();validate_settings(data)
                if data['revision']!=profile['profile_revision']:return JSONResponse({},status_code=409)
                settings_values[key]=data['fields'];profile['fields']={field:data['fields'][field] for field in profile['fields']};profile['profile_revision']=str(int(profile['profile_revision'])+1);self.people[key]['display_name']=profile['fields']['display_name'];self.writes.append(('settings',key))
                return {'saved':True,'profile_revision':profile['profile_revision']}
            return {'id':str(key),'profile_revision':profile['profile_revision'],'fields':fields}
        @app.api_route('/api/auth/settings/signature',methods=['GET','PUT'])
        async def signature(request:Request):
            key=actor(request,request.method=='PUT')
            if request.method=='PUT':
                data=await request.json()
                if data['previous']!=signatures.get(key):return JSONResponse({},status_code=409)
                signatures[key]=data['individual_id'];self.writes.append(('signature',key))
            return {'individual_id':signatures.get(key)}
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
        def own(request:Request,kind:str='owned',after:int=0,limit:int=25):
            key=actor(request)
            rows=self.rows if self.profile_all and kind=='owned' and key==1 else [] if self.profile_all else [self.rows[key-1 if kind=='owned' else key+1]]
            remaining=[dict(row) for row in rows if int(row['id'])>after]
            for row in remaining:row.pop('photo')
            page=remaining[:limit]
            return {'items':page,'total':str(len(rows)),'next_after':page[-1]['id'] if len(remaining)>limit else None}
        @app.get('/api/auth/favorites')
        def favorites(request:Request,after:int=0,limit:int=25):
            key=actor(request);rows=[r for r in reversed(self.rows) if ('synthetic-'+str(key),r['id']) in self.favorites]
            remaining=[{k:v for k,v in row.items() if k!='claim_count'} for row in rows if not after or int(row['id'])<after];page=remaining[:limit]
            return {'items':page,'total':str(len(rows)),'next_after':page[-1]['id'] if len(remaining)>limit else None}
        @app.api_route('/api/auth/avatar',methods=['GET','PUT','DELETE'])
        async def avatar(request:Request):
            key=actor(request,request.method!='GET')
            if request.method=='PUT':self.images[key]=await request.body();self.writes.append(('avatar',key))
            if request.method=='DELETE':self.images.pop(key,None);return {}
            if key not in self.images:return Response(status_code=404)
            return Response(self.images[key],media_type='image/jpeg')
        @app.get('/api/auth/notifications')
        def notifications(request:Request):
            actor(request);return {'items':self.notices,'next_after':None,'unread_count':str(sum(not row['is_read'] for row in self.notices)),'can_write':self.mode=='normal'}
        @app.post('/api/auth/notifications/{notice}/read')
        def read_notice(request:Request,notice:str):
            actor(request,True);row=next(row for row in self.notices if row['id']==notice);row.update(is_read=True,read_at='2026-10-08T12:00:00Z');self.writes.append(('notification_read',notice))
            return {key:row[key] for key in ('id','is_read','read_at')}|{'unread_count':str(sum(not item['is_read'] for item in self.notices))}
        @app.get('/api/auth/ownership-disputes')
        @app.get('/api/auth/ownership-disputes/options')
        def empty(request:Request):
            key=actor(request);return {'items':[],'next_after':None,'viewer_user_id':str(key),'can_write':self.mode=='normal'}
        @app.get('/api/auth/identity-corrections')
        def listing_actions(request:Request):
            key=actor(request)
            return {'items':[{'id':'101','individual':{k:self.rows[0][k] for k in ('id','manufacturer','model','year','serial_number')},'occurred_at':'2026-01-01'}] if self.prepublication and key==1 else [],'next_after':None,'can_write':self.mode=='normal'}
        @app.get('/api/auth/identity-corrections/{listing}')
        def listing_detail(listing:str,request:Request):
            key=actor(request)
            if not self.prepublication or key!=1 or listing!='101':return JSONResponse({},status_code=404)
            return {'listing':{'id':'101','individual_id':'1','occurred_at':'2026-01-01'},'individual':{k:self.rows[0][k] for k in ('id','manufacturer','model','year','serial_number')},'revision':'a'*64,'can_write':self.mode=='normal','items':[],'next_after':None}
        def vote_page(key,claim='101'):
            own=self.votes.get((key,claim))
            return {'can_write':self.mode=='normal','items':[{'id':claim,'vote':own,'good_count':str(sum(v=='good' for (a,c),v in self.votes.items() if c==claim)),'bad_count':str(sum(v=='bad' for (a,c),v in self.votes.items() if c==claim))}]}
        @app.get('/api/auth/guitars/{individual}/votes')
        def votes(individual:str,request:Request):
            key=actor(request)
            return vote_page(key) if self.prepublication else {'can_write':self.mode=='normal','items':[]}
        @app.put('/api/auth/guitars/{individual}/claims/{claim}/vote')
        async def cast_vote(individual:str,claim:str,request:Request):
            key=actor(request,True);data=await request.json();assert data['vote'] in ('good','bad',None)
            if data['vote'] is None:self.votes.pop((key,claim),None)
            else:self.votes[(key,claim)]=data['vote']
            self.writes.append(('vote',key,claim,data['vote']))
            return vote_page(key,claim)
        released=set();transfers={}
        def ownership_value(key,individual):
            row=next(r for r in self.rows if r['id']==individual);owner=None if individual in released else '1'
            return dict(viewer_user_id=str(key),individual={k:row[k] for k in ('id','manufacturer','model','finish','year','serial_number')},current_owner_user_id=owner,is_current_owner=owner==str(key),can_write=self.mode=='normal',can_release=owner==str(key),can_transfer=owner==str(key),revision='a'*64,items=[],next_after=None)
        @app.get('/api/auth/guitars/{individual}/ownership')
        def ownership_view(request:Request,individual:str):return ownership_value(actor(request),individual)
        @app.get('/api/auth/guitars/{individual}/transfer-users')
        def transfer_people(request:Request,individual:str,q:str='',offset:int=0,limit:int=20):
            actor(request);return {'items':[dict(id='2',display_name='Bob',account_type='user')] if q.lower()=='bob' else [],'next_offset':None}
        def participant_transfer(row,key):
            return {**row,'viewer_user_id':str(key),'can_accept':row['state']=='pending' and row['to_user']['id']==str(key),'can_decline':row['state']=='pending' and row['to_user']['id']==str(key),'can_cancel':row['state']=='pending' and row['from_user']['id']==str(key)}
        @app.get('/api/auth/ownership-transfers')
        def transfer_inbox(request:Request):
            key=actor(request);return dict(items=[participant_transfer(row,key) for row in transfers.values()],next_after=None,viewer_user_id=str(key),can_write=self.mode=='normal')
        @app.post('/api/auth/guitars/{individual}/transfers')
        async def transfer_start(request:Request,individual:str):
            key=actor(request,True);data=await request.json();row=dict(id='501',viewer_user_id=str(key),individual_id=individual,individual=ownership_value(key,individual)['individual'],ownership_kind='transfer',from_user=dict(id=str(key),display_name='Alice',account_type='user'),to_user=dict(id=data['to_user_id'],display_name='Bob',account_type='user'),state='pending',status='active',verification_status='unverified',created_at='2026-10-08T12:00:00Z',resolved_at=None,occurred_at=None,acceptance=None,can_write=True,can_accept=False,can_decline=False,can_cancel=True,revision='b'*64)
            transfers['501']=row;self.writes.append(('transfer',individual));return {'transfer':row}
        @app.get('/api/auth/transfers/{claim}')
        def transfer_read(request:Request,claim:str):return participant_transfer(transfers[claim],actor(request))
        @app.post('/api/auth/transfers/{claim}/resolve')
        async def transfer_resolve(request:Request,claim:str):
            key=actor(request,True);data=await request.json();row=transfers[claim];row.update(state={'cancel':'cancelled','decline':'declined'}[data['action']],resolved_at='2026-10-08T12:01:00Z',can_cancel=False,revision='c'*64);self.writes.append(('transfer_'+data['action'],claim));return {'transfer':participant_transfer(row,key)}
        @app.post('/api/auth/guitars/{individual}/release')
        async def release_guitar(request:Request,individual:str):
            key=actor(request,True);data=await request.json();released.add(individual);self.writes.append(('release',individual,data))
            return {'claim':dict(id='500',individual_id=individual,ownership_kind='release',status='active',verification_status='positive',occurred_at=data['occurred_at'] or '2026-10-08',body=data['body']), 'ownership':ownership_value(key,individual)}
        drafts={};requests={}
        @app.get('/api/auth/applications')
        def application_list(request:Request):
            key=actor(request);return {'items':list(requests.get(key,{}).values()),'can_write':self.mode=='normal'}
        @app.post('/api/auth/applications/preview')
        async def application_preview(request:Request):
            import time
            key=actor(request,True);data=await request.json();token=str(len(drafts)+1).zfill(64);kind=data['kind'];payload=data.get('payload')
            row=dict(kind=kind,payload=payload,individual_id=data.get('individual_id'),revision=token[-32:],draft_token=token,unsaved=True,
                status='draft',serial=payload['serial_number'] if payload else 'DEMO-0002',challenge='SYNTH123',expires_at=time.time()+86400,
                acquisition_date=payload['occurred_at'] if payload else None,body=payload['body'] if payload else '',photos=[],claim_id=None,verification_status=None,reasons=[],admin_review=None)
            drafts[(key,token)]=row;return row
        @app.post('/api/auth/applications/keep')
        async def application_keep(request:Request):
            key=actor(request,True);data=await request.json();row=dict(drafts[(key,data['draft_token'])] if 'draft_token' in data else requests[key][data['revision']])
            row.pop('draft_token',None);row.pop('unsaved',None)
            row.update(acquisition_date=data['acquisition_date'],body=data['body']);requests.setdefault(key,{})[row['revision']]=row
            self.writes.append(('application_keep',row['revision']));return row
        @app.post('/api/auth/applications/{revision}/cancel')
        def application_cancel(request:Request,revision:str):
            key=actor(request,True);row=requests[key][revision];row['status']='cancelled';self.writes.append(('application_cancel',revision));return row
        @app.get('/api/auth/owner-acquire-requests')
        def owner_inbox(request:Request):
            key=actor(request)
            return {'items':[dict(id=r['id'],individual_id=r['individual_id'],author_name=r['author_name'],
                product_name='Fender Stratocaster · Fixture 1',can_write=self.mode=='normal')
                for r in self.owner_rows if key==1 and r.get('ownership_kind')=='acquire'
                and r['verification_status']=='unverified'],'next_after':None}
        @app.get('/api/auth/guitars/{individual}/owner-responses')
        def owner_responses(request:Request,individual:str):
            key=actor(request)
            if key!=1:return JSONResponse({},status_code=403)
            return {'items':self.owner_rows if individual=='1' else [],'can_write':self.mode=='normal'}
        @app.post('/api/auth/guitars/{individual}/owner-responses/{claim_id}')
        async def respond(request:Request,individual:str,claim_id:str):
            key=actor(request,True)
            if key!=1:return JSONResponse({},status_code=403)
            data=await request.json();row=next(r for r in self.owner_rows if r['id']==claim_id)
            if data['revision']!=row['revision']:return JSONResponse({},status_code=409)
            row.update(verification_status=data['stance'],revision='b'*64);self.writes.append(('owner_response',claim_id,data));return {'saved':True}
        own_claims=self.own_claims
        @app.api_route('/api/auth/guitars/{individual}/claims',methods=['GET','POST'])
        async def claims(request:Request,individual:str):
            key=actor(request,request.method=='POST');rows=own_claims.setdefault((key,individual),[])
            if request.method=='POST':
                data=await request.json();identifier=str(1001+sum(len(v) for v in own_claims.values()))
                row=dict(id=identifier,individual_id=individual,claim_type=data['claim_type'],
                    specification_kind=data.get('specification_kind'),incident_kind=data.get('incident_kind'),event_kind=data.get('event_kind'),
                    status='active',verification_status='unverified',revision='a'*64,body=data.get('body'),occurred_at=data.get('occurred_at'),
                    spec_items=data.get('items',[]),media_items=[],created_at='2026-10-08',updated_at='2026-10-08')
                rows.insert(0,row);self.writes.append(('claim_create',identifier));return {'claim':row}
            return {'individual':next(r for r in self.rows if r['id']==individual),'items':rows,'next_after':None,'can_write':self.mode=='normal'}
        @app.patch('/api/auth/guitars/{individual}/claims/{claim_id}')
        async def edit_claim(request:Request,individual:str,claim_id:str):
            key=actor(request,True);data=await request.json();row=next(r for r in own_claims[(key,individual)] if r['id']==claim_id)
            if data['revision']!=row['revision']:return JSONResponse({},status_code=409)
            row.update(body=data.get('body'),occurred_at=data.get('occurred_at'),revision='b'*64)
            if row['claim_type']=='specification':row.update(spec_items=data['items'],specification_kind=data['specification_kind'])
            self.writes.append(('claim_edit',claim_id));return {'claim':row}
        return app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(FormalUIFixture().app(manual=True),host='127.0.0.1',port=8764,log_level='error')
