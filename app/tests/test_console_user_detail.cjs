const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('app/src/ygc/static/index_html.html', 'utf8');
assert.doesNotMatch(html, /id="activeUserSelect"/);
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]).find(text => text.includes('let selectedUserId=null'))
  .split('const header=document.querySelector')[0]
  .replace('const CONSOLE_ADMIN_TOKEN="";', 'const CONSOLE_ADMIN_TOKEN="admin";');

const elements = Object.fromEntries(['userBody', 'userCount', 'accountPanel',
  'openUserTopBtn', 'userFilter'].map(id => [id, {innerHTML: '', textContent: '',
  disabled: false, value: '', className: ''}]));
const storage = new Map();
const sessionStorage = {getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)};
const opened = [];
const users = [
  {id: 1, display_name: 'Alice', account_type: 'shop', ban_status: 'normal'},
  {id: 2, display_name: 'Bob', account_type: 'user', ban_status: 'ban'},
];
const fetch = async url => {
  let data;
  if(url === '/api/users') data = users;
  else if(url === '/api/themes') data = [];
  else if(url.startsWith('/api/users/')) {
    const user = users.find(row => row.id === Number(url.split('/')[3]));
    data = {user, summary: {}, guitars: []};
  } else throw new Error('Unexpected request: ' + url);
  return {ok: true, json: async () => data};
};
const context = vm.createContext({sessionStorage, localStorage: {getItem: () => null,
  removeItem() {}}, document: {getElementById: id => elements[id]},
  window: {open: (...args) => opened.push(args)}, fetch, Headers,
  URLSearchParams});
vm.runInContext(script, context);
(async () => {
  await vm.runInContext('loadUsers()', context);
  assert.equal(elements.openUserTopBtn.disabled, true);
  await vm.runInContext('showUserRecord(1)', context);
  assert.equal(storage.get('ygc_active_user_id'), '1');
  assert.match(elements.accountPanel.innerHTML, /user-header-text.*Alice.*Account Type: shop.*BAN Status: normal/);
  assert.equal(elements.openUserTopBtn.disabled, false);
  vm.runInContext('openTopPageAsActiveUser()', context);
  assert.equal(opened[0][0], '/user-view?prototype_user_id=1');
  vm.runInContext('openTopPageAsGuest()', context);
  assert.equal(opened[1][0], '/user-view?prototype_user_id=');
  await vm.runInContext('showUserRecord(2)', context);
  assert.equal(elements.openUserTopBtn.disabled, true);
  assert.equal(storage.has('ygc_active_user_id'), false);
  vm.runInContext('openTopPageAsActiveUser()', context);
  assert.equal(opened.length, 2);
  console.log('console user detail: passed');
})().catch(error => {console.error(error);process.exitCode = 1});
