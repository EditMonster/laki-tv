# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""v9-regressiot: sivun bugikorjaukset."""
import json, subprocess, sys, datetime
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))   # testikello: tänään klo 21 Helsinki
B = _ROOT + "/"
sys.path.insert(0, B + "tools"); import lakitv as L
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)
rows = "[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')"

# datavariantti: tuleva juttu, hiljaiset lähteet, tekstityyppi puuttuu, päättynyt lausuntoaika arkistossa
d = json.load(open(B + "test/fixture_data.json", encoding="utf-8"))
today = L.now().date()
fut = dict(d["kanavat"]["kko"][0]); fut.update({"id": "FUT:2026:1", "tunnus": "FUT:2026:1", "otsikko": "TULEVAISUUDEN JUTTU", "paino": 5, "julkaistu": (today + datetime.timedelta(days=3)).isoformat()})
d["kanavat"]["kko"].insert(0, fut)
nt = dict(d["kanavat"]["kho"][0]); nt.update({"id": "NT:2026:1", "tunnus": "NT:2026:1", "otsikko": "ILMAN TEKSTITYYPPIÄ"}); nt.pop("tekstityyppi", None)
d["kanavat"]["kho"].insert(0, nt)
d["_ajot"] = [{"aika": f"{today.isoformat()}T06:46", "uusia": 5, "juttuja": 103, "hiljaa": ["KKO", "KHO"]}]
d.setdefault("_lahteet", {})["TT"] = {"ok": True, "n": 3}
arch = dict(d["kanavat"]["lausunnot"][0]); arch.update({"id": "ARK-L-1", "otsikko": "PÄÄTTYNYT LAUSUNTO", "maaraaika": (today - datetime.timedelta(days=3)).isoformat(), "k": "lausunnot"})
d.setdefault("arkisto", []).append(arch)
json.dump(d, open("/tmp/v9_data.json", "w"), ensure_ascii=False)
subprocess.run([sys.executable, B + "tools/lakitv.py", "inject", B + "test/fixture.html", "/tmp/v9_data.json", "/tmp/v9_page.html", "--force"], capture_output=True, text=True)
URL = "file:///tmp/v9_page.html"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 820}); errs = []
    pg.clock.set_fixed_time(_FIXED)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    # 1. poistunut seurattava
    pg.add_init_script("localStorage.setItem('lakitv:seuranta', JSON.stringify([{id:'gone-id', tunnus:'X', otsikko:'POISTUNUT JUTTU', k:'kko', tila:'pvm:2026-01-01', pvm:'2026-09-01'}]))")
    pg.goto(URL + "#p108"); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    t = pg.evaluate(rows)
    ok("POISTUNUT JUTTU" in t and "LOPETA" in t, "108: poistuneella seurattavalla on LOPETA-linkki", t[:300])
    pg.click("#rows a[data-act='seuraa']"); pg.wait_for_timeout(200)
    ok(pg.evaluate("window.LAKITV.followList().length") == 0, "108: LOPETA poistaa poistuneen seurannan")
    pg.evaluate("localStorage.setItem('lakitv:seuranta', JSON.stringify([{id:'gone-id', tunnus:'X', otsikko:'POISTUNUT', k:'kko', tila:'pvm:2026-01-01', pvm:'2026-09-01'}])); window.dispatchEvent(new StorageEvent('storage', {key:'lakitv:seuranta'})); window.LAKITV.show(108,0,true)")
    pg.wait_for_timeout(100)
    if pg.query_selector("#rows a[data-act='seuraa-ok']"):
        pg.click("#rows a[data-act='seuraa-ok']"); pg.wait_for_timeout(200)
        ok(pg.evaluate("window.LAKITV.followList().length") == 0, "108: MERKITSE NÄHDYIKSI pudottaa poistuneet")
    else:
        ok(False, "108: MERKITSE NÄHDYIKSI -linkki puuttuu poistuneelle")
    # 2. JAKELU-paneeli aukeaa ja sulkeutuu
    pg.evaluate("window.LAKITV.show(100,0,true)"); pg.click("#kSub"); pg.wait_for_timeout(300)
    ok(pg.get_attribute("#tabKal", "aria-selected") == "true", "JAKELU avaa jakelupaneelin")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    # 3-4. rikkinäiset syvälinkit
    for hs, exp in [("#d=2026-06-31", 104), ("#d=0000-00-00", 104), ("#p050", 100), ("#p999", 100), ("#000", 100)]:
        pg.goto(URL + hs); pg.reload(); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
        cur = pg.evaluate("window.LAKITV.state.current"); t = pg.evaluate(rows)
        ok(cur == exp and "EI NÄY" not in t and not errs, f"syvälinkki {hs} -> sivu {exp} ilman virhettä", (cur, errs[:2]))
    pg.goto(URL + "#d=2026-06-31"); pg.reload(); pg.wait_for_timeout(300); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    ok(pg.evaluate("window.LAKITV.state.day") == today.isoformat(), "#d=2026-06-31 -> tämä päivä")
    # 5. otsikot
    pg.goto(URL + "#p101"); pg.reload(); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    t = pg.evaluate("""() => { const L = window.LAKITV; let t=''; const n = L.getPage(101).subs.length; for (let s=0;s<n;s++){ L.show(101,s,true); t += """ + rows + """ + '\\n'; } return t; }""")
    ok("TÄLLÄ VIIKOLLA" not in t.replace("AIEMMIN TÄLLÄ VIIKOLLA", ""), "101: voimaantulojen otsikko ei väitä 'tällä viikolla'", t[:200])
    # 6. tuleva juttu ei ole kärki eikä UUSI
    pg.evaluate("window.LAKITV.show(100,0,true)"); t = pg.evaluate(rows)
    ok("TULEVAISUUDEN JUTTU" not in t, "100: tulevaisuuteen päivätty juttu ei ole etusivulla", t[:200])
    n = pg.evaluate("[...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.id === 'FUT:2026:1')")
    pg.evaluate(f"window.LAKITV.show({n},0,true)"); t = pg.evaluate(rows)
    ok("UUSI" not in t, "juttusivu: tuleva juttu ei ole UUSI", t[:200])
    # 7. 198 ilman päällekkäisyyttä
    t = pg.evaluate("""() => { const L = window.LAKITV; window.__ovl = []; let t=''; const n = L.getPage(198).subs.length; for (let s=0;s<n;s++){ L.show(198,s,true); t += """ + rows + """ + '\\n'; } return t; }""")
    ok("KKO,KHO" in t and not pg.evaluate("window.__ovl.length"), "198: ajorivi ja hiljaiset lähteet eivät mene päällekkäin", pg.evaluate("window.__ovl"))
    pg.evaluate("window.LAKITV.setLang('sv'); window.LAKITV.show(198,0,true)"); t = pg.evaluate(rows)
    ok("Arbetsdomst" in t, "198 sv: lähteen nimi ruotsiksi", t[:300]); pg.evaluate("window.LAKITV.setLang('fi')")
    # 8. haamuhistoria
    pg.evaluate("window.LAKITV.show(100,0,true); window.LAKITV.state.hist = []")
    pg.evaluate("window.LAKITV.go(201); document.dispatchEvent(new KeyboardEvent('keydown', {key:'2', bubbles:true}))"); pg.wait_for_timeout(300)
    ok(pg.evaluate("window.LAKITV.state.hist.length") == 0 and pg.evaluate("window.LAKITV.state.current") == 100, "keskeytetty sivunvaihto ei jätä historiamerkintää", pg.evaluate("[window.LAKITV.state.hist, window.LAKITV.state.current]"))
    pg.evaluate("window.LAKITV.go(201)"); pg.wait_for_timeout(300)
    ok(pg.evaluate("window.LAKITV.state.hist.length") == 1 and pg.evaluate("window.LAKITV.state.current") == 201, "onnistunut sivunvaihto kirjautuu historiaan")
    # pienet
    n = pg.evaluate("[...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.id === 'NT:2026:1')")
    t = pg.evaluate("((num) => { const L = window.LAKITV; let t=''; const n = L.getPage(num).subs.length; for (let s=0;s<n;s++){ L.show(num,s,true); t += " + rows + " + '\\n'; } return t; })(" + str(n) + ")")
    ok("undefined" not in t.lower() and "TEKOÄLY" not in t.upper(), "juttusivu ilman tekstityyppiä: ei 'undefined', ei tyyppiriviä", t[:200])
    pg.evaluate("window.LAKITV.state.arch = 'ARK-L-1'; window.LAKITV.show(105,0,true)")
    t = pg.evaluate("""() => { const L = window.LAKITV; let t=''; const n = L.getPage(105).subs.length; for (let s=0;s<n;s++){ L.show(105,s,true); t += """ + rows + """ + '\\n'; } return t; }""")
    ok("PÄÄTTYNYT" in t and "KALENTERIIN" not in t, "arkistoitu lausunto: PÄÄTTYNYT, ei kalenterilinkkiä", t[:300])
    pg.evaluate("window.LAKITV.show(107,0,true)"); t = pg.evaluate(rows)
    ok("…" not in t.split("\n")[2] if len(t.split("\n")) > 2 else True, "107: alaotsikko ei katkea", t.split("\n")[1:3])
    ok(not errs, "ei JS-virheitä", errs[:3])
    b.close()
print(f"{len(fails)} virhettä" if fails else "KAIKKI OK")
sys.exit(1 if fails else 0)
