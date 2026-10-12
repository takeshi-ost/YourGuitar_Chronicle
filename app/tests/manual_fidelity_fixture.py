"""Manual Browser Use comparison; localhost, synthetic data and identical no-network CSP.

Run directly and stop with Ctrl-C; both servers and temporary DB are cleaned up.
No real identities, databases, uploads or remote resources are used.
Fonts fall back equally on both sides; this does not certify external font loading.
"""
import os,sys,tempfile,threading,socket
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'app/src'),str(root/'app/tests')]
for k in list(os.environ):
 if k.startswith('YGC_') or k in ('REVERB_API_TOKEN','K_SERVICE','CLOUD_RUN_JOB'):os.environ.pop(k)
store=tempfile.TemporaryDirectory(prefix='ygc-fidelity-local-')
os.environ.update(YGC_DATA_DIR=store.name,YGC_DB_PATH=store.name+'/chronicle.db',YGC_ACCOUNTS_DB_PATH=store.name+'/accounts.sqlite',YGC_LOG_DIR=store.name+'/logs',YGC_IDENTITY_BACKEND='local_dummy')
from formal_ui_fixture import FormalUIFixture
from ygc.web import app,repo
@app.middleware("http")
async def local_only(request,call_next):
 response=await call_next(request)
 response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'"
 return response
import uvicorn
fixture=FormalUIFixture();fixture.profile_all=True;repository=repo();repository.init_db();alice=repository.create_user('Alice');repository.create_user('Bob')
# No photo bytes or existing DB is read. All identifiers and descriptions are fictional.
for row in fixture.rows:
 repository.create_initial_listing_claim(alice,manufacturer=row['manufacturer'],model=row['model'],finish=row['finish'],year=row['year'],serial_number=row['serial_number'],media_storage_path='missing-fixture.png',occurred_at='2026-01-01',body='Synthetic listing')
servers=[];threads=[]
for name,application in [('local',app),('formal',fixture.app(manual=True))]:
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 server=uvicorn.Server(uvicorn.Config(application,log_level='error',lifespan='off'))
 thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start();servers.append(server);threads.append(thread)
 print(name,port,flush=True)
try:
 threading.Event().wait()
except KeyboardInterrupt:
 pass
finally:
 for server in servers:server.should_exit=True
 for thread in threads:thread.join(5)
 store.cleanup()
