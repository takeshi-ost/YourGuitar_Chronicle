const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = {window: {}, document: {
  addEventListener() {}, createElement() { return {}; }, head: {append() {}},
}};
vm.runInNewContext(fs.readFileSync('app/src/ygc/static/product-detail.js', 'utf8'), context);
const detail = context.window.YGCProductDetail;
const options = {
  individual: {manufacturer: 'Fender', model: 'Stratocaster', serial_number: '123', year: '1960'},
  specifications: [{field_name: 'pickups', value_text: 'Single coil'}],
  image: '<img src="example">', owner: 'A', location: 'Japan',
  ownership: '<button>Claim</button>', titleAction: '<button>Favorite</button>',
  headerAction: '<button>Delete Individual</button>', chronicleAction: '<button>Add Claim</button>',
  fieldLabel: value => value, escape: value => String(value || ''),
};
const html = detail.render(options);
for (const text of ['Stratocaster', 'Current Owner:', 'Japan', 'Single coil',
  'Favorite', 'Delete Individual', 'specificationAccordion', 'chronicleEntries']) {
  assert.ok(html.includes(text), text);
}
assert.ok(html.indexOf('Chronicle</span>') < html.indexOf('Toggle Chronicle'));
assert.ok(html.indexOf('accordion-body"><button>Add Claim') < html.indexOf('chronicleEntries'));
assert.ok(html.indexOf('accordion-body"><button>Add Claim') > html.indexOf('Toggle Chronicle'));
assert.equal(detail.orderedClaims([
  {id: 1, claim_type: 'listing', occurred_at: '2026-01-01'},
  {id: 3, claim_type: 'identity_correction', target_claim_id: 1, occurred_at: '2026-02-01'},
  {id: 2, claim_type: 'ownership', occurred_at: '2026-02-01'},
]).map(c => c.id).join(','), '2,1,3');
assert.equal(detail.orderedClaims([
  {id: 4, occurred_at: '2026-01-01', created_at: '2026-09-01'},
  {id: 5, occurred_at: '2026-08-01', created_at: '2026-08-02'},
]).map(c => c.id).join(','), '5,4');
for (const page of ['index_html', 'user_view_html']) {
  const markup = require('./page_source.cjs')('app/src/ygc/static/' + page + '.html');
  assert.match(markup, /<script src="\/assets\/product-detail\.js\?v=shared-ui-v2" defer><\/script>/);
  assert.match(markup, /YGCProductDetail\.render\(/);
  assert.match(markup, /YGCProductDetail\.orderedClaims\(/);
  assert.match(markup, /#detail \.detail-image\{width:calc\(100% - 72px\);height:auto;aspect-ratio:4\/3;object-fit:contain\}/);
  assert.match(markup, /#detail \.detail-gallery\{width:100%;grid-template-columns:28px minmax\(0,1fr\) 28px;gap:8px\}/);
  for (const match of markup.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)) {
    if (match[1].trim()) new Function(match[1]);
  }
}
console.log('shared product detail: passed');
