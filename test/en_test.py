# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""Englanti: kielivalinta, juttusivu, selko, arkisto, tulostaulu, visa, haku, tilaus, staattiset tekstit, EN_S-kattavuus."""
import json, re, sys, subprocess
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))   # testikello: tänään klo 21 Helsinki
BASE = "/tmp/claude-0/-home-claude/c8405571-3ec0-5dfb-a73c-700ea8f8ed87/scratchpad/laki-tv/"
ok = []
def check(name, cond, info=""):
    ok.append(bool(cond)); print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))
rows = lambda pg: pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
allrows = lambda pg, n: pg.evaluate("""(n) => { const L = window.LAKITV; let t = ''; const p = L.getPage(n); for (let s = 0; s < p.subs.length; s++) { L.show(n, s); t += [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n'); } return t; }""", n)

# 0) staattinen kattavuus: jokaiselle S("…")-kutsulle on englanninnos EN_S:ssä
src = open(BASE + "part_js.html", encoding="utf-8").read()
r = subprocess.run(["python3", BASE + "en/extract_s.py"], capture_output=True, text=True, cwd=BASE)
lit = json.load(open(BASE + "en/s_strings.json", encoding="utf-8"))["literal"]
m = re.search(r"const EN_S = \{\n(.*?)\n\};", src, re.S)
en_keys = set(json.loads("{" + m.group(1) + "}").keys())
has3 = lambda k: re.search(r'S\(' + re.escape(json.dumps(k, ensure_ascii=False)) + r',\s*"[^"]*",\s*"', src) is not None   # kolmas argumentti annettu suoraan
missing = [s for s, l in lit if s not in en_keys and not has3(s)]
check("EN_S kattaa kaikki S()-merkkijonot", not missing, missing[:10])
# kaikilla data-sv-elementeillä on data-en
body = open(BASE + "part_body.html", encoding="utf-8").read()
tags = re.findall(r"<[^>]*data-sv(?:-\w+)?=[^>]*>", body)
nomatch = [t[:80] for t in tags if not re.search(r"data-en(?:-\w+)?=", t)]
check("jokaisella data-sv:llä on data-en", not nomatch, nomatch)

