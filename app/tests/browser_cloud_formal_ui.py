"""Formal shell acceptance: isolated loopback app and synthetic SDK only."""
import os
import re
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
    page.locator('#shellNotifications').click()
    expect(page.locator('#formalNotifications')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('#formalNotifications')).not_to_be_visible()
    expect(page.locator('#shellNotifications')).to_be_focused()
    expect(page.locator('.profile-name')).to_have_text('Alice')
    for direction in ('followers','following'):
        trigger=page.locator('[data-connections="'+direction+'"]')
        expect(trigger).to_be_visible()
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':844})
            trigger.click();expect(page.locator('#userConnectionsDialog')).to_be_visible()
            expect(page.locator('#userConnectionsStatus')).to_have_text(page.evaluate("YGCI18n.t('ui.no_users_yet_44e4e2d9')"))
            assert page.locator('#userConnectionsDialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            page.keyboard.press('Escape');expect(page.locator('#userConnectionsDialog')).not_to_be_visible()
            expect(trigger).to_be_focused()
    page.set_viewport_size({'width':1440,'height':844})
    for route in ('/ui/profile', '/ui/profiles/2'):
        page.goto(base+route)
        expect(page.locator('#selfProfileEdit' if route=='/ui/profile' else '#profileFollow')).to_be_visible()
        if route=='/ui/profile':expect(page.locator('#selfProfileEdit')).to_be_enabled()
        for width in (1440, 390, 320):
            page.set_viewport_size({'width':width,'height':844})
            for theme,logo in (('sunburst_3ply','script'),('dark_default','block'),('butterscotch_black','badge')):
                page.evaluate("theme => document.documentElement.dataset.theme=theme",theme)
                expect(page.locator('.brand-logo:visible')).to_have_count(1)
                expect(page.locator('.brand-logo-'+logo)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (route,width,theme,page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth && getComputedStyle(e).position!=='fixed').map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right]).slice(0,20)"))
                # Match local position links: horizontal navigation may scroll; the page must not.
                assert page.locator('header .page-nav').evaluate("""nav => {
                    const bounds=nav.getBoundingClientRect();
                    return bounds.left>=0 && bounds.right<=innerWidth && (nav.scrollWidth<=nav.clientWidth+1 || getComputedStyle(nav).overflowX==='auto');
                }"""), (route,width,theme)
    print('Formal profile/member headers: 1440/390/320px, three theme wordmarks, no page overflow and contained horizontal navigation passed.')


def check_profile_lists(page,base,fixture):
    page.set_viewport_size({'width':1440,'height':1000})
    fixture.profile_all=True
    fixture.favorites={('synthetic-1',str(i)) for i in range(1,31)}
    page.goto(base+'/ui/profile')
    page.evaluate("localStorage.setItem('ygc_ui_language','en');sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true');sessionStorage.removeItem('ygc-self-display-v1')")
    page.reload()
    # The seed changed outside a user mutation; remove only the disposable
    # display cache before the reload so this is a fresh-profile measurement.
    expect(page.locator('#formalProfileRefresh')).to_have_count(0)
    expect(page.locator('#selfGuitars_owned .toolbar button').last).to_be_enabled()
    page.locator('#selfFavorites #favoritesRefresh').click()
    owned=page.locator('#selfGuitars_owned')
    favorites=page.locator('#selfFavorites')
    expect(owned.locator('tbody tr.clickable')).to_have_count(30)
    try:
        expect(favorites.locator('tbody tr.clickable')).to_have_count(30)
    except AssertionError:
        print('Synthetic Favorites diagnostics:',favorites.inner_text(),fixture.calls[-60:],flush=True)
        raise
    expect(owned.locator('tbody tr.clickable').first.locator('td').first).to_have_text('1')
    expect(favorites.locator('tbody tr.clickable').first.locator('td').first).to_have_text('1')
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # ResizeObserver applies the canonical measured height on the next frame.
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        height=owned.bounding_box()['height']
        owned.locator('.toolbar input').fill('Sunburst 1963')
        expect(owned.locator('tbody tr.clickable')).to_have_count(4)
        if width>900:assert abs(owned.bounding_box()['height']-height)<1
        owned.locator('.toolbar input').fill('')
    page.set_viewport_size({'width':1440,'height':1000})
    owned.locator('thead th').first.click()
    expect(owned.locator('tbody tr.clickable').first.locator('td').first).to_have_text('30')
    owned.locator('tbody tr.clickable').first.locator('td').first.locator('a').click()
    expect(page.locator('#detailTitle')).to_contain_text('Fixture 30')
    expect(favorites.locator('tr.selected')).to_have_count(1)
    owned.locator('.toolbar input').fill('no match')
    expect(page.locator('#detailTitle')).to_contain_text('Fixture 30')
    assert '/guitars/30' in page.url
    owned.locator('.toolbar input').fill('')
    expect(owned.locator('tr.selected')).to_have_count(1)
    ids=page.locator('[id]').evaluate_all('(els)=>els.map(e=>e.id)')
    assert len(ids)==len(set(ids)),[value for value in set(ids) if ids.count(value)>1]
    fixture.profile_all=False
    print('Formal profile lists: 30-row cursor aggregation, local columns/order/live filter, fixed unfiltered desktop height, cross-list selection and 1440/390/320 passed.')


