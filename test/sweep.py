# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""Käy läpi kaikki sivut 100–899 ja kaikki alasivut: rivimäärä, rivileveys, linkit, pikanäppäimet."""
import json, sys
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
URL = "file://" + _ROOT + "/test/fixture.html"
JS = r"""
(lang) => {
  const L = window.LAKITV, out = {chars:{}, errors:[], pages:0, subs:0, fillers:0, deadLinks:{}, longFt:[], badRows:[], overflow:[]};
  L.setLang(lang);
  const real = new Set(L.NUMS());
  const extra = [];
  const t0 = new Date(); for (let k = 0; k <= 31; k++) extra.push([104, new Date(t0 - k * 864e5).toISOString().slice(0, 10)]);
  (L.allKnown().filter(x => x.ai).slice(0, 40)).forEach(x => extra.push([105, null, x.ai]));
  const seq = []; for (let n = 100; n <= 899; n++) seq.push([n]); seq.push(...extra);
  out.overlaps = [];
  for (const [n, day, ai] of seq) {
    if (day) L.state.day = day; if (ai) L.state.arch = ai;
    window.__ovl = [];
    L.show(n, 0, true);
    if (window.__ovl.length) out.overlaps.push([n, day || ai || "", window.__ovl.slice(0, 3)]);
    const pg = L.state.current;
    const nsub = document.getElementById('rmNow').textContent.match(/(\d+)\/(\d+)/);
    const total = nsub ? +nsub[2] : 1;
    if (!real.has(n)) out.fillers++; else out.pages++;
    for (let s = 0; s < total; s++) {
      if (s > 0) { document.getElementById('kSubNext').click(); }
      out.subs++;
      const rows = [...document.querySelectorAll('#rows .row')];
      let lines = 0;
      rows.forEach((r, i) => {
        if (r.hidden) return;
        const t = r.textContent;
        lines += r.classList.contains('dh') ? 2 : 1;
        if ([...t].length !== 40) out.badRows.push([n, s, i, [...t].length, t]);
        for (const ch of t.toUpperCase()) out.chars[ch] = (out.chars[ch] || 0) + 1;
      });
      if (lines !== 25) out.badRows.push([n, s, 'lines', lines]);
      document.querySelectorAll('#rows a[data-p]').forEach(a => {
        const p = +a.dataset.p; if (!real.has(p)) (out.deadLinks[n] = out.deadLinks[n] || new Set()).add(p);
      });
      const ft = [0,1,2,3].map(i => document.getElementById('ft' + i).textContent);
      ft.forEach(t => { if ([...t].length > 9) out.longFt.push([n, t]); });
    }
  }
  for (const k in out.deadLinks) out.deadLinks[k] = [...out.deadLinks[k]];
  return out;
}
"""
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "fonts.g" not in m.text else None)
    pg.add_init_script("window.__ovl = []")
    pg.goto(URL); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    res = pg.evaluate(JS, sys.argv[1] if len(sys.argv) > 1 else "fi")
    res["jsErrors"] = errs
    from fontTools.ttLib import TTFont
    cm = TTFont(_FONTS + "/lakicaps-sub.woff2").getBestCmap()
    missing = {c: n for c, n in res.pop("chars").items() if ord(c) not in cm}
    res["missingGlyphs"] = missing
    print(json.dumps({k: (v if k not in ("badRows", "overlaps") else v[:25]) for k, v in res.items()}, ensure_ascii=False, indent=1))
    b.close()
