"""Read-only UI regression on a disposable running app with user/guitar ID 1.

Run explicitly with Playwright installed. YGC_BROWSER_URL and
YGC_BROWSER_EXECUTABLE can override the server and Chromium executable.
"""
import os

from playwright.sync_api import sync_playwright, expect


def main():
    base = os.environ.get('YGC_BROWSER_URL', 'http://127.0.0.1:18765')
    executable = os.environ.get('YGC_BROWSER_EXECUTABLE')
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/users/1?prototype_user_id=1&individual_id=1')
        expect(page.locator('#detail')).to_contain_text('Current Owner')
        page.locator('#newGuitarAction').click()
        expect(page.locator('#guitarMaker')).to_be_focused()
        assert page.evaluate('document.body.style.overflow') == 'hidden'
        page.keyboard.press('Shift+Tab')
        assert page.evaluate("document.activeElement.closest('#acquireReviewModal') !== null")
        page.keyboard.press('Tab')
        expect(page.locator('#guitarMaker')).to_be_focused()
        # Even a programmatic background focus cannot escape the modal.
        page.evaluate("document.getElementById('newGuitarAction').focus()")
        assert page.evaluate("document.activeElement.closest('#acquireReviewModal') !== null")
        page.evaluate("YGCOverlays.open('eventClaimModal')")
        page.keyboard.press('Escape')
        expect(page.locator('#eventClaimModal')).not_to_be_visible()
        expect(page.locator('#acquireReviewModal')).to_be_visible()
        assert page.evaluate('document.body.style.overflow') == 'hidden'
        page.keyboard.press('Escape')
        expect(page.locator('#acquireReviewModal')).not_to_be_visible()
        expect(page.locator('#newGuitarAction')).to_be_focused()
        assert page.evaluate('document.body.style.overflow') == ''
        # All feature overlays use the same lifecycle, without submitting data.
        for modal in ['mediaClaimModal', 'eventClaimModal', 'incidentClaimModal',
                      'specClaimModal', 'formerOwnerClaimModal', 'ownershipClaimModal',
                      'accountRequiredModal', 'claimPopupModal']:
            page.evaluate('(id) => YGCOverlays.open(id)', modal)
            expect(page.locator('#' + modal)).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#' + modal)).not_to_be_visible()
            assert page.evaluate('document.body.style.overflow') == ''
        page.set_viewport_size({'width': 390, 'height': 844})
        page.evaluate('openCompactDetail()')
        page.locator('#detail .detail-image').click()
        expect(page.locator('.ygc-album-panel')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('.ygc-album-panel')).to_have_count(0)
        expect(page.locator('#detail .detail-gallery')).to_be_focused()
        assert page.locator('#productDetailShell').evaluate("el => el.classList.contains('compact-open')")
        page.keyboard.press('Escape')
        assert not page.locator('#productDetailShell').evaluate("el => el.classList.contains('compact-open')")
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.goto(base + '/')
        # Initial user loading may redraw an already selected Product Detail.
        # Start the focus lifecycle check after those requests have completed.
        page.wait_for_load_state('networkidle')
        page.locator('#individualBody tr.clickable').first.click()
        button = page.get_by_role('button', name='Observation decision', exact=True)
        button.click()
        expect(page.locator('#observationDiagnosticDialog')).to_be_visible()
        assert page.evaluate('document.body.style.overflow') == 'hidden'
        page.keyboard.press('Escape')
        expect(page.locator('#observationDiagnosticDialog')).not_to_be_visible()
        expect(button).to_be_focused()
        assert page.evaluate('document.body.style.overflow') == ''
        button.click()
        page.locator('#observationDiagnosticDialog').get_by_role('button', name='Close', exact=True).click()
        expect(button).to_be_focused()
        button.click()
        page.mouse.click(2, 2)
        expect(page.locator('#observationDiagnosticDialog')).not_to_be_visible()
        assert not errors, errors
        browser.close()
    print('Shared overlays: focus, Tab, nesting, Escape, scroll restoration, mobile album, native dialog passed')


if __name__ == '__main__':
    main()