def check_profile_bootstrap_timing(page,base,fixture):
    import time,json
    page.set_viewport_size({'width':1440,'height':1000})
    page.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true');sessionStorage.removeItem('ygc-self-display-v1')")
    fixture.profile_all=True;fixture.profile_cursor_gate=threading.Event()
    gate=fixture.profile_cursor_gate
    before=len(fixture.calls);started=time.monotonic()
    try:
        page.goto(base+'/ui/profile/guitars/1')
        expect(page.locator('#detailContent')).to_be_visible()
        detail_ms=round((time.monotonic()-started)*1000)
        expect(page.locator('#selfGuitars_owned tbody tr.clickable')).to_have_count(0)
        calls=fixture.calls[before:]
        assert calls.count(('GET','/api/auth/profile/bootstrap'))==1,calls
        # First pages/settings/counts/signature are one HTTP read. A deliberately
        # held cursor continuation must not hold the explicit initial Detail.
        assert not any(path in ('/api/auth/settings','/api/auth/profile/summary','/api/auth/settings/signature') for method,path in calls),calls
        gate.set()
        expect(page.locator('#selfGuitars_owned tbody tr.clickable')).to_have_count(30)
        list_ms=round((time.monotonic()-started)*1000)
        artifacts=Path(os.environ.get('YGC_BROWSER_ARTIFACTS','/tmp/ygc-formal-ui-artifacts'));artifacts.mkdir(parents=True,exist_ok=True)
        result={'initial_profile_reads_before':6,'initial_profile_reads_after':1,'detail_visible_before_cursor_completion':True,'fixture_detail_visible_ms':detail_ms,'fixture_all_owned_rows_ms':list_ms,'live_latency_measured':False}
        (artifacts/'profile-bootstrap-timing.json').write_text(json.dumps(result,indent=2));print('Profile bootstrap timing:',json.dumps(result),flush=True)
    finally:
        gate.set();fixture.profile_cursor_gate=None;fixture.profile_all=False


def check_settings(page,base,fixture):
    page.goto(base+'/ui/settings')
    expect(page.locator('#settings')).to_be_visible()
    expect(page.locator('#displayName')).to_have_value('Alice')
    expect(page.locator('#userId')).to_have_value('1')
    expect(page.locator('#cloudAuthDialog')).to_be_hidden();expect(page.locator('#authPolicyDialog')).to_be_hidden()
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        expect(page.locator('#saveButton')).to_be_visible()
    page.locator('#theme').select_option('butterscotch_black')
    expect(page.locator('html')).to_have_attribute('data-theme','butterscotch_black')
    page.get_by_role('button',name='Cancel',exact=True).click()
    expect(page).to_have_url(base+'/ui/profile')
    assert not fixture.writes
    page.goto(base+'/ui/settings');expect(page.locator('#settings')).to_be_visible()
    expect(page.locator('#theme')).to_have_value('sunburst_3ply')
    page.locator('#displayName').fill('Alice Settings')
    page.locator('#accountType').select_option('builder')
    page.locator('#dateOfBirth').fill('2000-01-01')
    page.locator('#theme').select_option('butterscotch_black')
    page.locator('#signatureGuitar').select_option('1')
    page.locator('#saveButton').click()
    expect(page).to_have_url(base+'/ui/profile')
    assert fixture.writes==[('settings',1),('signature',1)],fixture.writes
    page.goto(base+'/ui/settings');expect(page.locator('#settings')).to_be_visible()
    expect(page.locator('#displayName')).to_have_value('Alice Settings')
    expect(page.locator('#dateOfBirth')).to_have_value('2000-01-01')
    expect(page.locator('#accountType')).to_have_value('builder')
    expect(page.locator('#theme')).to_have_value('butterscotch_black')
    expect(page.locator('#signatureGuitar')).to_have_value('1')
    print('User Settings: canonical page, 1440/390/320, theme preview/Cancel without writes, explicit Save and reload; synthetic settings/signature only, no upload.')


def check_favorite_sync(page,base,fixture):
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(base+'/ui/profile/guitars/1')
    row=page.locator('#profileRows-owned_1_favoriteToggle')
    detail=page.locator('#favoriteToggle')
    expect(row).to_be_enabled();expect(detail).to_be_enabled()
    expect(row).to_have_attribute('aria-pressed','true')
    expect(detail).to_have_attribute('aria-pressed','true')
    expect(page.locator('#favoritesList tr.clickable')).to_have_count(30)
    row.click()
    expect(detail).to_have_attribute('aria-pressed','false')
    expect(page.locator('#favoritesList tr.clickable')).to_have_count(29)
    detail.click()
    expect(row).to_have_attribute('aria-pressed','true')
    expect(page.locator('#favoritesList tr.clickable')).to_have_count(30)
    assert ('synthetic-1','1') in fixture.favorites
    print('Favorite: Owned-row/detail hearts and Favorite collection update together after two explicit synthetic toggles.')


