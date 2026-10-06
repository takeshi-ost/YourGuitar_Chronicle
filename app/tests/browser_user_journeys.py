"""Real UI journeys on the disposable server; only GPT observations are simulated."""
import os
from playwright.sync_api import sync_playwright, expect
from browser_diagnostics import diagnostic_page
from authentication_fixtures import image_bytes, transcription, comparison
from ygc import acquire_review


def ready(page, url):
    page.goto(url)
    settled(page)


def settled(page):
    page.wait_for_function('window.YGCPageReady')
    page.evaluate('async () => await window.YGCPageReady')


def confirm(page):
    page.locator('#ownershipConfirmSubmit').click()
    expect(page.locator('#ownershipConfirmModal')).not_to_be_visible()


def upload(page):
    picture = {'name': 'test.png', 'mimeType': 'image/png', 'buffer': image_bytes()}
    page.locator('#acquireCloseup').set_input_files(picture)
    page.locator('#acquireOverview').set_input_files(picture)
    page.locator('#acquireSubmit').click()
    confirm(page)
    expect(page.locator('#acquireReviewTitle')).to_contain_text('Awaiting review')
    page.wait_for_function('!acquireBusy')


def reviewed(repository, kind):
    job = acquire_review.call_tool(repository, 'ygc_pending_'+kind, {})['jobs'][0]
    with repository.connect() as con:
        row = acquire_review.find(con, job['revision'])
    keys = {key: job[key] for key in ('revision', 'lease_token')}
    acquire_review.call_tool(repository, 'ygc_'+kind+'_product_details', {
        **keys, 'observations': {k: 'Test fixture: image observation unavailable' for k in ('maker', 'model', 'finish')}})
    acquire_review.call_tool(repository, 'ygc_submit_'+kind+'_review', {
        **keys, 'closeup': transcription(row['serial'], row['challenge']),
        'overview': transcription(None, row['challenge']),
        'identity': comparison()['identity'] if job.get('reference_available') else None,
        'product_consistency': {k: {'status': 'uncertain', 'note': 'Test fixture: no contradiction'} for k in ('maker', 'model', 'finish')}})
    with repository.connect() as con:
        return dict(acquire_review.find(con, job['revision']))


def sign_out(page):
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator('#accountHub button[onclick="logoutUser(this)"]').click()
    expect(page.locator('#accountHub button[onclick="openAccountSignIn()"]')).to_be_visible()
    settled(page)


def sign_in(page, user_id):
    page.locator('#accountHub button[onclick="openAccountSignIn()"]').click()
    page.locator('#signInUser').select_option(str(user_id))
    page.locator('#signInEmail').fill('discarded@example.invalid')
    page.locator('#signInPassword').fill('not-a-real-secret')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#accountSignInSubmit').click()
    expect(page.locator('#accountHub button[onclick="logoutUser(this)"]')).to_be_visible()
    settled(page)


def main(repository):
    base = os.environ['YGC_BROWSER_URL']
    with sync_playwright() as p, diagnostic_page(p, 'user-journeys') as page:
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        sent = []
        page.on('request', lambda request: sent.append(request.post_data_buffer or b''))
        ready(page, base+'/user-view')
        # A language selection must change actual rendered labels and survive reload.
        page.locator('[data-language-picker]').select_option('ja')
        expect(page.locator('html')).to_have_attribute('lang', 'ja')
        expect(page.locator('body')).to_contain_text('見つかったすべてのギター')
        page.reload()
        expect(page.locator('html')).to_have_attribute('lang', 'ja')
        page.locator('[data-language-picker]').select_option('en')
        expect(page.locator('html')).to_have_attribute('lang', 'en')
        page.locator('#accountHub button[onclick="openAccountRegistration()"]').click()
        page.locator('#registrationEmail').fill('discarded@example.invalid')
        page.locator('#registrationPassword').fill('not-a-real-secret')
        page.locator('#registrationDisplayName').fill('Journey Applicant')
        page.locator('#registrationAccountType').select_option('shop')
        page.locator('#registrationTerms').check()
        page.locator('#registrationPrivacy').check()
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('#accountRegistrationSubmit').click()
        expect(page.locator('#accountHub button[onclick="logoutUser(this)"]')).to_be_visible()
        settled(page)
        with repository.connect() as con:
            user = con.execute("SELECT id FROM users WHERE display_name='Journey Applicant'").fetchone()[0]
            assert con.execute('SELECT COUNT(*) FROM accounts.account_consents WHERE app_user_id=(SELECT app_user_id FROM users WHERE id=?)', (user,)).fetchone()[0] == 2
        sign_out(page)
        sign_in(page, user)
        assert all(b'discarded@example.invalid' not in body and b'not-a-real-secret' not in body for body in sent)
        # Listing: submit through the real form, apply simulated GPT observations.
        ready(page, base+'/users/'+str(user))
        page.locator('#newGuitarAction').click()
        page.locator('#guitarMaker').fill('Fender')
        page.locator('#guitarModel').fill('Journey Guitar')
        page.locator('#guitarSerial').fill('JOURNEY002')
        page.locator('#guitarSubmit').click()
        confirm(page)
        expect(page.locator('#acquireCloseup')).to_be_enabled()
        upload(page)
        listing = reviewed(repository, 'listing')
        assert listing['status'] == 'accepted'
        ready(page, base+'/users/'+str(user)+'?individual_id='+str(listing['individual_id']))
        expect(page.locator('#detail')).to_contain_text('Journey Guitar')
        with repository.connect() as con:
            assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?', (listing['individual_id'],)).fetchone()[0] == user
        # Acquire an existing user-owned guitar. Review must not bypass its owner.
        ready(page, base+'/user-view?individual_id=1')
        expect(page.locator('#detail')).to_contain_text('Browser Test')
        page.locator('.add-claim-action').click()
        page.locator('#addClaimMenu').get_by_role('button', name='Ownership', exact=True).click()
        confirm(page)
        expect(page.locator('#acquireCloseup')).to_be_enabled()
        page.locator('#acquireDate').fill('2026-02-01')
        upload(page)
        acquire = reviewed(repository, 'acquire')
        assert acquire['status'] == 'accepted'
        with repository.connect() as con:
            assert con.execute('SELECT verification_status FROM claims WHERE id=?', (acquire['claim_id'],)).fetchone()[0] == 'unverified'
            assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=1').fetchone()[0] == 1
        page.locator('#acquireReviewActions').get_by_role('button', name='OK', exact=True).click()
        expect(page.locator('#acquireReviewModal')).not_to_be_visible()
        sign_out(page)
        sign_in(page, 1)
        ready(page, base+'/user-view?individual_id=1')
        # The addressed request uses the existing owner response API via the UI.
        accept = page.locator('button[onclick*="answerOwnershipRequest('+str(acquire['claim_id'])+',"]').filter(has_text='Accept')
        accept.click()
        confirm(page)
        page.wait_for_function('(id) => activeUser && selectedIndividualId === 1 && currentClaims.some(c => c.id === id && c.verification_status === "positive")', arg=acquire['claim_id'])
        with repository.connect() as con:
            assert con.execute('SELECT current_owner_user_id FROM individuals WHERE id=1').fetchone()[0] == user
        expect(page.locator('#detail')).to_contain_text('Journey Applicant')
        assert not errors, errors
    print('User journeys: registration, credential discard, sign-in/out, Japanese, Listing and Acquire owner approval passed')
