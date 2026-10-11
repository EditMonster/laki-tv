"""v11-regressiot: toisen katselmuksen korjaukset (sivu)."""
import json, subprocess, sys, datetime, os
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
HKI = _zi.ZoneInfo("Europe/Helsinki")
_FIXED = _dt.datetime.combine(_dt.datetime.now(HKI).date(), _dt.time(21, 0), tzinfo=HKI)
B = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"
sys.path.insert(0, B + "tools"); import lakitv as L
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)
rows = "[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')"
allsubs = lambda num: """((num) => { const L = window.LAKITV; let out = []; const n = L.getPage(num).subs.length; for (let s=0;s<n;s++){ L.show(num,s,true); out.push(""" + rows + """); } return out; })(%d)""" % num

d = json.load(open(B + "test/fixture_data.json", encoding="utf-8"))
today = L.now().date()
# vaihemuutos, päättynyt lausunto kanavalla, SuV-valiokunta lokakuussa, UUSI-juttu eilen 20.30, prototyyppiavain aiheissa
he = d["kanavat"]["he"][0]
d["he_muutokset"] = [{"he": he["tunnus"], "nimi": he["otsikko"], "vanha": 4, "uusi": 5, "havaittu": today.isoformat()}]
d.setdefault("he_tila", []).append({"he": "HE 999/2026 vp", "nimi": "Suurivaliokuntatesti", "vaihe": 2, "valiokunta": "SuV", "pvm": f"{today.year}-10-25"})
exp = d["kanavat"]["lausunnot"][0]; exp["maaraaika"] = (today - datetime.timedelta(days=2)).isoformat()
y = today - datetime.timedelta(days=1)
fresh = d["kanavat"]["kko"][0]; fresh["julkaistu"] = f"{y.isoformat()}T22:30"; fresh["pvm"] = y.isoformat()
proto = dict(d["kanavat"]["kho"][0]); proto.update({"id": "PROTO:1", "tunnus": "PROTO:1", "otsikko": "PROTOTYYPPIAVAIN", "aiheet": ["constructor", "sote"]})
d["kanavat"]["kho"].insert(1, proto)
d.setdefault("arkisto", []).append({**dict(d["kanavat"]["eu"][-1]), "id": "ARK-PROTO", "tunnus": "ARK-PROTO", "otsikko": "ARKISTO PROTO", "k": "constructor"})
json.dump(d, open("/tmp/v11_data.json", "w"), ensure_ascii=False)
subprocess.run([sys.executable, B + "tools/lakitv.py", "inject", B + "test/fixture.html", "/tmp/v11_data.json", "/tmp/v11_page.html", "--force"], capture_output=True, text=True)
URL = "file:///tmp/v11_page.html"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 820}); errs = []
    pg.clock.set_fixed_time(_FIXED)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL + "#p101"); pg.wait_for_timeout(600)
    pg.evaluate("window.__ovl = []")
    # 1. EDUSKUNNASSA näyttää uuden vaiheen
    t = "\n".join(pg.evaluate(allsubs(101)))
    ok("▶ 2. käsittely" in t, "101: vaihemuutosrivillä uusi vaihe kokonaan", [l for l in t.split("\n") if "▶" in l][:3])
    # 2. päättynyt lausuntoaika ilman päällekkäisyyttä
    n = pg.evaluate("[...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.id === %s)" % json.dumps(exp["id"]))
    t = "\n".join(pg.evaluate(allsubs(n)))
    ok("LAUSUNTOAIKA PÄÄTTYI" in t and "PÄÄTTYNYT" not in t and not pg.evaluate("window.__ovl.length"), "juttusivu: päättynyt lausuntoaika omalla rivillä, ei päällekkäisyyttä", pg.evaluate("window.__ovl")[:3])
    # 3. 190: LAINSÄÄDÄNTÖ yhdellä alasivulla
    subs = pg.evaluate(allsubs(190))
    ok(any("LAINSÄÄDÄNTÖ" in s and "802" in s for s in subs) and len(subs) <= 3, "190: LAINSÄÄDÄNTÖ-osio ei jakaudu", [s[:80] for s in subs])
    ok(not any(s.strip().count("\n") < 3 for s in subs), "190: ei lähes tyhjiä alasivuja")
    # 4. seuranta huomaa arkistoon siirtymisen
    pg.evaluate("window.LAKITV.show(100,0,true)")
    kid = d["kanavat"]["kko"][-1]["id"]
    pg.evaluate("localStorage.setItem('lakitv:seuranta', JSON.stringify([{id:%s, tunnus:'X', otsikko:'ARK TESTI', k:'kko', tila:'pvm:%s', pvm:'2026-09-01'}])); window.dispatchEvent(new StorageEvent('storage', {key:'lakitv:seuranta'}))" % (json.dumps(kid), d["kanavat"]["kko"][-1].get("julkaistu", "")))
    d2 = json.loads(open("/tmp/v11_data.json", encoding="utf-8").read())
    moved = d2["kanavat"]["kko"].pop(); moved["k"] = "kko"; d2.setdefault("arkisto", []).append(moved)
    json.dump(d2, open("/tmp/v11b_data.json", "w"), ensure_ascii=False)
    subprocess.run([sys.executable, B + "tools/lakitv.py", "inject", B + "test/fixture.html", "/tmp/v11b_data.json", "/tmp/v11b_page.html", "--force"], capture_output=True, text=True)
    pg.goto("file:///tmp/v11b_page.html#p108"); pg.wait_for_timeout(600)
    t = "\n".join(pg.evaluate(allsubs(108)))
    T = t.upper()
    ok("MUUTTUNUT" in T and "▶ ARKISTOSSA" in T and T.index("▶ ARKISTOSSA") < (T.index("EI MUUTOKSIA") if "EI MUUTOKSIA" in T else 10**6), "108: arkistoon siirtynyt juttu on MUUTTUNUT-osiossa", t[:400])
    pg.goto(URL); pg.wait_for_timeout(500)
    # 5. 850 englanniksi: sivunumero näkyy värinäppäimessä
    pg.evaluate("window.LAKITV.setLang('en'); window.LAKITV.show(850,0,true)"); pg.wait_for_timeout(100)
    ft = pg.evaluate("document.getElementById('ft0').textContent")
    ok(ft.endswith("851") and len(ft) <= 9, "850 en: punainen näppäin päättyy 851", ft)
    pg.evaluate("window.LAKITV.setLang('fi')")
    # 7. juttusivuilla ei alasivua, jolla on vain toimintorivi
    lonely = pg.evaluate("""() => { const L = window.LAKITV; const bad = []; for (const n of L.NUMS()) { const pg = L.getPage(n); if (!pg || !pg.item || pg.subs.length < 2) continue;
      const last = pg.subs[pg.subs.length - 1]; const txt = last.map(r => (r.c || []).map(c => c.t).join('').trim()).filter(Boolean); const body = txt.slice(1, -1).filter(x => !/^\\d\\/\\d$/.test(x));
      if (body.length <= 2) bad.push([n, body]); } return bad; }""")
    ok(not lonely, "juttusivut: viimeisellä alasivulla on enemmän kuin pelkkä toimintorivi", lonely[:3])
    # 9. UUSI-merkintä vanhenee tunnin vaihtuessa ilman sivun latausta
    pg.evaluate("window.LAKITV.show(200,0,true)"); t0 = pg.evaluate(rows)
    ok("UUSI" in t0, "200: eilen 22.30 julkaistu on UUSI klo 21", t0[:200])
    pg.clock.set_fixed_time(_FIXED + datetime.timedelta(hours=1, minutes=45)); pg.wait_for_timeout(1600)
    pg.evaluate("window.LAKITV.show(200,0,true)"); t1 = pg.evaluate(rows)
    ok("UUSI" not in t1, "200: klo 22.45 UUSI on poistunut ilman uudelleenlatausta", t1[:200])
    pg.clock.set_fixed_time(_FIXED); pg.wait_for_timeout(1200)
    # 11. kohdistus ei putoa bodyyn linkin jälkeen
    pg.evaluate("window.LAKITV.show(100,0,true)"); pg.wait_for_timeout(100)
    pg.focus("#rows a[data-p='101']"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    ok(pg.evaluate("window.LAKITV.state.current") == 101 and pg.evaluate("document.activeElement.tagName") != "BODY", "linkin aktivointi säilyttää kohdistuksen ruudulla", pg.evaluate("document.activeElement.tagName"))
    # 12. prototyypin nimiset avaimet
    n = pg.evaluate("[...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.id === 'PROTO:1')")
    t = "\n".join(pg.evaluate(allsubs(n)))
    ok("undefined" not in t.lower() and "SOTE" in t, "juttusivu: 'constructor' ei ole aihe", t[:200])
    pg.evaluate("window.LAKITV.show(100,0,true)"); pg.click("#kSearch"); pg.wait_for_timeout(300); pg.fill("#q", "proto"); pg.wait_for_timeout(400)
    ok(pg.is_visible("#paneSearch") and not errs, "haku aukeaa prototyyppiavaimesta huolimatta", errs[:2]); pg.keyboard.press("Escape")
    pg.evaluate("window.LAKITV.state.arch = 'ARK-PROTO'; window.LAKITV.show(105,0,true)"); t = pg.evaluate(rows)
    ok("undefined" not in t.lower() and "Object" not in t, "105: arkistojuttu kanavalla 'constructor' ei kaadu", t[:200])
    # 13. selaimen .ics on taitettu
    ics = pg.evaluate("window.LAKITV.icsText(window.LAKITV.kalEventsUpcoming(30))")
    ok(ics and all(len(l.encode()) <= 75 for l in ics.split("\r\n")) and ics.replace("\r\n ", "").count("BEGIN:VEVENT") >= 1, "icsText: rivit ≤ 75 oktettia", max(len(l.encode()) for l in ics.split("\r\n")))
    # 14. palautuslaskuri nollautuu
    ok(pg.evaluate("sessionStorage.getItem('lakitv:recover')") is None, "lakitv:recover tyhjä onnistuneen käynnistyksen jälkeen")
    # 16. 720 sv: SuV ei törmää päivämäärään
    pg.evaluate("window.__ovl = []; window.LAKITV.setLang('sv')"); pg.wait_for_timeout(100)
    t = "\n".join(pg.evaluate(allsubs(720)))
    ok("Sto" in t and not pg.evaluate("window.__ovl.length"), "720 sv: valiokunta ja päivämäärä eivät mene päällekkäin", pg.evaluate("window.__ovl")[:3])
    pg.evaluate("window.LAKITV.setLang('fi')")
    # 17. JAKELU kaukosäätimestä ei näytä vanhaa valintaa
    pg.evaluate("const pn = document.getElementById('panel'); if (pn.open) pn.close(); window.LAKITV.show(740,0,true)"); pg.wait_for_timeout(100)
    n = pg.evaluate("[...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it && window.LAKITV.itemIndexGet(n).it.maaraaika > %s)" % json.dumps(today.isoformat()))
    if n:
        link = None
        for sub in range(pg.evaluate(f"window.LAKITV.getPage({n}).subs.length")):
            pg.evaluate(f"window.LAKITV.show({n},{sub},true)"); pg.wait_for_timeout(100)
            link = pg.query_selector("#rows a[data-act='kal']")
            if link: break
        if link:
            link.click(); pg.wait_for_timeout(300)
            had = "VALITTU" in pg.inner_text("#paneKal").upper(); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            pg.click("#kSub"); pg.wait_for_timeout(300)
            ok(had and "VALITTU" not in pg.inner_text("#paneKal").upper(), "JAKELU kaukosäätimestä: ei vanhaa Valittu-tapahtumaa"); pg.keyboard.press("Escape")
        else: ok(False, "KALENTERIIN-linkki puuttuu")
    else: print("skip 17: ei tulevaa määräaikaa")
    # 10. tulostus-CSS
    ok(pg.evaluate("[...document.styleSheets].some(s => { try { return [...s.cssRules].some(r => r.media && [...r.media].includes('print')); } catch (e) { return false; } })"), "print-mediasäännöt löytyvät")
    ok(not errs, "ei JS-virheitä", errs[:3])
    b.close()
print(f"{len(fails)} virhettä" if fails else "KAIKKI OK")
sys.exit(1 if fails else 0)