def check_claim_forms(page,base,fixture):
    page.goto(base+'/ui/profile/guitars/1')
    expect(page.locator('#selfProfileEdit')).to_be_enabled()
    before=list(fixture.writes)
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        for kind,title in (('specification','Specification/Repair Claim'),('incident','Incident Claim'),('event','Event Claim'),('media','Media Claim')):
            page.locator('#addClaimLink').click()
            page.locator('[data-claim-type="'+kind+'"]').click()
            expect(page.locator('#claimDialog.open .modal')).to_be_visible()
            expect(page.locator('#claimTitle')).to_have_text(title)
            assert page.locator('#claimDialog .modal').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),(width,kind)
            if kind=='specification':
                expect(page.locator('#specKindSpecification')).to_be_visible()
                expect(page.locator('#claimItems')).to_contain_text('Use + to add a field.')
                page.locator('.spec-add-button').click()
                page.locator('#specItemMenu').get_by_role('button',name='Nut',exact=True).click()
                expect(page.locator('#claimItems .spec-item-row')).to_have_count(1)
            if kind=='media':expect(page.locator('#mediaClaimImages .media-image-slot.visible')).to_have_count(1)
            page.keyboard.press('Escape')
            expect(page.locator('#claimDialog')).not_to_be_visible()
            # Only the overlay closes; compact Product Detail remains selected.
            expect(page.locator('#productDetailShell')).to_be_visible()
    assert fixture.writes==before
    page.set_viewport_size({'width':1440,'height':1000})
    for kind in ('specification','incident','event'):
        page.locator('#addClaimLink').click();page.locator('[data-claim-type="'+kind+'"]').click()
        expect(page.locator('#claimDialog')).to_be_visible()
        if kind=='specification':
            page.locator('#specKindRepair').click();page.locator('.spec-add-button').click()
            page.locator('#specItemMenu').get_by_role('button',name='Nut',exact=True).click()
            page.locator('#claimValue_0').fill('Synthetic bone nut')
        page.locator('#claimBody').fill('Synthetic '+kind+' draft')
        page.locator('#claimSave').click();expect(page.locator('#claimDialog')).not_to_be_visible()
        expect(page.locator('#selfProfileEdit')).to_be_enabled()
        page.locator('#chronicleEntries [data-private-claim-action=edit]').first.click();expect(page.locator('#claimDialog')).to_be_visible()
        expect(page.locator('#claimBody')).to_have_value('Synthetic '+kind+' draft')
        page.locator('#claimBody').fill('Synthetic '+kind+' edited')
        page.locator('#claimSave').click();expect(page.locator('#claimDialog')).not_to_be_visible()
        expect(page.locator('#selfProfileEdit')).to_be_enabled()
    assert len([w for w in fixture.writes if w[0]=='claim_create'])==3
    assert len([w for w in fixture.writes if w[0]=='claim_edit'])==3
    print('Canonical Claim forms: PC/390/320, four per-kind layouts, Escape/focus/selection, Specification/Incident/Event create and edit; no upload.')


def check_application_forms(page,base,fixture):
    page.goto(base+'/ui/profile/guitars/2');expect(page.locator('#selfProfileEdit')).to_be_enabled()
    before=list(fixture.writes)
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        page.locator('#acquireLink').click();expect(page.locator('#applicationDialog.open')).to_be_visible()
        expect(page.locator('#applicationDialog')).to_contain_text('Not saved')
        expect(page.locator('#applicationDialog .challenge-box')).to_contain_text('SYNTH123')
        expect(page.locator('#application_occurred_at')).to_be_visible()
        expect(page.locator('#application_closeup')).to_be_visible()
        expect(page.locator('#applicationKeep')).to_be_visible()
        expect(page.locator('#applicationRefresh')).not_to_be_visible()
        assert page.locator('#applicationDialog .modal').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
        page.keyboard.press('Escape');expect(page.locator('#applicationDialog')).not_to_be_visible()
    assert fixture.writes==before
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('#acquireLink').click();expect(page.locator('#applicationDialog.open')).to_be_visible()
    page.locator('#application_occurred_at').fill('2020-01-01');page.locator('#application_body').fill('Synthetic keep')
    page.locator('#applicationKeep').click();expect(page.locator('#ownershipConfirmModal')).to_be_visible()
    page.locator('#ownershipConfirmSubmit').click();expect(page.locator('#applicationDialog')).not_to_be_visible()
    expect(page.locator('#importantInformation .unanswered-request')).to_have_count(1)
    page.locator('#importantInformation .unanswered-request button').click();expect(page.locator('#applicationDialog')).to_be_visible()
    expect(page.locator('#application_body')).to_have_value('Synthetic keep')
    page.keyboard.press('Escape')
    page.locator('#applicationListing').click();expect(page.locator('#applicationDialog')).to_be_visible()
    expect(page.locator('#applicationDialog .challenge-box')).to_contain_text('Not generated')
    expect(page.locator('#application_closeup')).to_be_disabled()
    page.locator('#application_manufacturer').fill('Synthetic');page.locator('#application_serial_number').fill('SYNTHETIC-ONLY')
    page.locator('#applicationCreate').click();expect(page.locator('#applicationDialog .challenge-box')).to_contain_text('SYNTH123')
    expect(page.locator('#application_manufacturer')).to_have_attribute('readonly','')
    page.keyboard.press('Escape')
    assert len([row for row in fixture.writes if row[0]=='application_keep'])==1
    print('Acquire/Listing: canonical modal, unsaved challenge on open, Cancel leaves no request, explicit Keep creates important-information row, PC/390/320; no photo selected/uploaded.')


