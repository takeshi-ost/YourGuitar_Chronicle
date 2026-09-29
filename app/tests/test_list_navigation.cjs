const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const handlers = {};
let selected = null;
let scrolls = 0;
let selectionStyle = '';
let frames = [];
const flushFrames = () => {
  const callbacks = frames;
  frames = [];
  callbacks.forEach(callback => callback());
};
const classes = () => {
  const values = new Set();
  return {add: key => values.add(key), remove: key => values.delete(key),
    contains: key => values.has(key)};
};
class Element {
  constructor(root = null, index = -1, control = false) {
    this.root = root;
    this.index = index;
    this.control = control;
    this.classList = classes();
    this.isConnected = true;
  }
  closest(selector) {
    if (selector.includes('input') && !selector.includes('tr.clickable')) {
      return this.control ? this : null;
    }
    if (selector.includes('tr.clickable')) return this.index >= 0 ? this : null;
    if (selector.includes('#individualBody')) return this.root;
    return null;
  }
  matches(selector) { return this.control && selector.includes('input'); }
  click() {
    handlers.click({target: this});
    selected = this.index;
    // The application redraws the table when an item is selected.
    this.root.rows = [0, 1, 2].map(index => new Element(this.root, index));
  }
  scrollIntoView() { scrolls++; }
}
const root = new Element();
root.rows = [0, 1, 2].map(index => new Element(root, index));
root.querySelectorAll = selector => selector.includes('list-keyboard-current')
  ? root.rows.filter(row => row.classList.contains('list-keyboard-current'))
  : root.rows;
root.querySelector = () => root.rows.find(row => row.classList.contains('list-keyboard-current')) || null;
const body = new Element();
const document = {
  activeElement: body,
  documentElement: {classList: classes()},
  addEventListener: (event, callback) => { handlers[event] = callback; },
  querySelector: () => null,
  createElement: () => ({}),
  head: {append(style) { selectionStyle = style.textContent; }},
};
vm.runInNewContext(fs.readFileSync('app/src/ygc/static/list-navigation.js', 'utf8'),
  {document, Element, requestAnimationFrame: callback => frames.push(callback)});
const arrow = key => {
  let prevented = false;
  handlers.keydown({key, defaultPrevented: false, preventDefault: () => { prevented = true; }});
  flushFrames();
  return prevented;
};

assert.equal(arrow('ArrowDown'), false);
root.rows[0].click();
flushFrames();
assert.equal(root.rows[0].classList.contains('list-keyboard-current'), true);
assert.match(selectionStyle, /\.clickable\.selected, \.user-results tr\.selected, \.list-keyboard-current/);
assert.match(selectionStyle, /color-mix\(in srgb, var\(--text/);
assert.equal(arrow('ArrowDown'), true);
assert.equal(selected, 1);
assert.equal(root.rows[1].classList.contains('list-keyboard-current'), true);
assert.equal(document.documentElement.classList.contains('list-keyboard-hover-muted'), true);
assert.match(selectionStyle, /hover:not\(\.selected\):not\(\.list-keyboard-current\)/);
assert.match(selectionStyle, /notification-item\.unread:hover/);
assert.equal(arrow('ArrowDown'), true);
assert.equal(selected, 2);
handlers.mousemove();
assert.equal(document.documentElement.classList.contains('list-keyboard-hover-muted'), false);
assert.equal(root.rows[2].classList.contains('list-keyboard-current'), true);
assert.equal(scrolls, 2);
assert.equal(arrow('ArrowDown'), true);
assert.equal(selected, 2);
document.activeElement = new Element(null, -1, true);
assert.equal(arrow('ArrowUp'), false);
assert.equal(selected, 2);
document.activeElement = body;
handlers.click({target: body});
assert.equal(arrow('ArrowUp'), false);
assert.equal(root.rows[2].classList.contains('list-keyboard-current'), false);
console.log('list navigation: passed');
