# Suora data: julkaistu sivusto hakee uusimman data.jsonin datavarastosta (meta lakitv-data) ja ottaa uudemman käyttöön.
# Testi rakentaa sivuston kopion kiinteästä testisivusta (tools/website.py --data-url) ja syöttää datavaraston vastaukset
# Playwrightin reitityksellä, joten verkkoa ei tarvita.
from playwright.sync_api import sync_playwright
import os as _os, sys, json, copy, subprocess, shutil, tempfile
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))
LIVE = "https://live.test/data.json"
ok = 0; fail = 0
def check(name, cond, info=""):
    global ok, fail
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))
    ok += bool(cond); fail += (not cond)

FIX = json.load(open(_os.path.join(_ROOT, "test", "fixture_data.json"), encoding="utf-8"))
def newer(bump_items=0):
    d = copy.deepcopy(FIX)
    d["paivitetty"] = FIX["paivitetty"][:11] + "09:30:00+03:00"
    k = next(iter(d["kanavat"]))
    for i in range(bump_items):
        it = copy.deepcopy(d["kanavat"][k][0]); it["id"] = f"live-{i}"; it["otsikko"] = f"Suoran datan testijuttu {i}"
        d["kanavat"][k].insert(0, it)
    return d
def older():
    d = copy.deepcopy(FIX); d["paivitetty"] = "2020-01-01T06:00:00+02:00"; return d
def tiny():
    d = newer(); d["kanavat"] = {k: v[:1] for k, v in list(d["kanavat"].items())[:1]}; return d

tmp = tempfile.mkdtemp(prefix="lakitv-live-")
# 1. website.py: --data-url kirjoittaa metan, väärä osoite hylätään
r = subprocess.run([sys.executable, _os.path.join(_ROOT, "tools", "website.py"), "--page", _os.path.join(_ROOT, "test", "fixture.html"),
                    "--feeds", _os.path.join(_ROOT, "out"), "--out", tmp, "--base", "https://sivusto.test/", "--data-url", LIVE], capture_output=True, text=True)
check("website.py rakentaa --data-url:lla", r.returncode == 0, r.stderr[-300:])
html = open(_os.path.join(tmp, "index.html"), encoding="utf-8").read()
check("meta lakitv-data sivustolla", f'<meta name="lakitv-data" content="{LIVE}">' in html)
r2 = subprocess.run([sys.executable, _os.path.join(_ROOT, "tools", "website.py"), "--page", _os.path.join(_ROOT, "test", "fixture.html"),
                     "--feeds", _os.path.join(_ROOT, "out"), "--out", tmp + "-x", "--base", "https://sivusto.test/", "--data-url", "http://ei-salattu/data.json"], capture_output=True, text=True)
check("http-osoite hylätään", r2.returncode != 0 and "https" in r2.stderr)
r3 = subprocess.run([sys.executable, _os.path.join(_ROOT, "tools", "website.py"), "--page", _os.path.join(_ROOT, "test", "fixture.html"),
                     "--feeds", _os.path.join(_ROOT, "out"), "--out", tmp + "-y", "--base", "https://sivusto.test/"], capture_output=True, text=True)
check("ilman --data-url ei metaa", r3.returncode == 0 and '<meta name="lakitv-data" content=' not in open(_os.path.join(tmp + "-y", "index.html"), encoding="utf-8").read())
SITE = "file://" + _os.path.join(tmp, "index.html")
PLAIN = "file://" + _os.path.join(_ROOT, "test", "fixture.html")

