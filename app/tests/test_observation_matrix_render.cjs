const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const page = fs.readFileSync('app/src/ygc/static/index_html.html', 'utf8');
const start = page.indexOf('function renderObservationMatrix(d){');
const end = page.indexOf('async function openObservationDiagnostic(){', start);
assert.ok(start > 0 && end > start);
const context = vm.createContext({esc: value => String(value).replaceAll('<', '&lt;')});
vm.runInContext(page.slice(start, end), context);
const html = vm.runInContext('renderObservationMatrix', context)({
  individual_id: 17,
  differences: {},
  matrix: {
    columns: [{key: 'manufacturer', group: 'individual'},
      {key: 'current_owner_name', group: 'individual'},
      {key: 'spec:pickups', group: 'specification'}],
    rows: [
      {claim_id: 1, type: 'listing', occurred_at: '2026-09-20',
        status: 'active', verification_status: 'positive', author_name: 'Automation',
        cells: {manufacturer: {value: 'Gibson', adopted: true},
          current_owner_name: {value: 'Shop', adopted: false}}},
      {claim_id: 2, type: 'specification', occurred_at: '2026-09-21',
        status: 'active', verification_status: 'unverified', author_name: 'User',
        cells: {'spec:pickups': {value: '<unsafe>', adopted: false}}},
    ],
    current: {manufacturer: 'Gibson', current_owner_name: 'Unknown',
      'spec:pickups': null},
  },
});
assert.ok(html.indexOf('#1 · listing') < html.indexOf('#2 · specification'));
assert.match(html, /matrix-adopted[^>]*><span class="matrix-cell-value">Gibson/);
assert.match(html, /matrix-rejected[^>]*><span class="matrix-cell-value">Shop/);
assert.match(html, /matrix-unrelated">—/);
assert.match(html, /&lt;unsafe>/);
assert.match(html, /Current Guitar Individual/);
assert.match(html, /Specification/);
assert.match(html, /<tfoot>[\s\S]*空欄/);
assert.match(html, /style="width:278px"/);
assert.equal((html.match(/<col class="matrix-value-col">/g) || []).length, 3);
assert.ok(html.indexOf('</tbody>') < html.indexOf('<tfoot>'));
assert.match(page, /\.observation-matrix tfoot td\{position:static;bottom:auto/);
console.log('observation matrix rendering: passed');
