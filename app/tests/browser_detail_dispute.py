"""Selected-guitar private hint on real formal pages; synthetic loopback only."""
import os,socket,threading,json
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from formal_ui_fixture import FormalUIFixture
from browser_cloud_ownership_disputes import case_record,APPLICANT,OWNER,GUITAR

def main():
 fixture=FormalUIFixture();app=fixture.app(manual=True);record=case_record(submitted=())
 def remap(v):
  if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
  if isinstance(v,list):return [remap(x) for x in v]
  return {APPLICANT:'1',OWNER:'2',GUITAR:'1'}.get(v,v) if isinstance(v,str) else v
 record=remap(record);record['round']['parties'][1]['can_submit']=True;record['rounds']=[record['round']]
 row={k:v for k,v in record.items() if k not in ('viewer_user_id','can_write','is_admin','can_reopen','claims','round','rounds','evidence','events')}
 output=Path('docs/development/fidelity-evidence');output.mkdir(exist_ok=True)
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1]);server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.environ.get('YGC_BROWSER_EXECUTABLE'));context=browser.new_context(viewport={'width':1440,'height':1000});context.route('https://**/*',lambda r:r.abort());page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));active=True
    def respond(route):
     from urllib.parse import urlsplit,parse_qs
     path=urlsplit(route.request.url).path;query=parse_qs(urlsplit(route.request.url).query)
     if path.endswith('/options'):route.fulfill(json={'items':[],'next_after':None,'can_write':True,'viewer_user_id':'1'})
     elif path.endswith('/'+record['id']):route.fulfill(json=record)
     else:route.fulfill(json={'items':[row] if active and query.get('individual',['1'])[0]=='1' else [],'next_after':None,'can_write':True,'viewer_user_id':'1'})
    page.route('**/api/auth/ownership-disputes**',respond)
    page.goto(base+'/ui');page.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true')")
    for path,name in [('/ui/guitars/1','top'),('/ui/profile/guitars/1','profile')]:
     page.goto(base+path);hint=page.locator('#detailDisputeHint');expect(hint).to_have_text('Under dispute');page.locator('#addClaimLink').click();expect(page.locator('#addClaimMenu button').filter(has_text='Ownership')).to_be_disabled();expect(page.locator('#addClaimMenu [data-claim-type="event"]')).to_be_enabled();hint.click();expect(page.locator('#disputeDialog')).to_be_visible();expect(page.locator('#disputeMeta')).to_contain_text('Original Owner');page.locator('#disputeClose').click();expect(page.locator('#disputeDialog')).not_to_be_visible();page.screenshot(path=str(output/('resume-dispute-'+name+'-1440.png')))
     page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/('resume-dispute-'+name+'-390.png')));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.set_viewport_size({'width':1440,'height':1000})
    active=False;page.reload();expect(page.locator('#detailDisputeHint')).to_have_count(0);page.locator('#addClaimLink').click();expect(page.locator('#addClaimMenu button').filter(has_text='Ownership')).to_be_enabled()
    assert not errors,errors;assert not fixture.writes,fixture.writes;context.close();browser.close();print('PASS: Top/Profile private dispute hint, shared details, ownership disabled, ordinary claims enabled, settled state restored, PC/390px; no product writes.')
  finally:server.should_exit=True;thread.join(10);assert not thread.is_alive()
if __name__=='__main__':main()