d = json.load(open(BASE + "test/fixture_data.json", encoding="utf-8"))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.clock.set_fixed_time(_FIXED)
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file://" + BASE + "test/fixture.html"); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.click("#kEn"); pg.wait_for_timeout(400)
    t = rows(pg)
    check("EN: etusivu englanniksi", "TOP NEWS" in t and "CHANNEL LIST" in t and "LEGAL" in t, t[:300])
    check("EN: html lang + nappi päällä", pg.evaluate("document.documentElement.lang") == "en" and pg.evaluate("document.getElementById('kEn').classList.contains('on')"))
    check("EN: kaukosäätimen tekstit", pg.inner_text("#kSearch").strip() == "SEARCH" and pg.inner_text("#kSub").strip() == "FEEDS" and pg.inner_text("#tabKal").strip() == "Feeds" and pg.inner_text("#kList").strip() == "CHANNELS")
    pg.reload(); pg.wait_for_timeout(500)
    check("EN: valinta muistetaan", pg.evaluate("document.documentElement.lang") == "en" and "TOP NEWS" in rows(pg))
    it = d["kanavat"]["kko"][0]
    pg.evaluate("window.LAKITV.go(201)"); pg.wait_for_timeout(400)
    t = allrows(pg, 201)
    check("EN: juttusivu otsikko_en, ei suomiviestiä", it["otsikko_en"] in t and "ONLY IN FINNISH" not in t.upper() and "SOURCE" in t, t[:300])
    check("EN: tunnus KKO säilyy", "KKO:" in t and "HD:" not in t)
    pg.evaluate("window.LAKITV.go(888)"); pg.wait_for_timeout(400)
    t = allrows(pg, 888)
    check("EN: 888 selko_en", it["selko_en"].split(".")[0].upper()[:30] in t.upper(), t[:300])
    pg.evaluate("window.LAKITV.go(720)"); pg.wait_for_timeout(400)
    t = allrows(pg, 720)
    check("EN: 720 nimi_en", any(h["nimi_en"].upper() in t.upper() for h in d["he_tila"][:5]) and "BILL TRACKER" in t, t[:300])
    pg.evaluate("window.LAKITV.go(150)"); pg.wait_for_timeout(400)
    t = allrows(pg, 150)
    q = d["visa"][0]
    check("EN: visa kysymys_en ja vaihtoehdot_en", q["vaihtoehdot_en"][2].upper() in t.upper() and "DAILY LEGAL QUIZ" in t, t[:300])
    pg.evaluate("window.LAKITV.go(801)"); pg.wait_for_timeout(400)
    t = allrows(pg, 801)
    check("EN: 801 säädöstyyppi englanniksi", "REGULATION (EU)" in t.upper() and "ASETUS (EU)" not in t.upper(), t[:300])
    arch = d["arkisto"][0]
    pg.evaluate("window.LAKITV.go(105, false, {ai: %s})" % json.dumps(arch["id"])); pg.wait_for_timeout(400)
    t = allrows(pg, 105)
    check("EN: arkistojuttu englanniksi", arch["otsikko_en"] in t and "ARCHIVE" in t, t[:300])
    pg.evaluate("window.LAKITV.go(100)"); pg.wait_for_timeout(300)
    t = rows(pg)
    check("EN: tiedote_en etusivulla", d["tiedote_en"] in t, t[:400])
    # haku englanninkielisellä sanalla
    pg.click("#kSearch"); pg.wait_for_timeout(300); pg.fill("#q", "guardian"); pg.wait_for_timeout(400)
    n = pg.evaluate("document.querySelectorAll('#qResults .pn-ch').length")
    check("EN: haku löytää englanninkielisen sanan", n >= 1 and "hits" in pg.inner_text("#qCount"), (n, pg.inner_text("#qCount")))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    # tilauslomake: kielivalinta en
    pg2 = b.new_page(viewport={"width": 1280, "height": 820})
    pg2.clock.set_fixed_time(_FIXED)
    pg2.add_init_script("""
      window.__sets = [];
      window.claude = { use: async n => n === 'db' ? {doc: p => ({get: async () => ({exists:false}), set: async v => { window.__sets.push([p, v]); }, delete: async () => {}}), collection: c => ({add: async v => ({id:'x'})})} : n === 'user' ? {id: async () => 'u_test123'} : null };
    """)
    e2 = []; pg2.on("pageerror", lambda e: e2.append(str(e)))
    pg2.goto("file://" + BASE + "test/fixture.html"); pg2.wait_for_timeout(500); pg2.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg2.wait_for_timeout(300)
    pg2.click("#kEn"); pg2.wait_for_timeout(300); pg2.click("#kSub"); pg2.wait_for_timeout(500)
    labels = pg2.evaluate("[...document.querySelectorAll('#paneKal h3')].map(l => l.textContent.trim())")
    check("EN: jakelupaneeli englanniksi", any("Next 30 days" in l for l in labels) and any("Feeds and weekly review" in l for l in labels), labels[:12])
    # digest-työkalu englanniksi tilaajalle
    json.dump({"a": {"email": "x@example.com", "sisalto": ["paiva"], "kieli": "en", "suostumus": True}}, open("/tmp/t_til.json", "w"))
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "digest", BASE + "test/fixture_data.json", "--laji", "aamu", "--tilaukset", "/tmp/t_til.json", "--out", "/tmp/t_msgs.json"], capture_output=True, text=True)
    msgs = json.load(open("/tmp/t_msgs.json"))
    check("digest: englanninkielinen viesti tilaajalle", msgs and msgs[0]["kieli"] == "en" and msgs[0]["subject"].startswith("LAKI-TV morning digest") and "LEGAL TELETEXT" in msgs[0]["html"], (r.stdout, msgs[0]["subject"] if msgs else None))
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "validate", BASE + "test/fixture_data.json"], capture_output=True, text=True)
    check("validate: ei ENGLANTI PUUTTUU -rivejä", "ENGLANTI PUUTTUU" not in r.stdout and "0 virhettä" in r.stdout, r.stdout[-300:])
    check("ei JS-virheitä", not errs and not e2, errs + e2)
    b.close()
print(f"{sum(ok)} / {len(ok)} OK")
