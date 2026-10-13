# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""Päällekirjoitukset suodattimen ollessa päällä (pitkät aihenimet) molemmilla kielillä."""
import json
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
URL = "file://" + _ROOT + "/test/fixture.html"
JS = """(lang) => {
  const L = window.LAKITV; L.setLang(lang);
  const out = [];
  for (const keys of [["ymparisto","asuminen","hallinto","finanssi","kuluttaja","yhtio"], ["sote"], ["tietosuoja","kilpailu","rikos","maahanmuutto"]]) {
    L.state.filter = new Set(keys); L.buildAll();
    for (const n of [100, 101, 102, 103, 104, 110, 200, 250, 300, 400, 700, 740, 850, 851, 190]) {
      window.__ovl = []; L.show(n, 0, true);
      const rows = [...document.querySelectorAll('#rows .row')].filter(r => !r.hidden).map(r => r.textContent);
      rows.forEach((t, i) => { if ([...t].length !== 40) out.push([keys.join(','), n, 'width', i, [...t].length]); });
      if (window.__ovl.length) out.push([keys.join(','), n, window.__ovl.slice(0, 2)]);
    }
  }
  L.state.filter = new Set(); L.buildAll();
  // tunnistimen toiminta
  window.__ovl = []; L.show(100, 0, true);
  return out;
}"""
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script("window.__ovl = []")
    pg.goto(URL); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    for lang in ("fi", "sv"):
        out = pg.evaluate(JS, lang)
        print(lang, json.dumps(out, ensure_ascii=False)[:3000] or "OK")
    # tunnistin toimii: kirjoitetaan tarkoituksella päälle
    print("detector", pg.evaluate("() => { window.__ovl = []; const L = window.LAKITV; const pg = L.getPage(100); return window.__ovl.length; }"))
    print("errors", errs)
    b.close()
