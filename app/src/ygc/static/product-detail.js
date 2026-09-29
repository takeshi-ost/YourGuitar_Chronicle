/* Shared Product Detail layout. Page-specific actions and Claim cards are extensions. */
window.YGCProductDetail = (() => {
  function orderedClaims(source, mode = 'event') {
    const sorted = (source || []).slice().sort((a, b) => {
      const value = c => mode === 'input' ? String(c.created_at || '') : String(c.occurred_at || c.created_at || '').slice(0, 10);
      const av = value(a), bv = value(b);
      return av < bv ? 1 : av > bv ? -1 : Number(b.id) - Number(a.id);
    });
    const corrections = new Map(), roots = [];
    for (const claim of sorted) {
      if (claim.claim_type === 'identity_correction' && claim.target_claim_id) {
        const key = Number(claim.target_claim_id);
        if (!corrections.has(key)) corrections.set(key, []);
        corrections.get(key).push(claim);
      } else roots.push(claim);
    }
    const ordered = [];
    for (const claim of roots) {
      ordered.push(claim);
      const related = corrections.get(Number(claim.id)) || [];
      related.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')));
      ordered.push(...related);
      corrections.delete(Number(claim.id));
    }
    for (const related of corrections.values()) ordered.push(...related);
    return ordered;
  }

  function render({individual: i, specifications = [], image, owner, location, ownership = '',
    titleAction = '', headerAction = '', chronicleAction = '', fieldLabel, escape}) {
    const specMap = {};
    for (const spec of specifications) specMap[String(spec.field_name || '')] = spec;
    const fixed = [['Maker', i.manufacturer || '—'], ['Model', i.model || '—'],
      ['Finish', (specMap.finish ? specMap.finish.value_text : i.finish) || '—'],
      ['Year', i.year || '—'], ['Serial', i.serial_number || '—']];
    const hidden = new Set(['maker', 'manufacturer', 'model', 'finish', 'year', 'serial', 'serial_number']);
    const preferred = ['body', 'bridge', 'fingerboard', 'frets', 'neck', 'nut', 'pickups',
      'pickguard', 'potentiometers', 'tuners', 'wiring', 'weight'];
    const dynamic = specifications.filter(s => !hidden.has(String(s.field_name || '').toLowerCase()))
      .slice().sort((a, b) => {
        const ak = String(a.field_name || '').toLowerCase(), bk = String(b.field_name || '').toLowerCase();
        const ai = preferred.indexOf(ak), bi = preferred.indexOf(bk);
        if (ai >= 0 || bi >= 0) {
          if (ai < 0) return 1;
          if (bi < 0) return -1;
          if (ai !== bi) return ai - bi;
        }
        return ak.localeCompare(bk);
      });
    const row = (label, value) => '<div class="catalog-spec-row"><span class="catalog-spec-label">' + escape(label) + ':</span> ' + escape(value) + '</div>';
    return image +
      '<div class="detail-header"><div class="detail-title-row"><div class="detail-header-title">' + escape(i.manufacturer) + ' ' + escape(i.model || '') + '</div>' + titleAction + '</div>' +
      '<div class="current-owner-line"><span class="catalog-spec-label">Current Owner:</span> ' + owner + '</div>' +
      '<div class="current-owner-line"><span class="catalog-spec-label">Location:</span> ' + location + '</div>' +
      ownership + headerAction + '</div>' +
      '<section class="accordion-section" id="specificationAccordion"><div class="accordion-header"><button type="button" class="accordion-toggle" onclick="toggleDetailAccordion(\'specificationAccordion\')">▼</button><span class="accordion-title" onclick="toggleDetailAccordion(\'specificationAccordion\')">Specification</span></div><div class="accordion-body"><div class="catalog-spec">' +
      fixed.map(([label, value]) => row(label, value)).join('') +
      dynamic.map(s => row(fieldLabel(s.field_name), s.value_text || '—')).join('') +
      '</div></div></section>' +
      '<section class="accordion-section" id="chronicleAccordion"><div class="accordion-header"><button type="button" class="accordion-toggle" onclick="toggleDetailAccordion(\'chronicleAccordion\')">▼</button><span class="accordion-title" onclick="toggleDetailAccordion(\'chronicleAccordion\')">Chronicle</span>' + chronicleAction +
      '</div><div class="accordion-body"><div id="chronicleEntries"></div></div></section>';
  }
  return {render, orderedClaims};
})();

