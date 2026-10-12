"""Focused private Claim actions: local fixture only; no upload or cloud DB."""
import os,socket,threading,sys
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from formal_ui_fixture import FormalUIFixture

def main():
 fixture=FormalUIFixture();fixture.detail_actions=True
 base_claim=dict(individual_id='1',claim_type='specification',specification_kind='specification',ownership_kind=None,incident_kind=None,event_kind=None,status='active',verification_status='positive',revision='a'*64,body='Synthetic private detail',occurred_at='2026-01-01',created_at='2026-01-01T12:00:00Z',updated_at='2026-01-01',spec_items=[{'field_name':'nut','value_text':'Bone'}],media_items=[],author_name='Bob',decline_reason_required=False)
 fixture.owner_rows=[dict(base_claim,id='901'),dict(base_claim,id='902',claim_type='media',verification_status='unverified',specification_kind=None,spec_items=[],media_items=[dict(id='71',mime_type='image/jpeg',width=64,height=64)])]
 fixture.own_claims[(1,'1')]=[dict(base_claim,id='1001',verification_status='unverified',author_name='Alice')]
 output=Path('docs/development/fidelity-evidence');output.mkdir(exist_ok=True)
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1]);server=uvicorn.Server(uvicorn.Config(fixture.app(),log_level='error',lifespan='off'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.environ.get('YGC_BROWSER_EXECUTABLE'));context=browser.new_context(viewport={'width':1440,'height':1000});context.route('https://**/*',lambda r:r.abort());page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+'/ui/profile/guitars/1');page.evaluate("sessionStorage.setItem('fixture-sdk-email','alice@example.invalid');sessionStorage.setItem('verified-alice@example.invalid','true')");page.reload()
    if '--top' in sys.argv:
     page.goto(base+'/ui/guitars/1');select=page.locator('[data-claim-id="901"] .claim-response-select');expect(select).to_be_enabled();select.select_option('negative');expect(page.locator('[data-claim-id="901"] .claim-negative-dot')).to_be_visible()
     page.locator('[data-claim-id="1001"] .claim-compact-tag').click();expect(page.locator('#claimPopupModal [data-private-claim-action="edit"]')).to_be_enabled();page.locator('#claimPopupModal [data-private-claim-action="edit"]').click();expect(page.locator('#claimBody')).to_have_value('Synthetic private detail');page.locator('#claimBody').fill('Top Page edit');page.locator('#claimSave').click();expect(page.locator('#claimDialog')).not_to_be_visible();assert fixture.writes[-1][0]=='claim_edit';assert not errors,errors;context.close();browser.close();print('PASS: Top Page reuses the same per-Claim owner decision and own editor with synthetic save.');return
    verify=page.locator('[data-claim-id="901"] .claim-response-select');expect(verify).to_be_enabled();expect(page.locator('#formalOwnershipActions')).to_have_count(0);expect(page.locator('#selfClaims')).not_to_be_visible()
    # The decision uses a fresh private revision, not the cached card metadata.
    fixture.owner_rows[0]['revision']='d'*64
    widths_before=page.locator('td.favorite-cell').evaluate_all('(cells)=>cells.map(e=>e.getBoundingClientRect().width)')
    verify.select_option('negative');expect(page.locator('[data-claim-id="901"] .claim-negative-dot')).to_be_visible()
    centers=page.locator('#chronicleEntries').evaluate('''(root)=>{const center=e=>{const r=e.getBoundingClientRect();return r.x+r.width/2};return [center(root.querySelector('.claim-card')),center(root.querySelector('.claim-negative-dot'))]}''')
    assert abs(centers[0]-centers[1])<1,centers
    assert page.locator('td.favorite-cell').evaluate_all('(cells)=>cells.map(e=>e.getBoundingClientRect().width)')==widths_before
    assert page.locator('td.favorite-cell .favorite-status-compact').evaluate_all('(items)=>items.every(e=>e.getBoundingClientRect().width<=1)')
    assert fixture.writes[-1][2]=={'stance':'negative','revision':'d'*64},fixture.writes
    page.locator('[data-claim-id="901"] button').click();expect(page.locator('#claimPopupModal .claim-response-select')).to_be_enabled();page.locator('#claimPopupModal .claim-response-select').select_option('positive');expect(verify).to_have_value('positive')
    for width in (1440,390):
     page.set_viewport_size({'width':width,'height':900});page.goto(base+'/ui/profile/guitars/1');expect(verify).to_be_enabled()
     page.screenshot(path=str(output/f'unit15-claim-actions-{width}.png'),full_page=True)
     page.locator('[data-claim-id="1001"] .claim-compact-tag').click();expect(page.locator('#claimPopupModal [data-private-claim-action="edit"]')).to_be_enabled();expect(page.locator('#claimPopupModal .claim-response-select')).to_have_count(0)
     page.locator('#claimPopupModal [data-private-claim-action="edit"]').click();expect(page.locator('#claimDialog')).to_be_visible();expect(page.locator('#claimBody')).to_have_value('Synthetic private detail' if width==1440 else 'Edited from Claim card')
     assert page.locator('#claimDialog .modal').evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth}')
     if width==1440:page.locator('#claimBody').fill('Edited from Claim card');page.locator('#claimSave').click();expect(page.locator('#claimDialog')).not_to_be_visible()
     else:page.keyboard.press('Escape')
     expect(verify).to_be_enabled()
     before=len(fixture.writes);page.locator('[data-claim-id="902"] .claim-compact-tag').click();expect(page.locator('#claimPopupModal .claim-response-select')).to_be_enabled();page.locator('#claimPopupModal .claim-response-select').select_option('positive');expect(page.locator('#ownerResponseDialog')).to_be_visible();expect(page.locator('#ownerResponseDialog select')).to_be_disabled();expect(page.locator('[data-owner-media-view]')).to_be_enabled();assert len(fixture.writes)==before
     page.keyboard.press('Escape');expect(page.locator('#ownerResponseDialog')).not_to_be_visible()
    fixture.mode='read_only';page.reload();expect(verify).to_be_disabled();assert len([w for w in fixture.writes if w[0]=='owner_response'])==2;assert len([w for w in fixture.writes if w[0]=='claim_edit'])==1
    fixture.mode='normal';page.evaluate("sessionStorage.setItem('fixture-sdk-email','bob@example.invalid');sessionStorage.setItem('verified-bob@example.invalid','true')");page.reload();expect(page.locator('.profile-name')).to_have_text('Bob');expect(page.locator('#chronicleEntries .claim-response-select')).to_have_count(0);page.locator('[data-claim-id="1001"] .claim-compact-tag').click();expect(page.locator('#claimPopupModal [data-private-claim-action]')).to_have_count(0)
    assert not errors,errors;context.close();browser.close();print('PASS: per-Claim owner select/fresh CAS; own Claim edit/save; no own verification; media read gate; read-only; identity switch; PC/390 screenshots. No uploads.')
  finally:server.should_exit=True;thread.join(10);assert not thread.is_alive()
if __name__=='__main__':main()