def check_ownership_entry(page,base,fixture):
    page.goto(base+'/ui/profile/guitars/1');expect(page.locator('#selfProfileEdit')).to_be_enabled()
    before=len(fixture.writes)
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        page.locator('#addClaimLink').click();page.locator('#addClaimMenu [data-ownership-entry]').click();expect(page.locator('#ownershipDialog.open')).to_be_visible()
        expect(page.locator('#ownershipTitle')).to_have_text('Ownership')
        page.locator('#ownershipSearch').fill('Bob');page.locator('#ownershipSearchButton').click()
        expect(page.locator('#ownershipCandidates button')).to_have_count(1)
        page.locator('#ownershipCandidates button').click();expect(page.locator('#ownershipSelected')).to_have_text('To: Bob (#2)')
        page.locator('#ownershipKind').select_option('release')
        expect(page.locator('#ownershipPrevious')).to_be_visible();expect(page.locator('#ownershipDate')).to_have_value('')
        assert page.locator('#ownershipDialog .modal').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),(width,page.locator('#ownershipDialog .modal').evaluate("e=>({classes:e.className,width:e.clientWidth,scroll:e.scrollWidth,items:[...e.querySelectorAll('*')].filter(x=>x.getBoundingClientRect().right>e.getBoundingClientRect().right-18&&x.getClientRects().length).map(x=>[x.tagName,x.id,x.className,x.getBoundingClientRect().width,getComputedStyle(x).boxSizing,getComputedStyle(x).position])})"))
        page.keyboard.press('Escape');expect(page.locator('#ownershipDialog')).not_to_be_visible()
    assert len(fixture.writes)==before
    page.locator('#addClaimLink').click();page.locator('#addClaimMenu [data-ownership-entry]').click();expect(page.locator('#ownershipDialog.open')).to_be_visible()
    page.locator('#ownershipKind').select_option('release');page.locator('#ownershipPrevious').fill('Synthetic person');page.locator('#ownershipBody').fill('Synthetic release')
    page.locator('#ownershipReview').click();expect(page.locator('#ownershipConfirmModal')).to_be_visible()
    page.keyboard.press('Escape');expect(page.locator('#ownershipDialog')).to_be_visible();assert len(fixture.writes)==before
    page.locator('#ownershipReview').click();page.locator('#ownershipConfirmSubmit').click();expect(page.locator('#ownershipDialog')).not_to_be_visible()
    assert fixture.writes[-1]==('release','1',{'occurred_at':None,'body':'Synthetic release','revision':'a'*64,'previous_owner_text':'Synthetic person'})
    fixture.profile_all=True
    page.goto(base+'/ui/profile/guitars/2');expect(page.locator('#addClaimMenu [data-ownership-entry]')).to_be_enabled()
    page.locator('#addClaimLink').click();page.locator('#addClaimMenu [data-ownership-entry]').click();expect(page.locator('#ownershipDialog.open')).to_be_visible()
    page.locator('#ownershipSearch').fill('Bob');page.locator('#ownershipSearchButton').click();page.locator('#ownershipCandidates button').click();page.locator('#ownershipReview').click()
    expect(page.locator('#transferReviewTitle')).to_have_text('Transfer');expect(page.locator('#transferReviewBody')).to_contain_text('Alice → Bob')
    expect(page.locator('#ownershipCancel')).to_be_enabled();page.locator('#ownershipCancel').click();expect(page.locator('#transferReviewBody')).to_contain_text('cancelled')
    page.locator('#ownershipClose').click();expect(page.locator('#ownershipDialog')).not_to_be_visible()
    assert fixture.writes[-1]==('transfer_cancel','501')
    page.locator('#addClaimLink').click();page.locator('#addClaimMenu [data-ownership-entry]').click()
    page.locator('#ownershipSearch').fill('Bob');page.locator('#ownershipSearchButton').click();page.locator('#ownershipCandidates button').click();page.locator('#ownershipReview').click()
    expect(page.locator('#ownershipCancel')).to_be_enabled()
    page.evaluate("sessionStorage.setItem('fixture-sdk-email','bob@example.invalid');sessionStorage.setItem('verified-bob@example.invalid','true')");page.goto(base+'/ui/profile')
    incoming=page.locator('#ownershipInbox .unanswered-request')
    expect(incoming).to_contain_text('Alice has offered to transfer')
    expect(incoming.locator('a').first).to_have_attribute('href','/ui/profiles/1')
    before=len(fixture.writes)
    incoming.locator('button').filter(has_text='Decline').click();expect(page.locator('#ownershipConfirmModal')).to_be_visible();page.keyboard.press('Escape');assert len(fixture.writes)==before
    incoming.locator('button').filter(has_text='Decline').click();page.locator('#ownershipConfirmSubmit').click()
    expect(page.locator('#transferReviewBody')).to_contain_text('declined');assert fixture.writes[-1]==('transfer_decline','501')
    page.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid')");page.goto(base+'/ui/profile')
    print('Ownership entry: canonical Transfer/Release fields, search/selection, optional date/related person, PC/390/320, confirmation Cancel without write and explicit synthetic Release passed.')


