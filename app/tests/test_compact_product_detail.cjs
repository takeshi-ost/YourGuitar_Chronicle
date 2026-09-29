const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('app/src/ygc/static/user_view_html.html', 'utf8');
const start = html.indexOf('function closeCompactDetail(){');
const end = html.indexOf('async function showIndividual(', start);
assert.ok(start > 0 && end > start);

const classes = new Set(), listeners = {};
let compact = true;
const shell = {classList: {
  add: name => classes.add(name), remove: name => classes.delete(name),
  contains: name => classes.has(name),
}, contains: target => target === shell};
class Element { closest() { return null; } }
const document = {
  getElementById: () => shell,
  addEventListener: (name, listener) => { listeners[name] = listener; },
  querySelector: () => null,
};
const window = {
  matchMedia: () => ({matches: compact}),
  addEventListener: (name, listener) => { listeners[name] = listener; },
};
const context = vm.createContext({window, document, Element});
vm.runInContext(html.slice(start, end), context);
vm.runInContext('openCompactDetail()', context);
assert.equal(classes.has('compact-open'), true);
listeners.pointerdown({target: shell});
assert.equal(classes.has('compact-open'), true);
listeners.pointerdown({target: new Element()});
assert.equal(classes.has('compact-open'), false);
vm.runInContext('openCompactDetail()', context);
listeners.keydown({key: 'Escape'});
assert.equal(classes.has('compact-open'), false);
compact = false;
vm.runInContext('openCompactDetail()', context);
assert.equal(classes.has('compact-open'), false);
assert.match(html, /\.detail-shell\.compact-open\{display:block\}/);
assert.match(html, /width:min\(320px,calc\(100vw - 28px\)\)/);
assert.match(html, /height:min\(720px,calc\(100dvh - var\(--header-height,108px\) - 28px\)\)/);
assert.match(html, /onclick="showIndividual\('\+x\.id\+',true\)"/);
assert.match(html, /onclick="showIndividual\('\+Number\(g\.individual_id\)\+',true\)"/);
console.log('compact product detail: passed');
