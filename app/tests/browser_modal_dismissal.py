"""Read-only backdrop checks against a disposable server (run explicitly)."""
import os
from browser_diagnostics import diagnostic_page
from playwright.sync_api import sync_playwright, expect


def main():
    base = os.environ.get('YGC_BROWSER_URL', 'http://127.0.0.1:18765')
    executable = os.environ.get('YGC_BROWSER_EXECUTABLE')
    errors = []
    checked = 0
    with sync_playwright() as p, diagnostic_page(p, 'browser_modal_dismissal') as page:
        page.on('pageerror', lambda error: errors.append(str(error)))
        for path in ('/user-view', '/'):
            page.goto(base + path)
            page.wait_for_function('window.YGCOverlays && window.YGCPageReady')
            page.evaluate('async () => await window.YGCPageReady')
            ids = page.evaluate('''() => Array.from(document.querySelectorAll('.modal-backdrop[id], dialog[id]')).map(el => el.id)''')
            assert ids
            for modal in ids:
                # Use the shared lifecycle without invoking a write or submitting a form.
                page.evaluate('''id => {
                    window.dismissalCloseCount = 0;
                    YGCOverlays.open(id, {onClose: () => window.dismissalCloseCount++});
                    const root = document.getElementById(id);
                    const panel = root.tagName === 'DIALOG' ? root : root.querySelector('[role="dialog"],.modal') || root.firstElementChild || root;
                    const rect = panel.getBoundingClientRect();
                    panel.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:rect.left+4, clientY:rect.top+4}));
                }''', modal)
                assert page.evaluate('YGCOverlays.isOpen()'), modal
                page.mouse.click(2, 2)
                expect(page.locator('#' + modal)).not_to_be_visible()
                assert page.evaluate('window.dismissalCloseCount') == 1
                assert page.evaluate('document.body.style.overflow') == ''
                checked += 1
        page.goto(base + '/user-view')
        page.evaluate('async () => await window.YGCPageReady')
        # Exercise actual Dispute Details rendering, not just an empty shell.
        page.route('**/api/ownership-disputes/987**', lambda route: route.fulfill(json={
            'id':987, 'status':'open', 'claims':[{'claim_id':1, 'applicant_name':'Applicant'}],
            'current_owner_name':'Owner', 'round':None, 'events':[], 'evidence':[]
        }))
        page.evaluate('async () => await YGCDisputes.open(987)')
        expect(page.locator('#disputeTitle')).to_contain_text('Dispute Details')
        page.locator('#disputeTitle').click()
        expect(page.locator('#disputeModal')).to_be_visible()
        page.mouse.click(2, 2)
        expect(page.locator('#disputeModal')).not_to_be_visible()
        assert page.evaluate('document.body.style.overflow') == ''
        page.evaluate("YGCOverlays.open('accountRegistrationModal'); YGCOverlays.open('registrationPolicyModal')")
        page.mouse.click(2, 2)
        expect(page.locator('#accountRegistrationModal')).to_be_visible()
        expect(page.locator('#registrationPolicyModal')).not_to_be_visible()
        assert page.evaluate('document.body.style.overflow') == 'hidden'
        page.mouse.click(2, 2)
        assert page.evaluate('document.body.style.overflow') == ''
        # Dismissing a confirmation resolves its pending action as cancellation.
        page.evaluate("() => { window.confirmationResult = null; confirmOwnershipAction('Test', 'Test').then(value => window.confirmationResult = value); }")
        page.mouse.click(2, 2)
        page.wait_for_function('window.confirmationResult === false')
        assert not errors, errors
    print(f'{checked} modal backdrops: inside clicks, outside dismissal, cleanup, nesting and confirmation cancellation passed')


if __name__ == '__main__':
    main()