def check_notification_cards(page,base,fixture):
    fixture.notices=[dict(id='1',notification_type='synthetic',title='Synthetic notice',body='Fixture message',created_at='2026-10-08T09:00:00Z',is_read=False,read_at=None,actor=None,destination=None)]
    page.goto(base+'/ui/profile');expect(page.locator('#selfProfileEdit')).to_be_enabled()
    page.locator('#shellNotifications').click();expect(page.locator('#notificationList > .notification-item.unread')).to_have_count(1)
    before=len(fixture.writes)
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844});assert page.locator('#formalNotifications .modal').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
    assert len(fixture.writes)==before
    expect(page.locator('#shellNotifications .account-hub-count')).to_have_text('1')
    page.locator('#notificationList > .notification-item').click();expect(page.locator('#formalNotifications')).not_to_be_visible()
    page.locator('#shellNotifications').click();expect(page.locator('#notificationList > .notification-item.unread')).to_have_count(0)
    assert fixture.writes[-1]==('notification_read','1')
    expect(page.locator('#shellNotifications .account-hub-count')).to_have_text('0')
    page.keyboard.press('Escape')
    print('Notification cards: canonical card classes/contents, PC/390/320, opening is read-only, explicit card activation marks only recipient notice; no invented destination.')


def check_claim_popup(page,base):
    import json
    endpoint=base+'/api/public/guitars/2/chronicle*'
    data={'items':[dict(id='902',claim_type='specification',ownership_kind=None,occurred_at=None,created_at='2026-01-01T12:00:00Z',verification_status='unverified',items=[],source_url=None)],'next_after':None}
    page.route(endpoint,lambda route:route.fulfill(content_type='application/json',body=json.dumps(data)))
    try:
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':844});page.goto(base+'/ui/profile/guitars/2')
            tag=page.locator('#chronicleEntries .claim-compact-tag.claim-type-specification');expect(tag).to_be_visible();tag.click()
            popup=page.locator('#claimPopupModal');expect(popup).to_be_visible()
            expect(popup.locator('.claim-event-date')).to_have_text('Date unknown')
            expect(popup.locator('.claim-votes,.claim-footer-meta,img')).to_have_count(0)
            assert popup.locator('.claim-popup-modal').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth}')
            page.keyboard.press('Escape');expect(popup).to_have_count(0);expect(tag).to_be_focused()
    finally:page.unroute(endpoint)
    print('Claim popup: canonical tag color/date/popup positioning, PC/390/320 and Escape/focus; omitted public author/body/votes/photos stay omitted.')


