"""Other-user Profile replaces the retired directory; viewer authority is separate."""
from urllib.parse import urlsplit
from contextlib import contextmanager
import socket,threading,uvicorn
from playwright.sync_api import sync_playwright, expect
from browser_diagnostics import diagnostic_page
from browser_cloud_public_catalog import HOLD_SCRIPT
from formal_ui_fixture import FormalUIFixture
BASE='http://ygc-follow-fixture.invalid'
@contextmanager
def local_server(fixture):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1]);server=uvicorn.Server(uvicorn.Config(fixture.app(),log_level='error',lifespan='off'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:yield base
        finally:server.should_exit=True;thread.join(timeout=10)

def main():
    fixture=FormalUIFixture();external=[];errors=[];images=[]
    with local_server(fixture) as BASE,sync_playwright() as pw,diagnostic_page(pw,'browser_cloud_follows') as page:
        page.add_init_script(HOLD_SCRIPT)
        page.add_init_script("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true')")
        page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            r=route.request;url=urlsplit(r.url)
            if url.scheme+'://'+url.netloc!=BASE:external.append(r.url);route.abort();return
            if url.path.endswith('/avatar'):images.append(r.headers)
            route.continue_()
        page.route('**/*',respond)
        page.goto(BASE+'/ui/members/2')
        expect(page.locator('#viewedUserProfile .profile-name')).to_have_text('Bob')
        assert urlsplit(page.url).path.startswith('/ui/profiles/2')
        expect(page.locator('#memberSearch')).to_have_count(0)
        expect(page.locator('#selfProfileEdit')).to_have_count(0)
        expect(page.locator('#profileFollow')).to_be_enabled()
        page.locator('#profileFollow').click();expect(page.locator('#profileFollow')).to_have_text('Unfollow')
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':844})
            page.get_by_role('button',name='Followers · 31',exact=True).click()
            expect(page.locator('#profileConnections a')).to_have_count(25)
            page.get_by_role('button',name='Load more',exact=True).click()
            expect(page.locator('#profileConnections a')).to_have_count(31)
            assert page.locator('#profileConnections a').first.get_attribute('href').startswith('/ui/profiles/')
            expect(page.locator('#profileConnections .ygc-modal-close')).to_have_text('×')
            assert page.locator('#profileConnections').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            page.keyboard.press('Escape');expect(page.locator('#profileConnections')).not_to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#profileFollow').click();expect(page.locator('#profileFollow')).to_have_text('Follow')
        fixture.drop_after_write=True
        page.locator('#profileFollow').click();expect(page.locator('#profileFollow')).to_be_disabled()
        page.reload();expect(page.locator('#profileFollow')).to_have_text('Unfollow')
        page.locator('#profileFollow').click();expect(page.locator('#profileFollow')).to_have_text('Follow')
        fixture.mode='read_only';page.reload();expect(page.locator('#profileFollow')).to_be_disabled()
        fixture.mode='normal';page.reload();expect(page.locator('#profileFollow')).to_be_enabled()
        page.evaluate("catalogFixture.hold('/api/auth/members/2/connections/followers','','late')")
        page.get_by_role('button',name='Followers · 30',exact=True).click()
        page.wait_for_function('()=>Boolean(catalogFixture.waiting.late)')
        page.keyboard.press('Escape');page.evaluate("catalogFixture.release('late')")
        expect(page.locator('#profileConnections a')).to_have_count(0)
        # Logout clears the target's rendered data synchronously before navigation.
        page.evaluate("favoritesFixtureSwitchUser('other@example.invalid')")
        expect(page.locator('#viewedUserProfile .profile-name')).to_have_text('Bob')
        expect(page.locator('#shellIdentity')).to_have_text('Other')
        assert fixture.writes==[(1,2,True),(1,2,False),(1,2,True),(1,2,False)]
        assert not external and not errors,(external,errors)
        print('Other-user Profile: retired-route redirect, no self editor, Follow/paging, uncertain writes, Read Only, delayed dismissal, viewer switch and 1440/390/320 passed.')
if __name__=='__main__':main()
