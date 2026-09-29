/* Shared lifecycle for custom overlays and native dialogs. Content and actions
   remain owned by each feature; Escape only closes the topmost overlay. */
window.YGCOverlays = (() => {
  const stack = [];
  let savedOverflow = '';
  const element = value => typeof value === 'string' ? document.getElementById(value) : value;
  const top = () => stack[stack.length - 1];
  function focusable(root) {
    return Array.from(root.querySelectorAll('a[href],button,input,select,textarea,[tabindex]'))
      .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length && !el.closest('[inert]'));
  }
  function focus(entry) {
    const target = entry.initialFocus && entry.panel.querySelector(entry.initialFocus);
    (target || focusable(entry.panel)[0] || entry.panel).focus();
  }
  function close(value) {
    const root = element(value);
    const index = stack.findIndex(entry => entry.root === root);
    if (index < 0) return;
    // Closing a parent also closes its children, without leaking scroll locks.
    while (stack.length > index) {
      const entry = stack.pop();
      entry.root.classList.remove('open');
      entry.root.style.zIndex = entry.zIndex;
      if (entry.root.tagName === 'DIALOG' && entry.root.open) entry.root.close();
      entry.root.dispatchEvent(new CustomEvent('ygc:closed'));
      if (entry.onClose) entry.onClose();
      if (entry.opener && entry.opener.isConnected && (!top() || top().root.contains(entry.opener))) entry.opener.focus();
      else if (top()) focus(top());
    }
    if (!stack.length) document.body.style.overflow = savedOverflow;
  }
  function open(value, options = {}) {
    const root = element(value);
    if (!root || stack.some(entry => entry.root === root)) return;
    const panel = root.tagName === 'DIALOG' ? root : root.querySelector('[role="dialog"],.modal,.ygc-album-panel') || root;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    if (!panel.hasAttribute('aria-label') && !panel.hasAttribute('aria-labelledby')) {
      panel.setAttribute('aria-label', panel.querySelector('h2,h3')?.textContent || 'Details');
    }
    if (!panel.hasAttribute('tabindex')) panel.tabIndex = -1;
    const entry = {root, panel, opener: options.opener || document.activeElement,
      onClose: options.onClose, initialFocus: options.initialFocus, zIndex: root.style.zIndex};
    if (!stack.length) { savedOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
    stack.push(entry);
    root.style.zIndex = String(3000 + stack.length);
    root.classList.add('open');
    if (root.tagName === 'DIALOG' && !root.open) root.showModal();
    focus(entry);
  }
  document.addEventListener('keydown', event => {
    const entry = top();
    if (!entry) return;
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopImmediatePropagation(); close(entry.root);
    } else if (event.key === 'Tab') {
      const items = focusable(entry.panel);
      const index = items.indexOf(document.activeElement);
      if (!items.length) { event.preventDefault(); entry.panel.focus(); }
      else if (event.shiftKey && index <= 0) { event.preventDefault(); items[items.length - 1].focus(); }
      else if (!event.shiftKey && (index < 0 || index === items.length - 1)) { event.preventDefault(); items[0].focus(); }
    }
  }, true);
  document.addEventListener('focusin', event => {
    if (top() && !top().panel.contains(event.target)) focus(top());
  });
  document.addEventListener('cancel', event => {
    if (top()?.root === event.target) { event.preventDefault(); close(event.target); }
  }, true);
  document.addEventListener('close', event => {
    if (!event.target.open) close(event.target);
  }, true);
  document.addEventListener('click', event => {
    const root = top()?.root;
    if (root?.tagName !== 'DIALOG' || event.target !== root) return;
    const rect = root.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) close(root);
  });
  return {open, close, isOpen: () => !!stack.length};
})();