def check_formal_follow(page,base,fixture):
    page.goto(base+'/ui/profiles/2')
    expect(page.locator('#profileFollow')).to_be_enabled()
    expect(page.locator('#profileFollow')).to_have_text('Follow')
    page.locator('#profileFollow').click()
    try:expect(page.locator('#profileFollow')).to_have_text('Unfollow')
    except AssertionError:
        print('Synthetic Follow diagnostics:',fixture.follows,fixture.writes[-8:],page.locator('#viewedUserProfile').inner_text(),flush=True)
        raise
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        page.get_by_role('button',name='Followers · 31',exact=True).click()
        expect(page.locator('dialog[open] a')).to_have_count(25)
        page.get_by_role('button',name='Load more',exact=True).click();expect(page.locator('dialog[open] a')).to_have_count(31)
        page.keyboard.press('Escape');expect(page.locator('dialog[open]')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#profileFollow').click();expect(page.locator('#profileFollow')).to_have_text('Follow')
    print('Other profile: canonical viewer, Follow, connections paging, modal close and mobile passed.')


def check_prepublication(page,base,fixture):
    fixture.prepublication=True
    page.set_viewport_size({'width':1440,'height':900})
    held=[]
    page.route(base+'/api/public/guitars/1/photo',lambda route:held.append(route))
    page.goto(base+'/ui/guitars/1')
    photo=page.locator('#detailPhoto');expect(photo).to_have_attribute('data-photo-loading','true');assert photo.get_attribute('src') is None
    card=page.locator('[data-claim-id="101"]')
    expect(card.locator('[data-vote="good"]')).to_be_enabled()
    assert len(held)==1;held.pop().fulfill(content_type='image/jpeg',body=fixture.images[1]);page.unroute(base+'/api/public/guitars/1/photo')
    expect(photo).to_be_visible();expect(photo).to_have_attribute('src',re.compile('^blob:'));assert len([call for call in fixture.calls if call==('GET','/api/public/guitars/1/photo')])==0
    card.locator('[data-vote="good"]').click()
    expect(card.locator('[data-vote="good"]')).to_have_attribute('aria-pressed','true')
    expect(card.locator('[data-vote="good"]')).to_have_text('👍 1')
    card.locator('[data-vote="bad"]').click()
    expect(card.locator('[data-vote="bad"]')).to_have_attribute('aria-pressed','true')
    page.reload();expect(card.locator('[data-vote="bad"]')).to_have_text('👎 1')
    expect(card.locator('[data-vote="bad"]')).to_have_attribute('aria-pressed','true')
    expect(card.locator('[data-private-claim-action="edit"]')).to_be_enabled()
    card.locator('[data-private-claim-action="edit"]').click()
    expect(page.locator('#identityDialog')).to_be_visible()
    expect(page.locator('#identityGuitar')).to_contain_text('Fixture 1')
    page.locator('#identityClose').click()
    expect(page.locator('html')).to_have_attribute('data-theme','butterscotch_black')
    held_settings=[];page.route(base+'/api/auth/settings',lambda route:held_settings.append(route))
    page.goto(base+'/ui/settings');expect(page.locator('html')).to_have_attribute('data-theme','butterscotch_black')
    page.unroute(base+'/api/auth/settings')
    for route in held_settings:route.continue_()
    expect(page.locator('#settings')).to_be_visible()
    page.goto(base+'/ui/profile/guitars/1')
    expect(page.locator('#selfIdentityCorrections')).to_be_hidden()
    expect(page.locator('#selfFavorites .toolbar #favoritesRefresh')).to_be_visible()
    expect(page.locator('#selfGuitars_owned .toolbar button')).to_be_visible()
    expect(page.locator('[data-claim-id="101"] [data-private-claim-action="edit"]')).to_be_enabled()
    page.locator('[data-claim-id="101"] [data-private-claim-action="edit"]').click()
    expect(page.locator('#identityDialog')).to_be_visible();page.locator('#identityClose').click()
    page.goto(base+'/account');expect(page.locator('html')).to_have_attribute('data-theme','butterscotch_black')
    expect(page.locator('#accountSummary')).to_contain_text('Alice')
    assert page.locator('main').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(25, 23, 21)'
    for path in ('/console',):
        page.goto(base+path);expect(page.locator('html')).to_have_attribute('data-theme','butterscotch_black')
        assert page.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(188, 132, 52)'
    print('Prepublication: member Good/Bad persist through reload independently of owner decisions; Listing Edit opens author correction on Top/Profile; independent Profile panel removed and list Refresh visible.')
    fixture.prepublication=False


def check_round2(page,base,fixture):
    # Explicit destination opens its Detail before the Claim confirmation.
    claim=dict(id='901',individual_id='1',claim_type='specification',specification_kind='specification',ownership_kind=None,incident_kind=None,event_kind=None,status='active',verification_status='unverified',revision='a'*64,body='Synthetic notification Claim',occurred_at='2026-01-01',created_at='2026-01-01T12:00:00Z',updated_at='2026-01-01',spec_items=[{'field_name':'nut','value_text':'Bone'}],media_items=[],author_name='Bob',decline_reason_required=False)
    previous=fixture.owner_rows;fixture.owner_rows=[claim]
    fixture.notices=[dict(id='81',notification_type='claim_added',title='New Specification Claim',body='Synthetic notice',created_at='2026-10-08T09:00:00Z',is_read=True,read_at='2026-10-08T09:00:00Z',actor=None,destination={'kind':'owner','individual_id':'1','claim_id':'901'})]
    for width in (1440,390,320):
        page.set_viewport_size({'width':width,'height':844})
        page.goto(base+'/ui');expect(page.locator('#shellIdentity')).to_have_text(fixture.people[1]['display_name'])
        page.locator('#shellNotifications').click();page.locator('[data-notification-id="81"]').click()
        expect(page.locator('#detailTitle')).to_contain_text('Fixture 1')
        expect(page.locator('#ownerResponseDialog.open')).to_be_visible()
        expect(page.locator('#ownerResponseDialog select')).to_be_visible()
        panel=page.locator('#ownerResponseDialog .claim-popup-modal')
        assert panel.evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight}'),panel.bounding_box()
        expect(panel.locator('.ygc-modal-close')).to_have_text('×')
        panel.locator('.ygc-modal-close').click();expect(page.locator('#ownerResponseDialog')).not_to_be_visible()
        expect(page.locator('#formalProfileRefresh')).to_have_count(0)
    fixture.owner_rows=previous
    page.goto(base+'/ui/settings');expect(page.locator('#settings')).to_be_visible()
    assert page.locator('main').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
    page.goto(base+'/ui');page.locator('#shellSignOut').click();expect(page.locator('#shellSignIn')).to_be_visible()
    page.locator('#catalogLanguage').select_option('ja');expect(page.locator('#shellSignIn')).to_have_text('サインイン/ アカウント作成')
    page.locator('#shellSignIn').click();dialog=page.locator('#cloudAuthDialog')
    expect(dialog.locator('#authCancel')).to_have_text('×')
    expect(dialog.locator('#authCreateAccount')).to_have_text('Register for a New Account here.')
    expect(dialog.locator('#authCreateAccount strong')).to_have_text('New Account')
    assert dialog.locator('#authSubmit').evaluate('(e)=>Math.abs(e.getBoundingClientRect().width-e.parentElement.getBoundingClientRect().width)<2')
    for theme in ('dark_default','light_default','sunburst_3ply','butterscotch_black','black_pearl','lake_blue_pearl'):
        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
        assert page.evaluate('''()=>{const p=getComputedStyle(document.querySelector('#catalogList')),m=getComputedStyle(document.querySelector('#cloudAuthDialog'));return p.backgroundColor===m.backgroundColor&&p.backgroundImage===m.backgroundImage&&p.borderTopWidth===m.borderTopWidth&&p.borderTopStyle===m.borderTopStyle}'''),theme
    dialog.locator('#authCancel').click()
    print('Round2: notification target and popup bounds, no global refresh, Settings wallpaper canvas, Japanese authentication, primary submit and right-top closes passed.')