/* The same album is used by Top Page, User Profile, and Browser Console. */
window.YGCImageAlbum = (() => {
  let items = [];
  let index = 0;
  let opener = null;
  let previousOverflow = '';
  let overlay = null;

  function caption(item) {
    const note = String(item.caption || '').trim();
    return String(item.label || 'Uploaded Image') + (note ? ' — ' + note : '');
  }

  function render() {
    const item = items[index];
    overlay.querySelector('.ygc-album-image').src = item.url;
    overlay.querySelector('.ygc-album-image').alt = caption(item);
    overlay.querySelector('.ygc-album-caption').textContent = caption(item);
    overlay.querySelector('.ygc-album-counter').textContent = (index + 1) + ' / ' + items.length;
    overlay.querySelectorAll('.ygc-album-nav').forEach(button => {
      button.hidden = items.length < 2;
    });
  }

  function step(delta) {
    if (items.length < 2) return;
    index = (index + delta + items.length) % items.length;
    render();
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    document.body.style.overflow = previousOverflow;
    if (opener && opener.isConnected) opener.focus();
    opener = null;
    items = [];
  }

  function onKeydown(event) {
    if (!overlay) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
  }
  document.addEventListener('keydown', onKeydown);

  function open(images, selectedIndex = 0, trigger = null) {
    const valid = (images || []).filter(item => item && item.url);
    if (!valid.length) return;
    close();
    items = valid;
    index = Math.max(0, Math.min(Number(selectedIndex) || 0, items.length - 1));
    opener = trigger || document.activeElement;
    previousOverflow = document.body.style.overflow;
    overlay = document.createElement('div');
    overlay.className = 'ygc-album-backdrop';
    overlay.innerHTML = '<div class="ygc-album-panel" role="dialog" aria-modal="true" aria-label="Guitar photo album">' +
      '<div class="ygc-album-header"><span class="ygc-album-counter"></span><button type="button" class="ygc-album-close">Close</button></div>' +
      '<div class="ygc-album-stage"><button type="button" class="ygc-album-nav ygc-album-prev" aria-label="Previous image">‹</button>' +
      '<img class="ygc-album-image" alt=""><button type="button" class="ygc-album-nav ygc-album-next" aria-label="Next image">›</button></div>' +
      '<div class="ygc-album-caption"></div></div>';
    overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
    overlay.querySelector('.ygc-album-close').addEventListener('click', close);
    overlay.querySelector('.ygc-album-prev').addEventListener('click', () => step(-1));
    overlay.querySelector('.ygc-album-next').addEventListener('click', () => step(1));
    document.body.append(overlay);
    document.body.style.overflow = 'hidden';
    render();
    overlay.querySelector('.ygc-album-close').focus();
  }

  const style = document.createElement('style');
  style.textContent = `
    #detail .detail-gallery,#detail .detail-image:not(.detail-gallery .detail-image):not(.detail-image-link .detail-image){cursor:zoom-in}
    #detail .detail-image-link{cursor:pointer}
    #detail .detail-gallery-nav{cursor:pointer}
    #detail .detail-gallery:focus-visible,#detail .detail-image-link:focus-visible,#detail .detail-image:focus-visible{outline:2px solid var(--accent,#d0a45d);outline-offset:3px}
    .ygc-album-backdrop{position:fixed;inset:0;z-index:3000;display:flex;align-items:center;justify-content:center;padding:clamp(12px,2.5vw,32px);background:rgba(0,0,0,.88)}
    .ygc-album-panel{box-sizing:border-box;width:min(1600px,100%);height:min(1000px,100%);display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:10px;padding:12px 16px;background:#111418;color:#f0f0ed;border:1px solid #5a626a;border-radius:12px;box-shadow:0 20px 70px #000b}
    .ygc-album-header{display:flex;align-items:center;justify-content:space-between;min-height:36px;font-size:13px;color:#c6cbd0}
    .ygc-album-panel button{border:1px solid #66707a;border-radius:7px;background:#252b31;color:#fff;cursor:pointer}
    .ygc-album-close{min-height:34px;padding:6px 14px;font-size:13px}
    .ygc-album-panel button:hover{background:#3a434b}
    .ygc-album-panel button:focus-visible{outline:2px solid #d0a45d;outline-offset:2px}
    .ygc-album-stage{min-height:0;display:grid;grid-template-columns:42px minmax(0,1fr) 42px;grid-template-rows:minmax(0,1fr);align-items:center;gap:10px;overflow:hidden}
    .ygc-album-image{display:block;min-width:0;min-height:0;max-width:100%;max-height:100%;width:100%;height:100%;object-fit:contain}
    .ygc-album-nav{width:42px;height:52px;font-size:32px;line-height:1}
    .ygc-album-nav[hidden]{visibility:hidden}
    .ygc-album-caption{min-height:24px;text-align:center;font-size:13px;color:#c6cbd0;overflow-wrap:anywhere}
    @media(max-width:600px){.ygc-album-panel{padding:8px}.ygc-album-stage{grid-template-columns:30px minmax(0,1fr) 30px;gap:2px}.ygc-album-nav{width:30px;height:44px}}
  `;
  document.head.append(style);
  function openRepresentative(image) {
    open([{url: image.currentSrc || image.src, label: 'Representative Image'}], 0, image);
  }

  function openFromFrame(event) {
    if (event.target.closest('.detail-gallery-nav')) return false;
    const detail = event.target.closest('#detail');
    if (!detail) return false;
    if (event.target.closest('.detail-image-link')) return false;
    const gallery = event.target.closest('.detail-gallery');
    if (gallery) {
      if (typeof window.openProductAlbum === 'function') window.openProductAlbum();
      return true;
    }
    const frame = event.target.closest('.detail-image');
    if (!frame) return false;
    open([{url: frame.currentSrc || frame.src, label: frame.alt || 'Guitar image'}], 0, frame);
    return true;
  }
  document.addEventListener('click', event => {
    if (openFromFrame(event)) event.preventDefault();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (event.target.closest('.detail-gallery-nav')) return;
    if (openFromFrame(event)) event.preventDefault();
  });
  return {open, openRepresentative, close, step};
})();
