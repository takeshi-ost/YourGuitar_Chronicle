/* Shared Product Detail layout. Page-specific actions and Claim cards are extensions. */
window.YGCProductDetail = (() => {
  function userLink(id, name, escape) {
    const userId = Number(id);
    const label = escape(name || (Number.isSafeInteger(userId) && userId > 0 ? 'User #' + userId : 'User'));
    return Number.isSafeInteger(userId) && userId > 0
      ? '<a class="claim-user-link" href="/users/' + userId + '" onclick="event.stopPropagation()">' + label + '</a>'
      : label;
  }
  function orderedClaims(source) {
    const sorted = (source || []).slice().sort((a, b) => {
      const value = c => String(c.occurred_at || c.created_at || '').slice(0, 10);
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
      '<div class="current-owner-line"><span class="catalog-spec-label">Current Owner:</span><span class="owner-value">' + owner + '</span></div>' +
      '<div class="current-owner-line"><span class="catalog-spec-label">Location:</span> ' + location + '</div>' +
      ownership + headerAction + '</div>' +
      '<section class="accordion-section" id="specificationAccordion"><div class="accordion-header"><span class="accordion-title" onclick="toggleDetailAccordion(\'specificationAccordion\')">Specification</span><button type="button" class="accordion-toggle" aria-label="Toggle Specification" onclick="toggleDetailAccordion(\'specificationAccordion\')">▼</button></div><div class="accordion-body"><div class="catalog-spec">' +
      fixed.map(([label, value]) => row(label, value)).join('') +
      dynamic.map(s => row(fieldLabel(s.field_name), s.value_text || '—')).join('') +
      '</div></div></section>' +
      '<section class="accordion-section" id="chronicleAccordion"><div class="accordion-header"><span class="accordion-title" onclick="toggleDetailAccordion(\'chronicleAccordion\')">Chronicle</span><button type="button" class="accordion-toggle" aria-label="Toggle Chronicle" onclick="toggleDetailAccordion(\'chronicleAccordion\')">▼</button></div>' +
      '<div class="accordion-body">' + chronicleAction + '<div id="chronicleEntries"></div></div></section>';
  }
  return {render, orderedClaims, userLink, toggleAccordion: id => document.getElementById(id)?.classList.toggle('collapsed')};
})();

/* The same album is used by Top Page, User Profile, and Browser Console. */
window.YGCImageAlbum = (() => {
  let items = [];
  let index = 0;
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
    window.YGCOverlays.close(overlay);
  }

  function onKeydown(event) {
    if (!overlay) return;
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
    render();
    const current = overlay;
    window.YGCOverlays.open(current, {opener: trigger || document.activeElement,
      onClose: () => { current.remove(); overlay = null; items = []; }});
  }

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


/* One gallery per Product Detail; shared by Console, Top and Profile. */
window.YGCProductGallery = (() => {
let productGallery=[], productGalleryIndex=0;
function render(images,model,esc){
  productGallery=(images||[]).slice();
  productGalleryIndex=0;
  if(!productGallery.length)return '';
  const item=productGallery[0];
  const disabled=productGallery.length<2?' disabled':'';
  const caption=String(item.caption||'').trim();
  const source=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' (1/'+productGallery.length+')';
  return '<div class="detail-gallery" tabindex="0" aria-label="Open photo album">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(-1)"'+disabled+'>◀</button>'+
    '<img class="detail-image" id="productGalleryImage" src="'+esc(item.url)+'" alt="'+esc(model||'Guitar')+'" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">'+
    '<button class="detail-gallery-nav" onclick="stepProductGallery(1)"'+disabled+'>▶</button>'+
    '</div><span class="detail-source" id="productGallerySource">'+esc(source)+'</span>';
}
function step(delta){
  if(productGallery.length<2)return;
  productGalleryIndex=(productGalleryIndex+delta+productGallery.length)%productGallery.length;
  const item=productGallery[productGalleryIndex];
  const image=document.getElementById('productGalleryImage');
  const source=document.getElementById('productGallerySource');
  if(image)image.src=item.url;
  if(source){
    const caption=String(item.caption||'').trim();
    source.textContent=String(item.label||'Uploaded Image')+(caption?' — '+caption:'')+' ('+(productGalleryIndex+1)+'/'+productGallery.length+')';
  }
}
function open(){
  YGCImageAlbum.open(productGallery,productGalleryIndex,document.querySelector('#detail .detail-gallery'));
}
return {render, step, open};
})();
