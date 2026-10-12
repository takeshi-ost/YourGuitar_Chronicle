"""Same-CSP, same-theme local/formal empty Follow connections geometry and labels; no upload."""
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
        local.goto(bases['local']+'/users/2?prototype_user_id=1');local.evaluate('YGCPageReady')
        formal.goto(bases['formal']+'/ui/members/2');formal.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true')");formal.reload();expect(formal.locator('#memberFollowing')).to_be_visible()
        for width in (1440,390,320):
            for page in (local,formal):page.set_viewport_size({'width':width,'height':844});page.evaluate("document.documentElement.dataset.theme='sunburst_3ply'")
            local.evaluate("openUserConnections('following')");formal.locator('#memberFollowing').click()
            expect(formal.locator('#memberConnectionsStatus')).to_have_text('No users yet.')
            js="""e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,text:e.innerText}}"""
            a=local.locator('#userConnectionsDialog').evaluate(js);b=formal.locator('#memberConnections').evaluate(js)
            print(json.dumps({'width':width,'local':a,'formal':b}),flush=True)
            assert all(abs(a[k]-b[k])<0.1 for k in ('x','y','width','height')), (width,a,b)
            assert a['text'].split()==b['text'].split(), (width,a['text'],b['text'])
            local.keyboard.press('Escape');formal.keyboard.press('Escape')
        browser.close()
finally:
    proc.send_signal(signal.SIGINT);proc.wait(timeout=20)
