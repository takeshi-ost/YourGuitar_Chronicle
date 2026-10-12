"""Same-CSP, same-theme local/formal application geometry and labels; no upload."""
import subprocess,signal,json,os,sys
from playwright.sync_api import sync_playwright,expect
from pathlib import Path
root=str(Path(__file__).resolve().parents[2])
proc=subprocess.Popen([sys.executable,root+'/app/tests/manual_fidelity_fixture.py'],cwd=root,stdout=subprocess.PIPE,text=True)
try:
    bases={}
    for _ in range(2):
        name,port=proc.stdout.readline().strip().split();bases[name]='http://127.0.0.1:'+port
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        c=browser.new_context(viewport={'width':1440,'height':1000});c.route('https://**/*',lambda r:r.abort())
        local=c.new_page();formal=c.new_page()
        local.goto(bases['local']+'/user-view?prototype_user_id=1');local.evaluate('YGCPageReady')
        formal.goto(bases['formal']+'/ui/profile/guitars/1');formal.evaluate("sessionStorage.setItem('fixture-sdk-email','bob@example.invalid');sessionStorage.setItem('verified-bob@example.invalid','true')");formal.reload();expect(formal.locator('#selfProfileEdit')).to_be_enabled()
        local.goto(bases['local']+'/users/2?prototype_user_id=2');local.evaluate('YGCPageReady')
        formal.goto(bases['formal']+'/ui/profile/guitars/2');expect(formal.locator('#selfProfileEdit')).to_be_enabled()
        for width in (1440,390,320):
            formal.goto(bases['formal']+'/ui/profile/guitars/2');expect(formal.locator('#selfProfileEdit')).to_be_enabled()
            for page in (local,formal):page.set_viewport_size({'width':width,'height':844});page.evaluate("document.documentElement.dataset.theme='sunburst_3ply'")
            for kind in ('acquire','listing'):
                if kind=='listing' and width<=900:
                    for page in (local,formal):
                        if page.locator('#productDetailShell.compact-open').count():page.locator('.compact-detail-close').click()
                expect(local.locator('#profileHero')).to_be_visible()
                local.evaluate('openAcquireApplication(2)' if kind=='acquire' else 'openNewGuitar()')
                formal.locator('#acquireLink' if kind=='acquire' else '#applicationListing').click();expect(formal.locator('#applicationDialog.open')).to_be_visible()
                js="""e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,text:e.innerText}}"""
                a=local.locator('#acquireReviewModal .modal').evaluate(js);b=formal.locator('#applicationDialog .modal').evaluate(js)
                print(json.dumps({'width':width,'kind':kind,'local':a,'formal':b}),flush=True)
                assert all(abs(a[k]-b[k])<0.1 for k in ('x','y','width','height')), (width,kind,a,b)
                pairs=[('acquireDate','application_occurred_at'),('acquireBody','application_body'),('acquireCloseup','application_closeup'),('acquireOverview','application_overview')]
                if kind=='listing':pairs += [('guitarMaker','application_manufacturer'),('guitarSerial','application_serial_number')]
                for local_id,formal_id in pairs:
                    left=local.locator('#'+local_id).bounding_box();right=formal.locator('#'+formal_id).bounding_box()
                    assert all(abs(left[k]-right[k])<0.1 for k in ('x','y','width','height')), (width,kind,local_id,left,right)
                local.keyboard.press('Escape');formal.keyboard.press('Escape')
        browser.close()
finally:
    proc.send_signal(signal.SIGINT);proc.wait(timeout=20)