with sync_playwright() as p:
    b = p.chromium.launch()
    def fresh(serve, delay_ms=0, status=200, body=None):
        """Uusi selainkonteksti, jossa datavaraston osoite vastaa annetulla datalla."""
        ctx = b.new_context(viewport={"width": 1400, "height": 900})
        pg = ctx.new_page(); pg.clock.set_fixed_time(_FIXED)
        hits = []
        def handle(route, req):
            hits.append(req.url)
            if delay_ms: pg.wait_for_timeout(delay_ms)
            route.fulfill(status=status, content_type="text/plain; charset=utf-8", headers={"Access-Control-Allow-Origin": "*"},
                          body=body if body is not None else json.dumps(serve, ensure_ascii=False))
        ctx.route("https://live.test/**", handle)
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        return ctx, pg, hits, errs
    stamp = lambda pg: pg.evaluate("window.LAKITV.dataStamp()")

    # 2. ilman metaa (artifact / paikallinen kopio) ei haeta mitään
    ctx, pg, hits, errs = fresh(newer(2))
    pg.goto(PLAIN); pg.wait_for_timeout(900)
    check("ilman metaa liveSrc tyhjä", pg.evaluate("window.LAKITV.liveSrc()") == "")
    check("ilman metaa ei hakua", len(hits) == 0, hits)
    check("ilman metaa data = upotettu", stamp(pg) == FIX["paivitetty"], stamp(pg))
    ctx.close()

    # 3. uudempi data: sivu latautuu heti uudelleen ja näyttää uuden datan, TILA-sivulla SUORA
    ctx, pg, hits, errs = fresh(newer(2))
    pg.goto(SITE + "#p198"); pg.wait_for_timeout(1500)
    check("datavarastoa haettiin latauksessa ja uudelleenlatauksessa", len(hits) == 2 and all(h.startswith(LIVE + "?v=") for h in hits), hits)
    check("uudempi data käytössä", stamp(pg) == newer()["paivitetty"], stamp(pg))
    check("dataLive true", pg.evaluate("window.LAKITV.dataLive()") is True)
    check("sivu säilyi (198)", pg.evaluate("window.LAKITV.state.current") == 198, pg.evaluate("window.LAKITV.state.current"))
    txt = pg.inner_text("#rows")
    check("TILA näyttää SUORA", "SUORA" in txt, txt[:200])
    pg.keyboard.press("/"); pg.wait_for_timeout(250); pg.fill("#q", "Suoran datan testijuttu"); pg.wait_for_timeout(400)
    check("uusi juttu löytyy haulla", pg.evaluate("document.querySelectorAll('#qResults button').length") >= 1, pg.inner_text("#qCount"))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("ei JS-virheitä", not errs, errs)
    # sama välilehti uudelleen: sessionStoragen kopio käytössä heti, hakuja tehdään silti (uudempaa ei tule)
    hits.clear(); pg.goto(SITE); pg.wait_for_timeout(1200)
    check("uudelleenlataus: suora data heti", stamp(pg) == newer()["paivitetty"] and pg.evaluate("window.LAKITV.dataLive()") is True)
    check("uudelleenlataus: yksi haku, ei toista reloadia", len(hits) == 1, hits)
    ctx.close()

    # 4. vanhempi data ei korvaa
    ctx, pg, hits, errs = fresh(older())
    pg.goto(SITE); pg.wait_for_timeout(1200)
    check("vanhempi data ei korvaa", stamp(pg) == FIX["paivitetty"] and pg.evaluate("window.LAKITV.dataLive()") is False)
    check("vanhempaa ei talleteta", pg.evaluate("sessionStorage.getItem('lakitv:live')") is None)
    ctx.close()

    # 5. rikkinäinen tai liian pieni data hylätään
    ctx, pg, hits, errs = fresh(None, body="{ei json")
    pg.goto(SITE); pg.wait_for_timeout(1200)
    check("rikkinäinen JSON hylätään", stamp(pg) == FIX["paivitetty"] and not errs, errs)
    ctx.close()
    ctx, pg, hits, errs = fresh(tiny())
    pg.goto(SITE); pg.wait_for_timeout(1200)
    check("alle puolet jutuista -> hylätään", stamp(pg) == FIX["paivitetty"], stamp(pg))
    ctx.close()
    bad = newer(); bad["kanavat"][next(iter(bad["kanavat"]))][0]["otsikko"] = 5
    ctx, pg, hits, errs = fresh(bad)
    pg.goto(SITE); pg.wait_for_timeout(1200)
    check("väärä kenttätyyppi -> hylätään", stamp(pg) == FIX["paivitetty"], stamp(pg))
    ctx.close()
    ctx, pg, hits, errs = fresh(None, status=500, body="virhe")
    pg.goto(SITE); pg.wait_for_timeout(1200)
    check("palvelinvirhe -> upotettu data", stamp(pg) == FIX["paivitetty"] and not errs, errs)
    ctx.close()

    # 6. lukija ehti toimia: ei välitöntä reloadia, uusi data seuraavassa sivunvaihdossa
    ctx, pg, hits, errs = fresh(newer(1), delay_ms=700)
    pg.goto(SITE); pg.wait_for_timeout(200)
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)   # lukija selaa ennen vastausta
    before = pg.evaluate("window.LAKITV.state.current")
    pg.wait_for_timeout(1200)
    check("selailun jälkeen ei välitöntä reloadia", stamp(pg) == FIX["paivitetty"] and pg.evaluate("window.LAKITV.state.current") == before, stamp(pg))
    check("uusi data odottaa sessionStoragessa", pg.evaluate("!!sessionStorage.getItem('lakitv:live')"))
    pg.evaluate("window.LAKITV.go(101)"); pg.wait_for_timeout(1200)
    check("sivunvaihto ottaa uuden datan käyttöön", stamp(pg) == newer()["paivitetty"] and pg.evaluate("window.LAKITV.state.current") == 101, (stamp(pg), pg.evaluate("window.LAKITV.state.current")))
    check("ei JS-virheitä (viivästetty)", not errs, errs)
    ctx.close()

    # 7. dataOk-tarkistus suoraan
    ctx, pg, hits, errs = fresh(older())
    pg.goto(PLAIN); pg.wait_for_timeout(600)
    checks = pg.evaluate("""() => { const f = window.LAKITV.dataOk; return [
        f(null), f({}), f({paivitetty:'2026-10-13T06:00:00+03:00', kanavat:[]}), f({paivitetty:'x', kanavat:{a:[]}}),
        f({paivitetty:'2026-10-13T06:00:00+03:00', kanavat:{a:[]}}),
        f({paivitetty:'2026-10-13T06:00:00+03:00', kanavat:{a:[{id:'1', otsikko:'t'}]}}),
        f({paivitetty:'2026-10-13T06:00:00+03:00', kanavat:{a:[{id:1, otsikko:'t'}]}}) ]; }""")
    check("dataOk hylkää väärät rakenteet", checks == [False, False, False, False, False, True, False], checks)
    ctx.close()
    b.close()
shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(tmp + "-x", ignore_errors=True); shutil.rmtree(tmp + "-y", ignore_errors=True)
print(f"{ok} / {ok + fail} OK")
sys.exit(1 if fail else 0)
