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
