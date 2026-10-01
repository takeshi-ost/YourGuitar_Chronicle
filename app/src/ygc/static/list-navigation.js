/* Navigate the last clicked list with Up / Down without hijacking form controls. */
(() => {
  'use strict';
  const listSelector = '#individualBody, #unverifiedAcquireBody, #userBody, '
    + '#newDiscoveryList, #notificationList, #userChronicleList, '
    + '[id^="profileRows-"], .user-guitar-list';
  const itemSelector = 'tr.clickable, .discovery-item, .notification-item, '
    + '.profile-chronicle-row.clickable, .user-guitar-row a';
  let active = null;
  let marked = null;
  let hoverMuted = false;

  function restoreHover() {
    document.documentElement.classList.remove('list-keyboard-hover-muted');
    hoverMuted = false;
  }

  function items(root) {
    return Array.from(root.querySelectorAll(itemSelector))
      .filter(item => item.closest(listSelector) === root);
  }

  function mark(root, item) {
    if (marked) marked.classList.remove('list-keyboard-current');
    item.classList.add('list-keyboard-current');
    marked = item;
  }

  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target : null;
    const item = target && target.closest(itemSelector);
    const root = item && item.closest(listSelector);
    if (!root || target.closest('input, select, textarea, button:not(.notification-item), [contenteditable="true"]')) {
      active = null;
      if (marked) marked.classList.remove('list-keyboard-current');
      marked = null;
      return;
    }
    const index = items(root).indexOf(item);
    active = index < 0 ? null : {root, index};
    if (active) {
      mark(root, item);
      requestAnimationFrame(() => {
        if (!active || active.root !== root || !root.isConnected) return;
        const updated = items(root)[active.index];
        if (updated) mark(root, updated);
      });
    }
  }, true);

  document.addEventListener('keydown', event => {
    if (!active || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') ||
        event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
        event.defaultPrevented || !active.root.isConnected ||
        (window.YGCOverlays?.isOpen() || document.querySelector('dialog[open], .modal-backdrop.open'))) return;
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
    if (!hoverMuted) {
      document.documentElement.classList.add('list-keyboard-hover-muted');
      document.addEventListener('mousemove', restoreHover, {once: true});
      hoverMuted = true;
    }
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
  style.textContent = `
    :is(.clickable.selected, .user-results tr.selected, .list-keyboard-current),
    :is(.clickable.selected, .user-results tr.selected, .list-keyboard-current):hover {
      background: color-mix(in srgb, var(--text, #edf0f3) 22%, var(--panel, #181b1f)) !important;
    }
    html.list-keyboard-hover-muted :is(tr.clickable, .discovery-item, .profile-chronicle-row.clickable):hover:not(.selected):not(.list-keyboard-current) {
      background: transparent !important;
    }
    html.list-keyboard-hover-muted .notification-item:hover:not(.list-keyboard-current) {
      background: var(--surface, #171a1e) !important;
    }
    html.list-keyboard-hover-muted .notification-item.unread:hover:not(.list-keyboard-current) {
      background: var(--control, #1d211e) !important;
    }
  `;
  document.head.append(style);
})();
