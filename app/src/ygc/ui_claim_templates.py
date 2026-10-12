"""The formal transport reuses local Claim form markup without prototype handlers."""
from pathlib import Path
import re


def formal_page(filename):
    static = Path(__file__).with_name('static')
    local = (static / 'user_view_html.html').read_text(encoding='utf-8')
    forms = []
    for name in ('mediaClaimModal', 'eventClaimModal', 'incidentClaimModal', 'specClaimModal', 'ownershipClaimModal', 'ownershipConfirmModal', 'claimPopupModal'):
        start = local.index('<div class="modal-backdrop" id="' + name + '"')
        end = local.find('<div class="modal-backdrop"', start + 1)
        if end < 0:end = local.index('<script', start)
        fragment = local[start:end].strip()
        # Only trusted repository markup. No prototype URL or inline action runs.
        fragment = re.sub(r'\s+on[a-z]+="[^"]*"', '', fragment)
        forms.append(fragment)
    for name in ('transferReviewDialog','userConnectionsDialog'):
        start=local.index('<dialog id="'+name+'"')
        fragment=local[start:local.index('</dialog>',start)+9]
        forms.append(re.sub(r'\s+on[a-z]+="[^"]*"','',fragment))
    page = (static / filename).read_text(encoding='utf-8')
    return page.replace('</body>', '<template id="formalClaimTemplates">' + '\n'.join(forms) + '</template></body>')


def ownership_presentation_script():
    """Publish the local pure HTML formatters, without its API/action code."""
    source = (Path(__file__).with_name('static') / 'pages/user-view.js').read_text(encoding='utf-8')
    functions = [source[source.index('const acquireLabels='):source.index('\nfunction acquireStatusLabel')]]
    names = ('listingMetadataFields','ownershipEvidenceFields','ownershipChallengeBox','acquireStatusLabel','positionClaimPopup','displayEventDate','displayInputDate','specificationFieldLabel')
    for name in names:
        start = source.index('function '+name+'(')
        end = source.index('\nfunction ',start+1)
        functions.append(source[start:end])
    important=(Path(__file__).with_name('static')/'important-information.js').read_text(encoding='utf-8')
    functions.append(important[important.index('  function requestRow('):important.index('  async function refresh()')])
    functions.append('const safe=esc;')
    names=(*names,'requestRow')
    return "(()=>{const esc=value=>String(value??'').replace(/[&<>\\\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\\\"':'&quot;',\"'\":'&#39;'}[c]));\n"+'\n'.join(functions)+'\nglobalThis.YGCOwnershipPresentation={'+','.join(names)+'};})();'


def formal_members_page():
    """Reuse the local connections dialog, retaining the cloud controller IDs."""
    static=Path(__file__).with_name('static')
    local=(static/'user_view_html.html').read_text(encoding='utf-8')
    start=local.index('<dialog id="userConnectionsDialog"')
    fragment=local[start:local.index('</dialog>',start)+9]
    fragment=re.sub(r'\s+on[a-z]+="[^"]*"','',fragment)
    for old,new in [('userConnectionsDialog','memberConnections'),('userConnectionsTitle','memberConnectionsTitle'),('userConnectionsList','memberConnectionsList'),('userConnectionsStatus','memberConnectionsStatus'),('userConnectionsMore','memberMore')]:fragment=fragment.replace(old,new)
    fragment=fragment.replace('<button data-ui-action="close"','<button id="memberClose" data-ui-action="close"')
    page=(static/'cloud_ui_members_html.html').read_text(encoding='utf-8')
    return re.sub(r'<dialog id="memberConnections".*?</dialog>',lambda _:fragment,page,flags=re.S)
