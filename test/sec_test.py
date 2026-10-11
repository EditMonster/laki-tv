# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""Tietoturva- ja vikatilannetesti: vihamielinen data, rikkinäinen selainmuisti, puuttuvat kyvyt.
Rakentaa kopion sivusta, jonka dataan on ujutettu XSS-yritteitä, ja tarkistaa ettei mikään suoritu."""
import json, re, sys, os
from playwright.sync_api import sync_playwright
BASE = "/tmp/claude-0/-home-claude/c8405571-3ec0-5dfb-a73c-700ea8f8ed87/scratchpad/laki-tv"
SRC = f"{BASE}/laki-tv.html"
OUT = f"{BASE}/test/sec_page.html"
BLOCK = re.compile(r'(<script type="application/json" id="laki-tv-data">)(.*?)(</script>)', re.S)

PAY = "<img src=x onerror=\"window.__xss=1\">"
PAY2 = "</script><script>window.__xss=2</script>"
PAY3 = "'\"><svg onload=window.__xss=3>"
h = open(SRC, encoding="utf-8").read()
m = BLOCK.search(h)
d = json.loads(m.group(2))
# 1. juttu jokaisen kentän kautta
k0 = next(k for k in d["kanavat"] if d["kanavat"][k])
it = dict(d["kanavat"][k0][0])
it.update({"id": "XSS-1", "tunnus": "XSS:2026:1", "otsikko": PAY[:35], "otsikko_sv": PAY3[:35], "otsikko_en": PAY2[:35],
           "teksti": PAY + PAY2 + PAY3, "selko": PAY3, "asiasanat": PAY, "lopputulos": PAY2, "huom": PAY3, "vaihe": PAY3[:30], "elin": PAY[:20],
           "lahde": "javascript:window.__xss=4", "aiheet": ["sote"], "paino": 5, "maaraaika": "2026-10-20",
           "julkaistu": d["kanavat"][k0][0].get("julkaistu")})
d["kanavat"][k0].insert(0, it)
# 2. muut rakenteet
if d.get("voimaantulot"):
    d["voimaantulot"][0]["nimi"] = PAY[:33]; d["voimaantulot"][0]["lahde"] = "javascript:window.__xss=5"; d["voimaantulot"][0]["muutos"] = PAY3
if d.get("eu_voimaantulot"):
    d["eu_voimaantulot"][0]["nimi"] = PAY[:30]; d["eu_voimaantulot"][0]["lahde"] = "data:text/html,<script>window.__xss=6</script>"
if d.get("he_tila"):
    d["he_tila"][0]["nimi"] = PAY[:18]
d["tiedote"] = PAY[:38]
if d.get("visa"):
    d["visa"][0]["kysymys"] = PAY; d["visa"][0]["vaihtoehdot"][0] = PAY3[:33]; d["visa"][0]["selitys"] = PAY2[:45]
d["etusivu"] = [{"ref": "XSS-1", "otsikko": PAY[:35]}]
if d.get("arkisto"):
    d["arkisto"][0]["otsikko"] = PAY[:35]; d["arkisto"][0]["lahde"] = "javascript:window.__xss=7"
s = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
open(OUT, "w", encoding="utf-8").write(h[:m.start(2)] + s + h[m.end(2):])

# vihamielinen selainmuisti
BAD_STORE = {
    "lakitv:seuranta": json.dumps([{"id": "XSS-1", "otsikko": PAY, "tunnus": PAY3, "k": k0, "tila": PAY2, "pvm": "x"}, {"id": 5}, "roska", None, {"id": "A" * 5000, "otsikko": 7}]),
    "lakitv:lang": '"<script>"',
    "lakitv:filter": '{"not":"an array"}',
    "lakitv:subDraft": '"broken',
}
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {extra}" if extra and not c else ""))
    if not c: fails.append(msg)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 820})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.add_init_script("(() => { const S = " + json.dumps(BAD_STORE) + "; for (const k in S) localStorage.setItem(k, S[k]); })()")
    pg.goto("file://" + OUT); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    ok(pg.evaluate("window.__xss") is None, "XSS ei suoritu latauksessa")
    ok(not errors, "ei JS-virheitä vihamielisellä muistilla", errors[:3])
    ok(pg.evaluate("document.documentElement.lang") in ("fi", "sv", "en"), "kieli palautuu oletukseen")
    # käy kaikki sivut ja alasivut kuten sweep
    res = pg.evaluate(r"""() => {
      const L = window.LAKITV, out = {js:[], bad:[], n:0};
      const real = L.NUMS();
      for (const n of real) { try { L.show(n, 0, true); } catch (e) { out.js.push([n, String(e)]); continue; }
        const m = document.getElementById('rmNow').textContent.match(/(\d+)\/(\d+)/); const total = m ? +m[2] : 1;
        for (let s = 0; s < total; s++) { if (s) document.getElementById('kSubNext').click(); out.n++;
          document.querySelectorAll('#rows a[href]').forEach(a => { const u = a.getAttribute('href') || ''; if (/^\s*(javascript|data|vbscript):/i.test(u)) out.bad.push([n, s, u.slice(0, 40)]); });
          if (document.querySelector('#rows img, #rows svg, #rows script')) out.bad.push([n, s, 'elementti']); } }
      return out; }""")
    ok(not res["js"], "kaikki sivut rakentuvat", res["js"][:3])
    ok(not res["bad"], "ei javascript:/data:-linkkejä eikä elementtejä ruudulla", res["bad"][:3])
    ok(pg.evaluate("window.__xss") is None, "XSS ei suoritu sivuilla")
    # juttusivu ja seuranta
    pg.evaluate("window.LAKITV.show(window.LAKITV.NUMS().find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.id === 'XSS-1'), 0, true)") if pg.evaluate("typeof window.LAKITV.itemIndexGet") == "function" else None
    pg.evaluate("window.LAKITV.toggleFollow('XSS-1'); window.LAKITV.show(108, 0, true)")
    ok(pg.evaluate("window.__xss") is None and not errors, "seuranta vihamielisellä jutulla", errors[:3])
    # kalenteripaneeli
    pg.evaluate("window.LAKITV.show(103, 0, true)")
    pg.click("#kSub"); pg.wait_for_timeout(200)
    pg.click("#tabKal"); pg.wait_for_timeout(300)
    hrefs = pg.evaluate("[...document.querySelectorAll('#paneKal a')].map(a => a.getAttribute('href'))")
    ok(all(re.match(r"^(https://|webcal://|file:///)", u or "") for u in hrefs), "kalenterilinkit vain https/webcal", [u for u in hrefs if not re.match(r"^(https://|webcal://|file:///)", u or "")][:3])
    ok(not pg.evaluate("!!document.querySelector('#paneKal img, #paneKal svg')"), "kalenteripaneelissa ei injektoituja elementtejä")
    ok("null" not in pg.evaluate("document.getElementById('paneKal').textContent"), "kalenteripaneelissa ei 'null'-tekstiä ilman valintaa")
    ok(not pg.evaluate("performance.getEntriesByType('resource').some(r => !r.name.startsWith('file:'))"), "sivu ei lataa mitään ulkopuolelta")
    ok(pg.evaluate("window.__xss") is None and not errors, "ei virheitä paneelissa", errors[:3])
    # haku vihamielisellä syötteellä
    pg.click("#tabSearch") if pg.evaluate("!!document.getElementById('tabSearch')") else None
    pg.fill("#q", PAY) if pg.evaluate("!!document.getElementById('q')") else None
    pg.wait_for_timeout(300)
    ok(pg.evaluate("window.__xss") is None and not errors, "haku vihamielisellä syötteellä", errors[:3])
    # localStorage heittää (yksityinen tila)
    pg.evaluate("Object.defineProperty(window, 'localStorage', {get(){ throw new Error('blocked'); }})")
    pg.evaluate("window.LAKITV.setLang('sv'); window.LAKITV.toggleFollow('XSS-1'); window.LAKITV.show(100, 0, true)")
    ok(not errors, "toimii, kun localStorage on estetty", errors[:3])
    # leikepöytä estetty
    pg.evaluate("Object.defineProperty(navigator, 'clipboard', {get(){ return undefined; }})")
    pg.click("#tabKal"); pg.wait_for_timeout(200)
    btn = pg.query_selector("#paneKal button:has-text('Kopiera')") or pg.query_selector("#paneKal button:has-text('Kopioi')")
    if btn: btn.click(); pg.wait_for_timeout(200)
    ok(not errors, "kopiointi ilman leikepöytää ei kaada", errors[:3])
    b.close()
print(f"{len(fails)} virhettä" if fails else "KAIKKI OK")
sys.exit(1 if fails else 0)
