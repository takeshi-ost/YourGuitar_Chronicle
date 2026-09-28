/* Navigate the last clicked list with Up / Down without hijacking form controls. */
(() => {
  'use strict';
  const listSelector = '#individualBody, #unverifiedAcquireBody, #userBody, '
    + '#newDiscoveryList, #notificationList, #userChronicleList, '
    + '[id^="profileRows-"], .user-guitar-list';
  const itemSelector = 'tr.clickable, .discovery-item, .notification-item, '
    + '.profile-chronicle-row.clickable, .user-guitar-row a';
  let active = null;

  function items(root) {
    return Array.from(root.querySelectorAll(itemSelector))
      .filter(item => item.closest(listSelector) === root);
  }

  function mark(root, item) {
    for (const old of root.querySelectorAll('.list-keyboard-current')) {
      old.classList.remove('list-keyboard-current');
    }
    item.classList.add('list-keyboard-current');
  }

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target : null;
    const item = target && target.closest(itemSelector);
    const root = item && item.closest(listSelector);
    if (!root || target.closest('input, select, textarea, button:not(.notification-item), [contenteditable="true"]')) {
      active = null;
      return;
    }
    const index = items(root).indexOf(item);
    active = index < 0 ? null : {root, index};
    if (active) mark(root, item);
  }, true);

  document.addEventListener('keydown', event => {
    if (!active || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
        event.defaultPrevented || !active.root.isConnected ||
        document.querySelector('dialog[open], .modal-backdrop.open')) return;
    const focused = document.activeElement;
    if (focused && focused.matches('input, select, textarea, [contenteditable="true"]')) return;
    if (focused && focused.matches('button') &&
        !focused.matches('.notification-item')) return;
    const list = items(active.root);
    if (!list.length) { active = null; return; }
    const selected = active.root.querySelector('.list-keyboard-current');
    const selectedIndex = list.indexOf(selected);
    const index = selectedIndex >= 0 ? selectedIndex : active.index;
    const next = Math.max(0, Math.min(list.length - 1,
      index + (event.key === 'ArrowDown' ? 1 : -1)));
    event.preventDefault();
    if (next === index) return;
    active.index = next;
    const item = list[next];
    mark(active.root, item);
    item.click();
    requestAnimationFrame(() => {
      if (!active || !active.root.isConnected) return;
      const updated = items(active.root)[active.index];
      if (updated) {
        mark(active.root, updated);
        updated.scrollIntoView({block: 'nearest'});
      }
    });
  });

  const style = document.createElement('style');
  style.textContent = '.list-keyboard-current{outline:2px solid var(--accent,#d0a45d);outline-offset:-2px}';
  document.head.append(style);
})();
