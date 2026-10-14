# Yhden sivun juttusivu: validate-työkalun rivibudjetti (item_rows) vastaa sivun buildItem-asettelua kaikilla kielillä,
# ja tiivis asettelu toimii (ei toistuvaa elin-riviä, UUSI kaistalla, lopputulos samassa lohkossa, toiminto- ja lähderivi).
from playwright.sync_api import sync_playwright
import os as _os, sys, json, copy, importlib.util
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))
spec = importlib.util.spec_from_file_location("lakitv", _os.path.join(_ROOT, "tools", "lakitv.py")); L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
ok = 0; fail = 0
def check(name, cond, info=""):
    global ok, fail
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {str(info)[:300]}"))
    ok += bool(cond); fail += (not cond)

D = json.load(open(_os.path.join(_ROOT, "test", "fixture_data.json"), encoding="utf-8"))
rows_js = "[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')"
# kaikki alasivut (vanhat pitkät jutut jakautuvat yhä alasivuihin)
def all_rows(pg, n):
    return pg.evaluate("""(n) => { const L = window.LAKITV; let t = ''; const k = L.getPage(n).subs.length;
        for (let s = 0; s < k; s++) { L.show(n, s, true); t += [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n') + '\\n'; }
        L.show(n, 0, true); return t; }""", n)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900}); pg.clock.set_fixed_time(_FIXED)
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file://" + _ROOT + "/test/fixture.html"); pg.wait_for_timeout(700)

    # 1. Python-budjetti == sivun alasivumäärä (1 sivu <=> <= 23 riviä) jokaiselle jutulle ja kielelle
    diffs = []; n = 0
    for lang in ("fi", "sv", "en"):
        pg.evaluate(f"window.LAKITV.setLang('{lang}')"); pg.wait_for_timeout(150)
        js = pg.evaluate("""() => { const L = window.LAKITV, out = {};
            for (const ch of L.CHANNELS) for (let i = 0; i < 9; i++) { const x = L.itemIndexGet(ch.page + i + 1); if (x) out[x.it.id] = L.getPage(ch.page + i + 1).subs.length; }
            return out; }""")
        for k, items in D["kanavat"].items():
            for it in items:
                if it["id"] not in js: continue
                n += 1
                need = L.item_rows(it, k, D, lang)
                if (need <= 23) != (js[it["id"]] == 1): diffs.append((lang, it["id"], need, js[it["id"]]))
    check(f"rivibudjetti vastaa sivua ({n} juttu-kieliparia)", n > 100 and not diffs, diffs[:5])
    pg.evaluate("window.LAKITV.setLang('fi')"); pg.wait_for_timeout(150)

    # 2. KKO-juttu: ei toistuvaa "KORKEIN OIKEUS" -riviä, lopputulos samassa lohkossa, toimintorivi ja lähderivi
    pg.evaluate("window.LAKITV.show(201, 0)"); pg.wait_for_timeout(200)
    t = all_rows(pg, 201); lines = [l.rstrip() for l in t.split("\n")]
    nsub = pg.evaluate("window.LAKITV.getPage(201).subs.length")
    check("201: kaista joka alasivulla, ei elin-riviä toistona", sum(1 for l in lines if "KORKEIN OIKEUS" in l) == nsub, [l for l in lines if "KORKEIN OIKEUS" in l])
    pg.evaluate("window.LAKITV.show(201, 0)")
    kko = D["kanavat"]["kko"][0]
    if kko.get("lopputulos"):
        check("201: LOPPUTULOS: samalla rivillä tekstin kanssa", any(l.strip().startswith("LOPPUTULOS:") for l in lines), lines[8:16])
    check("201: toimintorivi SEURAA ASIAA", any("SEURAA ASIAA" in l for l in lines))
    check("201: lähderivi LÄHDE ▶ ja PALAUTE ▶", any("LÄHDE" in l and "PALAUTE" in l for l in lines), lines[-2:])
    check("201: ei erillistä SELKEÄLLÄ KIELELLÄ- tai ILMOITA VIRHEESTÄ -riviä", not any("SELKEÄLLÄ KIELELLÄ" in l or "ILMOITA VIRHEESTÄ" in l for l in lines))
    check("201: tyyppirivi ilman sanamäärää", any("TIIVISTELMÄ" in l.upper() and "SANAA" not in l.upper() for l in lines[6:]), lines)
    pg.evaluate("window.LAKITV.show(201, window.LAKITV.getPage(201).subs.length - 1, true)"); pg.wait_for_timeout(100)
    fb = pg.evaluate("[...document.querySelectorAll('#rows a[href]')].map(a => a.href).filter(h => h.includes('/issues'))")
    check("201: palautelinkki osoittaa GitHub-issueihin", len(fb) == 1, fb)

    # 3. uusi juttu: UUSI vilkkuu kaistalla, ei omalla rivillä
    fresh = pg.evaluate("""() => { const L = window.LAKITV; for (const ch of L.CHANNELS) for (let i = 0; i < 9; i++) { const n = ch.page + i + 1, x = L.itemIndexGet(n);
        if (x && (Date.now() - Date.parse((x.it.julkaistu || '').length === 10 ? x.it.julkaistu + 'T06:00:00+03:00' : (x.it.julkaistu || '') + ':00+03:00')) / 36e5 <= 24) return n; } return null; }""")
    if fresh:
        pg.evaluate(f"window.LAKITV.show({fresh}, 0)"); pg.wait_for_timeout(200)
        first = pg.evaluate("document.querySelectorAll('#rows .row')[1].textContent")
        check(f"{fresh}: UUSI kaistalla", "UUSI" in first, first)
        check(f"{fresh}: UUSI vilkkuu", pg.evaluate("!!document.querySelectorAll('#rows .row')[1].querySelector('.fl')"))
    else:
        print("skip: ei tuoretta juttua")

    # 4. lausuntokierros: tunnuksen sisältämä päivä ei toistu, kalenterilinkki toimintorivillä oikealla
    laus = pg.evaluate("""() => { const L = window.LAKITV; for (let i = 0; i < 9; i++) { const x = L.itemIndexGet(741 + i); if (x && x.it.maaraaika >= new Date().toISOString().slice(0, 10)) return 741 + i; } return null; }""")
    if laus:
        pg.evaluate(f"window.LAKITV.show({laus}, 0)"); pg.wait_for_timeout(200)
        t = all_rows(pg, laus); lines = t.split("\n")
        check(f"{laus}: KALENTERIIN samalla rivillä kuin SEURAA ASIAA", any("SEURAA ASIAA" in l and "KALENTERIIN" in l for l in lines), [l for l in lines if "SEURAA" in l or "KALENTERIIN" in l])
        tun = pg.evaluate(f"window.LAKITV.itemIndexGet({laus}).it.tunnus")
        dup = [l for l in lines if l.strip().lower() in tun.lower() and l.strip().lower().startswith("tiedote ")]
        check(f"{laus}: tunnuksen sisältämä päivä ei toistu omana rivinään", not dup, dup)
    else:
        print("skip: ei avointa lausuntokierrosta")

    # 5. validate: uudelle (lisatty >= ONE_PAGE_SINCE) pitkälle jutulle YLI SIVUN -virhe, vanhalle vain yhteenveto
    long_item = max((it for lst in D["kanavat"].values() for it in lst), key=lambda it: len(it.get("teksti") or ""))
    d2 = copy.deepcopy(D)
    for lst in d2["kanavat"].values():
        for it in lst:
            if it["id"] == long_item["id"]: it["lisatty"] = L.ONE_PAGE_SINCE + "T06:50"
    E, W = L.validate(d2)
    check("validate: uusi pitkä juttu -> YLI SIVUN -virhe", any(e.startswith("YLI SIVUN") and long_item["id"] in e for e in E), E[:3])
    E0, W0 = L.validate(D)
    check("validate: vanhat jutut -> ei YLI SIVUN -virheitä, yhteenvetohuomautus", not any("YLI SIVUN" in e for e in E0) and any("ei mahdu yhdelle sivulle" in w for w in W0), (E0[:2], W0[-1:]))
    check("ei JS-virheitä", not errs, errs)
    b.close()
print(f"{ok} / {ok + fail} OK")
sys.exit(1 if fail else 0)
