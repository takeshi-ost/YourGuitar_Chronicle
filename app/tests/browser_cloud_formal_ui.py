"""Formal shell acceptance: isolated loopback app and synthetic SDK only."""
import os
from pathlib import Path
import socket
import threading
import uvicorn
from playwright.sync_api import sync_playwright, expect
from formal_ui_fixture import FormalUIFixture


def check_formal_headers(page, base):
    """Catch missing theme containers and clipped mobile account navigation."""
    page.goto(base+'/ui/profile')
    page.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid'); sessionStorage.setItem('verified-alice@example.invalid','true')")
    page.reload()
    expect(page.locator('#selfProfileEdit')).to_be_visible()
    for route in ('/ui/profile', '/ui/members', '/ui/members/2'):
        page.goto(base+route)
        expect(page.locator('#selfProfileEdit' if route=='/ui/profile' else '#memberSignOut')).to_be_visible()
        for width in (1440, 390, 320):
            page.set_viewport_size({'width':width,'height':844})
            for theme,logo in (('sunburst_3ply','script'),('dark_default','block'),('butterscotch_black','badge')):
                page.evaluate("theme => document.documentElement.dataset.theme=theme",theme)
                expect(page.locator('.brand-logo:visible')).to_have_count(1)
                expect(page.locator('.brand-logo-'+logo)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (route,width,theme)
                # Every header control must fit without horizontal scrolling.
                assert page.locator('header .page-nav').evaluate("""nav => {
                    const bounds=nav.getBoundingClientRect();
                    return nav.scrollWidth<=nav.clientWidth+1 &&
                      [...nav.querySelectorAll('a,select')].every(el=>{
                        const r=el.getBoundingClientRect();
                        return r.left>=bounds.left-1 && r.right<=bounds.right+1 && r.right<=innerWidth;
                      });
                }"""), (route,width,theme)
    print('Formal profile/member headers: 1440/390/320px, three theme wordmarks, no page overflow and fully visible navigation passed.')


def main():
    fixture=FormalUIFixture()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(fixture.app(),log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.environ.get('YGC_BROWSER_EXECUTABLE'))
                context=browser.new_context(viewport={'width':1440,'height':1000})
                # The fixture already serves a local fake SDK. No external traffic.
                context.route('https://**/*',lambda route:route.abort())
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/ui');expect(page.locator('#catalogRows tr')).to_have_count(24)
                expect(page.locator('#shellIdentity')).to_contain_text('Explore guitar histories')
                assert not any('/api/auth/favorites/' in path for _,path in fixture.calls)
                page.locator('#catalogSearch').fill('Fender');page.locator('#catalogSearchSubmit').click()
                expect(page.locator('#catalogRows tr')).to_have_count(15)
                page.locator('#catalogRows a').first.click();expect(page.locator('#detailContent')).to_be_visible()
                assert '/ui/guitars/' in page.url and 'q=Fender' in page.url
                selected=page.url;expect(page.locator('#acquireLink')).to_have_attribute('href','/ui/profile?acquire=29')
                page.go_back();expect(page.locator('#detailContent')).not_to_be_visible()
                page.go_forward();expect(page.locator('#detailContent')).to_be_visible()
                page.reload();expect(page.locator('#detailContent')).to_be_visible();assert page.url==selected
                # Focus trap, Escape and credential disposal, with return to opener.
                page.locator('#shellSignIn').click();expect(page.locator('#shellEmail')).to_be_focused()
                page.locator('#shellEmail').fill('alice@example.invalid');page.locator('#shellPassword').fill('discard-me')
                page.keyboard.press('Escape');expect(page.locator('#shellSignIn')).to_be_focused()
                assert page.locator('#shellPassword').input_value()=='' and page.locator('#shellEmail').input_value()==''
                page.locator('#shellSignIn').click();page.keyboard.press('Shift+Tab');expect(page.locator('#shellRegister')).to_be_focused()
                page.keyboard.press('Tab');expect(page.locator('#shellEmail')).to_be_focused()
                page.locator('#shellEmail').fill('alice@example.invalid');page.locator('#shellPassword').fill('bad');page.locator('#shellSubmit').click()
                expect(page.locator('#shellLoginStatus')).to_contain_text('could not be completed');assert page.locator('#shellPassword').input_value()==''
                page.evaluate("sessionStorage.setItem('verified-alice@example.invalid','true')")
                page.locator('#shellEmail').fill('alice@example.invalid');page.locator('#shellPassword').fill('fixture-password');page.locator('#shellSubmit').click()
                expect(page.locator('#shellIdentity')).to_have_text('Alice');expect(page.locator('#shellSignInDialog')).not_to_be_visible()
                expect(page.locator('#favoriteToggle')).to_be_visible()
                assert page.url==selected
                # Canonical identity changes clear private controls before Refresh.
                page.evaluate("sessionStorage.setItem('verified-bob@example.invalid','true'); favoritesFixtureSwitchUser('bob@example.invalid')")
                expect(page.locator('#shellIdentity')).not_to_have_text('Alice');expect(page.locator('#catalogRows tr')).to_have_count(0)
                expect(page.locator('#favoriteToggle')).not_to_be_visible()
                page.locator('#catalogRefresh').click();expect(page.locator('#shellIdentity')).to_have_text('Bob')
                fixture.reject_identity=True;page.locator('#catalogRefresh').click()
                expect(page.locator('#catalogRows tr')).to_have_count(0);expect(page.locator('#shellIdentity')).not_to_have_text('Bob')
                fixture.reject_identity=False;page.locator('#catalogRefresh').click();expect(page.locator('#shellIdentity')).to_have_text('Bob')
                page.locator('#shellSignOut').click();expect(page.locator('#shellIdentity')).to_contain_text('Explore guitar histories')
                expect(page.locator('#shellAccountLinks')).not_to_be_visible();expect(page.locator('#favoriteToggle')).not_to_be_visible()
                fixture.mode='offline';page.locator('#catalogRefresh').click();expect(page.locator('#catalogRows tr')).to_have_count(0)
                expect(page.locator('#detailContent')).not_to_be_visible();expect(page.locator('#serviceNotice')).to_be_visible()
                fixture.mode='normal';page.locator('#catalogRefresh').click();expect(page.locator('#detailContent')).to_be_visible()
                artifacts=Path(os.environ.get('YGC_BROWSER_ARTIFACTS','/tmp/ygc-formal-ui-artifacts'));artifacts.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(artifacts/'formal-ui-desktop.png'))
                page.set_viewport_size({'width':390,'height':844});page.locator('#catalogLanguage').select_option('ja')
                expect(page.locator('#shellTitle')).to_have_text('トップページ')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                box=page.locator('#productDetailShell').bounding_box();assert box['x']>=0 and box['x']+box['width']<=390
                page.screenshot(path=str(artifacts/'formal-ui-mobile.png'))
                page.keyboard.press('Escape');expect(page.locator('#productDetailShell')).not_to_be_visible();expect(page.locator('#listHeading')).to_be_focused()
                page.locator('#shellSignIn').click();page.keyboard.press('Escape');expect(page.locator('#shellSignInDialog')).not_to_be_visible()
                page.set_viewport_size({'width':320,'height':640});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#catalogRows a').first.click();expect(page.locator('#detailContent')).to_be_visible()
                box=page.locator('#productDetailShell').bounding_box();assert box['x']>=0 and box['x']+box['width']<=320
                assert not errors,errors
                assert not any(method not in ('GET','HEAD') for method,path in fixture.calls),fixture.calls
                check_formal_headers(page,base)
                context.close();browser.close()
                print('Formal UI: routes/history, canonical auth/identity switch/revocation, credential disposal, modal focus, Offline, Japanese and 1440/390/320px passed; only synthetic GET reads.')
        finally:
            server.should_exit=True;thread.join(timeout=10)
            assert not thread.is_alive()

if __name__=='__main__':main()
