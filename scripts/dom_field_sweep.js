// DOM field sweep — paste into the browser console on the running dashboard.
//
// WHY THIS EXISTS. scripts/audit_schema.py checks whether a FIELD NAME appears
// anywhere in index.html. That has two blind spots that both bit in one session:
// it only walks top-level record keys (themes[].items[].why was never checked),
// and a name used by ANY builder passes for ALL files ("why" renders for
// picks-shovels, so it passed for critical-minerals and themes too). This sweep
// tests VALUES instead: for every string field at any depth in every hand-
// maintained file, does a distinctive slice of it appear in the rendered page?
//
// It renders every tab, opens <details>, expands every heat-map row, every
// theme detail and every company drawer, so on-demand content counts as
// rendered. Anything still missing is either genuinely unrendered (Class 3 in
// docs/QA-LOG.md) or lives in a pane this script does not know how to open —
// in which case, teach it, do not dismiss the miss.
//
// Comparison strips HTML tags from data values first: cluster items contain
// <b>…</b> markup and textContent will never contain the tags.
(async () => {
  const FILES = ['companies','policy','critical-minerals','themes','geopolitical','electricity',
                 'picks-shovels','explainers','explorer','matrix','portfolio','annotations','cycle',
                 'excluded','glossary','reference'];
  const norm = s => String(s).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
  let D = '';
  const grab = () => { D += ' ' + norm(document.body.textContent); };

  for (const id of TAB_IDS) {                                   // every tab
    ST(id); const v = document.getElementById('v-' + id);
    v.querySelectorAll('details').forEach(d => d.open = true);
    if (typeof CM_FILTER !== 'undefined' && id === 'cm') { setCmFilter('all'); }
    grab();
  }
  ST('geo'); for (const h of (GEO.heatmap || [])) { GEO_ACTIVE = h.id; buildGeo(); grab(); } GEO_ACTIVE = null; buildGeo();
  ST('th'); for (const t of (THEMES || [])) { try { loadTheme(t.id); grab(); } catch (e) {} }
  ST('vx'); if (typeof VC !== 'undefined') for (const vid of Object.keys(VC)) { try { (window.selectVertical || window.setVx || (()=>{}))(vid); grab(); } catch (e) {} }
  for (const c of COMPANIES) { try { openCompanyDrawer(c.ticker); grab(); closeDrawer(); } catch (e) {} }
  for (const x of (EXCLUDED || [])) { try { openExcludedNote(x.ticker); grab(); closeDrawer(); } catch (e) {} }
  D += ' ' + [...document.querySelectorAll('[title]')].map(e => norm(e.title)).join(' ');

  const walk = (node, path, acc) => {
    if (Array.isArray(node)) { node.forEach(n => walk(n, path + '[]', acc)); return; }
    if (node && typeof node === 'object') { for (const k in node) { if (k === '_meta') continue; walk(node[k], path ? path + '.' + k : k, acc); } return; }
    if (typeof node === 'string' && norm(node).length >= 40) (acc[path] = acc[path] || []).push(node);
  };
  const out = {};
  for (const f of FILES) {
    let j; try { j = await (await fetch(BASE + f + '.json?t=' + Date.now())).json(); } catch (e) { out[f] = { error: String(e) }; continue; }
    const acc = {}; walk(j, '', acc); const miss = {};
    for (const p in acc) {
      const probes = acc[p].slice(0, 3).map(v => norm(v).slice(0, 50));
      if (!probes.some(pr => D.includes(pr))) miss[p] = acc[p].length;
    }
    out[f] = Object.keys(miss).length ? miss : 'ok';
  }
  ST('act');
  console.table(Object.entries(out).flatMap(([f, m]) => m === 'ok' ? [{ file: f, path: '—', strings: 'ok' }]
    : Object.entries(m).map(([p, n]) => ({ file: f, path: p, strings: n }))));
  return out;
})();
