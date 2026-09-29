const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

const html = fs.readFileSync('app/src/ygc/static/user_view_html.html', 'utf8');
function source(name) {
  const start = html.indexOf('async function ' + name + '(');
  assert.ok(start >= 0, name);
  return html.slice(start, html.indexOf('\n}', start) + 2);
}

function scenario(profileId, fail = false) {
  const calls = [];
  const elements = Object.fromEntries(Object.entries({
    eventClaimDetail: 'New performance', eventClaimKind: 'performance',
    eventClaimDate: '2026-09-29', eventClaimImages: '', eventClaimSubmit: '',
    ownershipClaimKind: 'release', ownershipClaimDate: '2026-09-29',
    ownershipClaimPrevious: '', ownershipClaimBody: '', ownershipClaimSubmit: '',
  }).map(([key, value]) => [key, {value, files: [], disabled: false}]));
  const context = vm.createContext({
    PROFILE_USER_ID: profileId, activeUser: {user: {id: 2}},
    selectedIndividualId: 7, pendingOwnershipClaimIndividualId: 7,
    individuals: [], document: {getElementById: id => elements[id]},
    confirm: () => true, alert: message => calls.push(['alert', message]),
    jfetch: async url => {
      calls.push(['write', url]);
      if (fail) throw new Error('Save failed');
      return {user: {id: 2}, guitars: []};
    },
    loadActiveUser: async () => { calls.push(['account']); },
    loadProfilePage: async id => { calls.push(['profile', profileId, id]); },
    showIndividual: async id => { calls.push(['detail', id]); },
    closeEventClaim() {},
    closeOwnershipClaim() { context.pendingOwnershipClaimIndividualId = null; },
  });
  for (const name of ['refreshClaimViews', 'submitEventClaim', 'submitOwnershipClaim',
                       'setClaimResponse', 'voteClaim']) {
    vm.runInContext(source(name), context);
  }
  context.closeClaimPopup = () => {};
  return {calls, elements, run: expression => vm.runInContext(expression, context)};
}

test('Event submission refreshes the displayed profile, retaining its selected guitar', async () => {
  // The viewer (2) and displayed profile (1) need not be the same user.
  const s = scenario(1);
  await s.run('submitEventClaim()');
  assert.deepEqual(s.calls, [['write', '/api/individuals/7/event-claim'],
    ['account'], ['profile', 1, 7]]);
  assert.equal(s.elements.eventClaimSubmit.disabled, false);
});

test('Top Page submission refreshes detail without loading a profile', async () => {
  const s = scenario(0);
  await s.run('submitEventClaim()');
  assert.deepEqual(s.calls, [['write', '/api/individuals/7/event-claim'], ['detail', 7]]);
});

test('Release refreshes ownership lists while retaining the released guitar selection', async () => {
  const s = scenario(2);
  await s.run('submitOwnershipClaim()');
  assert.deepEqual(s.calls, [['write', '/api/individuals/7/ownership-claim'],
    ['account'], ['profile', 2, 7]]);
});

test('Verification and voting refresh profile activity as well as the selected guitar', async () => {
  for (const action of ['setClaimResponse(10,"positive")', 'voteClaim(10,"good")']) {
    const s = scenario(1);
    await s.run(action);
    assert.deepEqual(s.calls.slice(1), [['account'], ['profile', 1, 7]]);
  }
});

test('Failed submission reports the error and reenables the form without refreshing', async () => {
  const s = scenario(1, true);
  await s.run('submitEventClaim()');
  assert.deepEqual(s.calls.map(call => call[0]), ['write', 'alert']);
  assert.equal(s.elements.eventClaimSubmit.disabled, false);
});