def check_initial_discovery(page,base,fixture):
    page.add_init_script("""
      Math.random=()=>Number(sessionStorage.getItem('fixture-random')||'0');
      const readyTimer=setInterval(()=>{
        if(globalThis.YGCCloudUIReady===true){document.documentElement.dataset.fixtureReady='true';clearInterval(readyTimer)}
      },10);
    """)
    page.goto(base+'/ui');expect(page.locator('html')).to_have_attribute('data-fixture-ready','true')
    expect(page.locator('#detailTitle')).to_contain_text('Fixture 30');assert page.url==base+'/ui'
    page.evaluate("sessionStorage.setItem('fixture-random','0.999')")
    page.reload();expect(page.locator('html')).to_have_attribute('data-fixture-ready','true')
    expect(page.locator('#detailTitle')).to_contain_text('Fixture 1');assert page.url==base+'/ui'
    page.locator('#insightsRefresh').click();expect(page.locator('#detailTitle')).to_contain_text('Fixture 1')
    page.goto(base+'/ui/guitars/2');expect(page.locator('html')).to_have_attribute('data-fixture-ready','true')
    expect(page.locator('#detailTitle')).to_contain_text('Fixture 2');assert page.url.endswith('/ui/guitars/2')
    fixture.insights_case='empty'
    page.goto(base+'/ui');expect(page.locator('html')).to_have_attribute('data-fixture-ready','true')
    expect(page.locator('#detailContent')).not_to_be_visible()
    fixture.insights_case='normal';fixture.mode='offline'
    page.goto(base+'/ui');expect(page.locator('html')).to_have_attribute('data-fixture-ready','true')
    expect(page.locator('#detailContent')).not_to_be_visible()
    fixture.mode='normal'
    print('Top random discovery: different draws on reload at /ui, refresh retention, explicit URL, empty/restricted data passed.')


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
                check_initial_discovery(page,base,fixture)
                page.goto(base+'/ui');expect(page.locator('#catalogRows tr')).to_have_count(30)
                expect(page.locator('#shellIdentity')).to_contain_text('Explore guitar histories')
                assert not any('/api/auth/favorites/' in path for _,path in fixture.calls)
                list_height=page.locator('#catalogList').bounding_box()['height']
                page.locator('#catalogSearch').fill('Fender');page.locator('#catalogSearch').press('Enter')
                expect(page.locator('#catalogRows tr')).to_have_count(15)
                assert abs(page.locator('#catalogList').bounding_box()['height']-list_height)<1
                page.locator('#catalogRows a').first.click();expect(page.locator('#detailContent')).to_be_visible()
                assert '/ui/guitars/' in page.url and 'q=Fender' in page.url
                expect(page.locator('header [data-language-picker]')).to_have_count(1)
                expect(page.locator('#detail .detail-image')).to_be_visible()
                assert page.locator('#detailPhoto').evaluate('(img) => img.complete && img.naturalWidth > 0')
                expect(page.locator('#specificationAccordion .accordion-toggle')).to_be_visible()
                page.locator('#specificationAccordion .accordion-toggle').click()
                expect(page.locator('#specificationAccordion .accordion-body')).not_to_be_visible()
                page.locator('#specificationAccordion .accordion-title').click()
                expect(page.locator('#specificationAccordion .accordion-body')).to_be_visible()
                assert page.locator('#detailTitle').evaluate('(el) => getComputedStyle(el).fontSize')=='16px'
                selected=page.url;expect(page.locator('#acquireLink')).to_have_attribute('href','/ui/profile?acquire=29')
                page.go_back();expect(page.locator('#detailContent')).to_be_visible()
                page.go_forward();expect(page.locator('#detailContent')).to_be_visible()
                page.reload();expect(page.locator('#detailContent')).to_be_visible();assert page.url==selected
                # Live filtering includes Finish/Year and retains selected detail.
                page.locator('#catalogSearch').fill('Sunburst 1963')
                expect(page.locator('#catalogRows tr')).to_have_count(4)
                assert '/ui/guitars/29' in page.url
                expect(page.locator('#detailTitle')).to_contain_text('Fixture 29')
                page.locator('#catalogSearch').fill('Fender ')
                expect(page.locator('#catalogRows tr')).to_have_count(15)
                assert page.locator('#catalogSearch').input_value()=='Fender '
                page.locator('#catalogList th[data-sort-field="model"]').click()
                expect(page.locator('#catalogList th[data-sort-field="model"]')).to_have_attribute('aria-sort','ascending')
                page.locator('#catalogList th[data-sort-field="model"]').click()
                expect(page.locator('#catalogList th[data-sort-field="model"]')).to_have_attribute('aria-sort','descending')
                selected=page.url
                # Focus trap, Escape and credential disposal, with return to opener.
                page.locator('#shellSignIn').click();expect(page.locator('#authEmail')).to_be_focused()
                page.locator('#authEmail').fill('alice@example.invalid');page.locator('#authPassword').fill('discard-me')
                page.keyboard.press('Escape');expect(page.locator('#shellSignIn')).to_be_focused()
                assert page.locator('#authPassword').input_value()=='' and page.locator('#authEmail').input_value()==''
                page.locator('#shellSignIn').click();page.keyboard.press('Shift+Tab');expect(page.locator('#authCreateAccount')).to_be_focused()
                page.keyboard.press('Tab');expect(page.locator('#authEmail')).to_be_focused()
                page.locator('#authEmail').fill('alice@example.invalid');page.locator('#authPassword').fill('bad');page.locator('#authSubmit').click()
                expect(page.locator('#cloudAuthStatus')).to_contain_text('incorrect');assert page.locator('#authPassword').input_value()=='bad'
                page.evaluate("sessionStorage.setItem('verified-alice@example.invalid','true')")
                def check_login_wait(route):
                    assert page.locator('#authEmail').input_value()=='alice@example.invalid'
                    assert page.locator('#authPassword').input_value()=='fixture-password'
                    expect(page.locator('#cloudAuthDialog')).to_be_visible()
                    route.continue_()
                page.route(base+'/api/auth/me',check_login_wait,times=1)
                page.locator('#authEmail').fill('alice@example.invalid');page.locator('#authPassword').fill('fixture-password');page.locator('#authSubmit').click()
                expect(page.locator('#shellIdentity')).to_have_text('Alice');expect(page.locator('#cloudAuthDialog')).not_to_be_visible()
                expect(page.locator('#favoriteToggle')).to_be_visible()
                assert page.url==selected
                # Canonical identity changes clear private controls before Refresh.
                page.evaluate("sessionStorage.setItem('verified-bob@example.invalid','true'); favoritesFixtureSwitchUser('bob@example.invalid')")
                expect(page.locator('#shellIdentity')).not_to_have_text('Alice');expect(page.locator('#catalogRows tr')).to_have_count(0)
                expect(page.locator('#favoriteToggle')).not_to_be_visible()
                page.reload();expect(page.locator('#shellIdentity')).to_have_text('Bob')
                fixture.reject_identity=True;page.reload()
                expect(page.locator('#catalogRows tr')).to_have_count(0);expect(page.locator('#shellIdentity')).not_to_have_text('Bob')
                fixture.reject_identity=False;page.reload();expect(page.locator('#shellIdentity')).to_have_text('Bob')
                page.locator('#shellSignOut').click();expect(page.locator('#shellIdentity')).to_contain_text('Explore guitar histories')
                expect(page.locator('#accountHub .account-hub-user-link')).not_to_be_visible();expect(page.locator('#favoriteToggle')).not_to_be_visible()
                fixture.mode='offline';page.reload();expect(page.locator('#catalogRows tr')).to_have_count(0)
                expect(page.locator('#detailContent')).not_to_be_visible();expect(page.locator('#serviceNotice')).to_be_visible()
                fixture.mode='normal';page.reload();expect(page.locator('#detailContent')).to_be_visible()
                artifacts=Path(os.environ.get('YGC_BROWSER_ARTIFACTS','/tmp/ygc-formal-ui-artifacts'));artifacts.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(artifacts/'formal-ui-desktop.png'))
                page.set_viewport_size({'width':390,'height':844});page.locator('#catalogLanguage').select_option('ja')
                expect(page.locator('#shellTitle')).to_have_text('トップページ')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                box=page.locator('#productDetailShell').bounding_box();assert box['x']>=0 and box['x']+box['width']<=390
                page.screenshot(path=str(artifacts/'formal-ui-mobile.png'))
                page.keyboard.press('Escape');expect(page.locator('#productDetailShell')).not_to_be_visible();expect(page.locator('#listHeading')).to_be_focused()
                page.locator('#shellSignIn').click();page.keyboard.press('Escape');expect(page.locator('#cloudAuthDialog')).not_to_be_visible()
                page.set_viewport_size({'width':320,'height':640});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#catalogRows a').first.click();expect(page.locator('#detailContent')).to_be_visible()
                box=page.locator('#productDetailShell').bounding_box();assert box['x']>=0 and box['x']+box['width']<=320
                assert not errors,errors
                assert not any(method not in ('GET','HEAD') for method,path in fixture.calls),fixture.calls
                fixture.rows[0]['manufacturer']='<img src=x onerror=alert(1)>'
                page.goto(base+'/ui/guitars/1')
                expect(page.locator('#detailTitle')).to_contain_text('<img src=x onerror=alert(1)>')
                expect(page.locator('#detailTitle img')).to_have_count(0)
                expect(page.locator('#detailSpecifications img')).to_have_count(0)
                assert page.locator('#detailContent').evaluate('(root)=>new Set([...root.querySelectorAll("[id]")].map(e=>e.id)).size===root.querySelectorAll("[id]").length')
                fixture.rows[0]['manufacturer']='Fender'
                check_formal_headers(page,base)
                check_profile_lists(page,base,fixture)
                check_settings(page,base,fixture)
                check_favorite_sync(page,base,fixture)
                check_claim_forms(page,base,fixture)
                check_application_forms(page,base,fixture)
                check_claim_popup(page,base)
                check_formal_follow(page,base,fixture)
                check_notification_cards(page,base,fixture)
                check_ownership_entry(page,base,fixture)
                check_prepublication(page,base,fixture)
                check_round2(page,base,fixture)
                check_profile_bootstrap_timing(page,base,fixture)
                assert not errors,errors
                context.close();browser.close()
                print('Formal UI: routes/history, canonical auth/identity switch/revocation, credential disposal, modal focus, Offline, Japanese and 1440/390/320px passed; synthetic GETs and explicit Settings/Signature/Favorite test saves only.')
        finally:
            server.should_exit=True;thread.join(timeout=10)
            assert not thread.is_alive()

if __name__=='__main__':main()
