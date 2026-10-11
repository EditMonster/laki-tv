"""Toiminnallisuustestit oikeilla näppäin-, hiiri- ja kosketustapahtumilla."""
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import json
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))   # testikello: tänään klo 21 Helsinki
URL = "file://" + ROOT + "/test/fixture.html"
results = []
def check(name, cond, info=""):
    results.append(("OK  " if cond else "FAIL") + " " + name + (f"  [{info}]" if info and not cond else ""))
cur = lambda pg: pg.evaluate("window.LAKITV.state.current")
sub = lambda pg: pg.evaluate("window.LAKITV.state.sub")
row = lambda pg, i: pg.evaluate(f"document.querySelectorAll('#rows .row')[{i}].textContent")
def all_text(pg):
    n = pg.evaluate("(() => { const L = window.LAKITV; const c = L.state.current; const s = L.state.sub; const pgx = document.getElementById('rmNow').textContent.match(/\\/(\\d+)/); return pgx ? +pgx[1] : 1; })()")
    c = cur(pg); out = []
    for s in range(n):
        pg.evaluate(f"window.LAKITV.show({c},{s},true)")
        out.append(screen_text(pg))
    pg.evaluate(f"window.LAKITV.show({c},0,true)")
    return "\n".join(out)
screen_text = lambda pg: pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r=>r.textContent).join('\\n')")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(400)
    check("aloitus etusivulla", cur(pg) == 100)
    check("isot kirjaimet oletuksena", pg.evaluate("document.getElementById('rows').classList.contains('caps')"))
    check("LakiCaps käytössä", "LakiCaps" in pg.evaluate("getComputedStyle(document.getElementById('rows')).fontFamily"))
    # näppäimistö: sivunumero
    pg.keyboard.type("201"); pg.wait_for_timeout(400)
    check("näppäily 201", cur(pg) == 201, cur(pg))
    check("header näyttää P201", row(pg, 0).startswith("P201"), row(pg, 0))
    # nolla alussa ei aloita numeroa
    pg.keyboard.type("0"); pg.wait_for_timeout(100)
    check("0 alussa ohitetaan", row(pg, 0).startswith("P201"), row(pg, 0))
    # kaukosäädin numeronäppäimet
    for d in "300": pg.click(f"[data-d='{d}']")
    pg.wait_for_timeout(400)
    check("kaukosäädin 300", cur(pg) == 300, cur(pg))
    # takaisin
    pg.keyboard.press("Backspace"); pg.wait_for_timeout(400)
    check("Backspace takaisin 201", cur(pg) == 201, cur(pg))
    pg.click("#kBack"); pg.wait_for_timeout(400)
    check("TAKAISIN-näppäin 100", cur(pg) == 100, cur(pg))
    # linkin klikkaus etusivulla (ensimmäinen pääuutinen)
    first = pg.evaluate("+document.querySelector('#rows .row:nth-child(8) a[data-p]').dataset.p")
    pg.click("#rows .row:nth-child(8) a[data-p]"); pg.wait_for_timeout(400)
    check("pääuutisen linkki", cur(pg) == first, (cur(pg), first))
    # fastext
    pg.click("#kIndex"); pg.wait_for_timeout(300)
    pg.click("[data-ft='1']"); pg.wait_for_timeout(400)
    check("vihreä näppäin etusivulta -> 102", cur(pg) == 102, cur(pg))
    for k in "800": pg.keyboard.press(k)
    pg.wait_for_timeout(400)
    pg.keyboard.press("r"); pg.wait_for_timeout(400)
    check("R-näppäin 800 -> 801", cur(pg) == 801, cur(pg))
    # P+ / P-
    pg.click("#kPp"); pg.wait_for_timeout(400)
    check("P+ 801 -> 802", cur(pg) == 802, cur(pg))
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(400)
    check("Nuoli alas 802 -> 801", cur(pg) == 801, cur(pg))
    # alasivut
    pg.keyboard.type("190"); pg.wait_for_timeout(400)
    n = pg.evaluate("window.LAKITV.getPage(190).subs.length")
    check("190 on useampi alasivu", n >= 2, n)
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(100)
    check("ArrowRight alasivu 2", sub(pg) == 1, sub(pg))
    check("alasivun ilmaisin", "2/" in row(pg, 3), row(pg, 3))
    pg.click("#kSubPrev"); pg.wait_for_timeout(100)
    check("◀ ALA alasivu 1", sub(pg) == 0, sub(pg))
    # SEURAA-näppäin avaa sivun 108
    pg.click("#kFollow"); pg.wait_for_timeout(200)
    check("SEURAA-näppäin -> 108", cur(pg) == 108, cur(pg))
    pg.keyboard.type("802"); pg.wait_for_timeout(300)
    # SIZE
    pg.keyboard.press("s"); c1 = pg.evaluate("document.getElementById('rows').className")
    pg.keyboard.press("s"); c2 = pg.evaluate("document.getElementById('rows').className")
    pg.keyboard.press("s"); c3 = pg.evaluate("document.getElementById('rows').className")
    check("SIZE kiertää 1-2-0", "size1" in c1 and "size2" in c2 and "size" not in c3.replace("caps", ""), (c1, c2, c3))
    # REVEAL
    pg.keyboard.type("150"); pg.wait_for_timeout(400)
    hidden = pg.evaluate("getComputedStyle(document.querySelector('#rows .cc')).color")
    pg.keyboard.press("?"); shown = pg.evaluate("getComputedStyle(document.querySelector('#rows .cc')).color")
    check("REVEAL paljastaa", hidden == "rgba(0, 0, 0, 0)" and shown != hidden, (hidden, shown))
    pg.keyboard.type("101"); pg.wait_for_timeout(400)
    check("REVEAL nollautuu sivua vaihtaessa", not pg.evaluate("document.getElementById('rows').classList.contains('reveal')"))
    # 888 viimeksi avatusta jutusta
    pg.keyboard.type("261"); pg.wait_for_timeout(400)
    pg.click("#k888"); pg.wait_for_timeout(400)
    t = screen_text(pg)
    check("888 näyttää EIT-jutun selkokielellä", cur(pg) == 888 and "SIVU 261" in t.upper(), t[:200])
    # EIT-kohdesivu: vaihe ja aiheet
    pg.keyboard.type("264"); pg.wait_for_timeout(400)
    t = all_text(pg)
    check("EIT vireillä-juttu näyttää VAIHE", "VAIHE" in t.upper() and "VIREILL" in t.upper(), t[:300])
    check("aiherivi kohdesivulla", "AIHEET" in t.upper() and "867" in t, "")
    # aihesivun linkki kohdesivulta
    pg.evaluate("(function(){ const L = window.LAKITV, n = L.getPage(264).subs.length; for (let i = 0; i < n; i++) { L.show(264, i); if (document.querySelector('#rows a[data-p=\"867\"]')) return i; } })()"); pg.wait_for_timeout(200)
    pg.click("#rows a[data-p='867']"); pg.wait_for_timeout(400)
    check("aiheen linkki -> 867", cur(pg) == 867, cur(pg))
    # tyhjä kanavapaikka
    pg.keyboard.type("233"); pg.wait_for_timeout(400)
    t = screen_text(pg)
    check("vapaa paikka 233: kuva + päivän termi", "PÄIVÄN TERMI" in t.upper() and "SIVU 233" in t.upper(), t[:200])
    # Kirjainkoko
    pg.keyboard.press("c")
    check("C vaihtaa pienet kirjaimet", not pg.evaluate("document.getElementById('rows').classList.contains('caps')"))
    pg.reload(); pg.wait_for_timeout(400)
    check("kirjainkoko muistetaan", not pg.evaluate("document.getElementById('rows').classList.contains('caps')"))
    check("hash-linkki säilyy reloadissa", cur(pg) == 233, cur(pg))
    pg.click("#kCase")
    check("ABC-näppäin palauttaa isot", pg.evaluate("document.getElementById('rows').classList.contains('caps')"))
    # Aihesuodatin
    pg.click("#kTopics"); pg.wait_for_timeout(200)
    check("AIHEET avaa paneelin", pg.evaluate("document.getElementById('panel').open"))
    check("aihe-välilehti valittuna", pg.evaluate("!document.getElementById('paneTopics').hidden"))
    pg.click("label[for='t-sote']"); pg.wait_for_timeout(150)
    pg.click("label[for='t-tyo']"); pg.wait_for_timeout(150)
    check("suodatin tallessa", pg.evaluate("[...window.LAKITV.state.filter].sort().join()") == "sote,tyo")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
    check("Esc sulkee paneelin", not pg.evaluate("document.getElementById('panel').open"))
    check("header AIHE", "AIHE" in row(pg, 0), row(pg, 0))
    check("kaukosäätimen suodatinmerkki", pg.evaluate("!document.getElementById('rmFilter').hidden"))
    pg.keyboard.type("200"); pg.wait_for_timeout(400)
    t = screen_text(pg)
    check("KKO suodatettuna: vain TYÖ/SOTE-jutut", "IRTISANOTULLE" in t.upper() and "PETOKSESTA" not in t.upper(), t[:500])
    pg.keyboard.type("110"); pg.wait_for_timeout(400)
    t = all_text(pg)
    check("110 listaa omat aiheet", "OMAT AIHEET" in t.upper() and "TERVEYSTALO" in t.upper(), t[:400])
    pg.keyboard.type("100"); pg.wait_for_timeout(400)
    t = screen_text(pg)
    check("etusivu suodatettuna", "OMAT AIHEET" in t.upper(), t[:400])
    pg.reload(); pg.wait_for_timeout(400)
    check("suodatin muistetaan", pg.evaluate("window.LAKITV.state.filter.size") == 2)
    pg.click("#rmFilterClear"); pg.wait_for_timeout(150)
    check("Poista-näppäin tyhjentää", pg.evaluate("window.LAKITV.state.filter.size") == 0 and "AIHE" not in row(pg, 0))
    # Kanavaluettelo-paneeli
    pg.keyboard.press("l"); pg.wait_for_timeout(200)
    check("L avaa kanavaluettelon", pg.evaluate("document.getElementById('panel').open && !document.getElementById('paneList').hidden"))
    pg.click("#paneList button[data-go='270']"); pg.wait_for_timeout(400)
    check("luettelosta ICJ 270", cur(pg) == 270 and not pg.evaluate("document.getElementById('panel').open"), cur(pg))
    # hash-navigointi
    pg.evaluate("location.hash = '#p853'"); pg.wait_for_timeout(500)
    check("hashchange -> 853", cur(pg) == 853, cur(pg))
    # alasivut eivät vaihdu itsestään
    pg.keyboard.type("802"); pg.wait_for_timeout(400)
    pg.mouse.move(5, 5); pg.wait_for_timeout(2200)
    check("alasivut eivät kierrä itsestään", sub(pg) == 0, sub(pg))
    check("ei JS-virheitä", not errs, errs)
    ctx.close()

    # Mobiili ja kosketus
    m = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
    mp = m.new_page(); errs2 = []
    mp.on("pageerror", lambda e: errs2.append(str(e)))
    mp.goto(URL + "#p190"); mp.wait_for_timeout(500)
    check("mobiili: ei vaakavieritystä", mp.evaluate("document.documentElement.scrollWidth <= innerWidth"), mp.evaluate("[document.documentElement.scrollWidth, innerWidth]"))
    swipe = """(dx) => { const s = document.getElementById('screen'); const r = s.getBoundingClientRect();
      const mk = (x) => new Touch({identifier: 1, target: s, clientX: x, clientY: r.top + 100});
      s.dispatchEvent(new TouchEvent('touchstart', {changedTouches:[mk(r.left + 200)], touches:[mk(r.left + 200)], bubbles:true}));
      s.dispatchEvent(new TouchEvent('touchend', {changedTouches:[mk(r.left + 200 + dx)], touches:[], bubbles:true})); }"""
    mp.evaluate(swipe, -120); mp.wait_for_timeout(200)
    check("pyyhkäisy vasemmalle -> alasivu 2", sub(mp) == 1, sub(mp))
    mp.evaluate("window.LAKITV.show(200, 0)"); mp.wait_for_timeout(100)
    mp.evaluate(swipe, -120); mp.wait_for_timeout(400)
    check("pyyhkäisy yksisivuisella -> seuraava sivu", cur(mp) > 200, cur(mp))
    mp.tap("[data-d='8']"); mp.tap("[data-d='0']"); mp.tap("[data-d='1']"); mp.wait_for_timeout(400)
    check("mobiili napautus 801", cur(mp) == 801, cur(mp))
    mp.tap("#kList"); mp.wait_for_timeout(300)
    box = mp.evaluate("(() => { const r = document.getElementById('panel').getBoundingClientRect(); return [r.left, r.width, r.bottom, innerHeight]; })()")
    check("mobiili: paneeli alareunan arkkina", abs(box[0]) < 1 and abs(box[2] - box[3]) < 2, box)
    check("mobiili: ei JS-virheitä", not errs2, errs2)
    m.close(); b.close()
print("\n".join(results))
print(sum(r.startswith("OK") for r in results), "/", len(results), "OK")
