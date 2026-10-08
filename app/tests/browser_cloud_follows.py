"""Production member UI/HTTP routes with only synthetic accounts and SDK."""
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from browser_diagnostics import diagnostic_page
from browser_cloud_public_catalog import HOLD_SCRIPT
from follow_browser_fixture import FollowFixture

BASE='http://ygc-follow-fixture.invalid'

def main():
    fixture=FollowFixture();external=[];errors=[];image_requests=[]
    with TestClient(fixture.app(),base_url=BASE) as client, sync_playwright() as pw, diagnostic_page(pw,'browser_cloud_follows') as page:
        page.add_init_script(HOLD_SCRIPT)
        page.add_init_script("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true')")
        page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            r=route.request;url=urlsplit(r.url)
            if url.scheme+'://'+url.netloc!=BASE:external.append(r.url);route.abort();return
            if url.path.endswith('/avatar'): image_requests.append((url.path,r.headers))
            response=client.request(r.method,url.path+('?' +url.query if url.query else ''),headers=r.headers,content=r.post_data_buffer)
            route.fulfill(status=response.status_code,headers=dict(response.headers),body=response.content)
        page.route('**/*',respond)
        page.goto(BASE+'/members')
        expect(page.locator('#memberResults li')).to_have_count(25)
        assert page.locator('#memberResults button').count()==0
        expect(page.locator('#memberResults img')).to_have_count(3)  # Alice self, Members and Public
        assert not page.evaluate('Boolean(window.fixtureXss)')
        page.get_by_role('link',name='Next page',exact=True).click()
        expect(page.locator('#memberResults li')).to_have_count(25)
        page.get_by_role('link',name='Next page',exact=True).click()
        expect(page.locator('#memberResults li')).to_have_count(12)
        page.go_back();expect(page.locator('#memberResults li')).to_have_count(25)
        page.go_forward();expect(page.locator('#memberResults li')).to_have_count(12)
        page.get_by_label('Display name',exact=True).fill('Same name')
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.locator('#memberResults li')).to_have_count(2)
        expect(page.locator('#memberResults img')).to_have_count(1)
        assert page.locator('#memberResults a').all_text_contents()==['Same name','♙Same name']
        assert len(set(page.locator('#memberResults a').evaluate_all('(els)=>els.map(e=>e.href)')))==2
        page.get_by_label('Display name',exact=True).fill('Bob')
        page.get_by_role('button',name='Search',exact=True).click()
        page.get_by_role('link',name='Bob',exact=True).click()
        expect(page.get_by_role('heading',name='Bob',exact=True)).to_be_visible()
        expect(page.locator('#memberAvatar img')).to_have_count(0)
        page.get_by_role('button',name='Follow',exact=True).click()
        expect(page.get_by_role('button',name='Unfollow',exact=True)).to_be_enabled()
        expect(page.locator('#memberAvatar img')).to_have_count(1)
        assert page.locator('#memberAvatar img').get_attribute('src').startswith('blob:')
        page.get_by_role('button',name='Following · 0',exact=True).click()
        expect(page.locator('#memberConnectionsList li')).to_have_count(0)
        expect(page.locator('#memberConnectionsStatus')).to_have_text('No members found.')
        page.get_by_role('button',name='Close',exact=True).click()
        page.get_by_role('button',name='Followers · 31',exact=True).click()
        expect(page.locator('#memberConnectionsList li')).to_have_count(25)
        assert page.locator('#memberConnectionsList button').count()==0
        page.get_by_role('button',name='Load more',exact=True).click()
        expect(page.locator('#memberConnectionsList li')).to_have_count(31)
        page.get_by_role('button',name='Close',exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_role('button',name='Followers · 31',exact=True).click()
        page.keyboard.press('Escape');expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_role('button',name='Unfollow',exact=True).click()
        expect(page.get_by_role('button',name='Follow',exact=True)).to_be_enabled()
        expect(page.locator('#memberAvatar img')).to_have_count(0)
        page.go_back();expect(page.locator('#memberResults li')).to_have_count(1)
        page.go_forward();expect(page.get_by_role('button',name='Follow',exact=True)).to_be_enabled()
        fixture.drop_after_write=True
        page.get_by_role('button',name='Follow',exact=True).click()
        expect(page.locator('#memberStatus')).to_contain_text('uncertain')
        expect(page.locator('#memberFollow')).to_be_disabled()
        page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.get_by_role('button',name='Unfollow',exact=True)).to_be_enabled()
        page.get_by_role('button',name='Unfollow',exact=True).click()
        expect(page.get_by_role('button',name='Follow',exact=True)).to_be_enabled()
        fixture.mode='read_only';page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#memberFollow')).to_be_disabled()
        fixture.mode='normal';page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#memberFollow')).to_be_enabled()
        # Policy changes invalidate already displayed bytes; the same endpoint
        # is reauthorized rather than cached. Broadcast contains no identity/data.
        fixture.visibility[2]='Members'
        page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#memberAvatar img')).to_have_count(1)
        fixture.visibility[2]='Private'
        page.evaluate("(()=>{const c=new BroadcastChannel('ygc-member-avatar');c.postMessage('invalidate');c.close()})()")
        expect(page.locator('#memberAvatar img')).to_have_count(0)
        fixture.visibility[2]='Public'
        page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#memberAvatar img')).to_have_count(1)
        fixture.visibility[2]='Followers'
        page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#memberAvatar img')).to_have_count(0)
        # A late modal response cannot reopen a closed modal.
        page.evaluate("catalogFixture.hold('/api/auth/members/2/connections/followers','','modal')")
        page.get_by_role('button',name='Followers · 30',exact=True).click()
        page.wait_for_function('()=>Boolean(catalogFixture.waiting.modal)')
        page.get_by_role('button',name='Close',exact=True).click()
        page.evaluate("catalogFixture.release('modal')")
        expect(page.get_by_role('dialog')).not_to_be_visible()
        # Old actor's result cannot populate after an SDK user switch.
        page.evaluate("catalogFixture.hold('/api/auth/members/2','','identity')")
        page.get_by_role('button',name='Refresh',exact=True).click()
        page.wait_for_function('()=>Boolean(catalogFixture.waiting.identity)')
        page.evaluate("favoritesFixtureSwitchUser('bob@example.invalid')")
        page.evaluate("catalogFixture.release('identity')")
        expect(page.get_by_role('heading',name='Bob',exact=True)).to_be_visible()
        expect(page.locator('#memberFollow')).not_to_be_visible()
        expect(page.locator('#memberAvatar img')).to_have_count(1)  # target is now self
        assert fixture.writes==[(1,2,True),(1,2,False),(1,2,True),(1,2,False)]
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name='Followers · 30',exact=True).click()
        expect(page.locator('#memberConnectionsList li')).to_have_count(25)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.get_by_role('button',name='Close',exact=True).click()
        page.get_by_role('button',name='SignOut',exact=True).click()
        expect(page.locator('#memberGuest')).to_be_visible()
        expect(page.locator('#memberProfile')).not_to_be_visible()
        expect(page.locator('#memberResults li')).to_have_count(0)
        # Language reload restores authenticated member state and localizes the new UI.
        page.locator('[data-language-picker]').select_option('ja')
        expect(page.get_by_role('heading',name='Bob',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='フォロワー · 30',exact=True)).to_be_visible()
        expect(page.get_by_role('link',name='会員を探す',exact=True)).to_be_visible()
        assert image_requests and all(h.get('authorization','').startswith('Bearer fixture-') for _,h in image_requests)
        assert not external and not errors,(external,errors)
        print('Member browser: search/pages/same names, member profile, follows, third-party connections, history/modal cancellation, uncertain write, identity race, Guest and 390px passed.')

if __name__=='__main__':main()
