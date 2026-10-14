# Juttu on yksi sivu (ei alasivuja): tiivistelmä mahtuu sivulle tai katkaistaan kolmeen pisteeseen; validate-työkalun rivibudjetti
# item_rows vastaa sivun katkaisua. NÄYTÄ LÄHDETIEDOT (▶-näppäin) avaa samalle numerolle asiasanat, aiheet, seurannan, kalenterin,
# lähteen ja palautteen. Tekoälymaininta ei ole jutuissa vaan ohjeessa 199.
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
rows_js = "[...document.querySelectorAll('#rows .row')].map(r => r.textContent)"
def goto(pg, n): pg.evaluate(f"window.LAKITV.show({n}, 0)"); pg.wait_for_timeout(120); return pg.evaluate(rows_js)
def detail(pg, n):
    pg.evaluate(f"window.LAKITV.show({n}, 0)"); pg.wait_for_timeout(80)
    pg.click("a[data-act='detail']"); pg.wait_for_timeout(150); return pg.evaluate(rows_js)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900}); pg.clock.set_fixed_time(_FIXED)
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file://" + _ROOT + "/test/fixture.html"); pg.wait_for_timeout(700)

    # 1. jokainen juttu on yksi sivu; Python-budjetti == sivun katkaisu (mahtuu <=> ei katkaistu) kaikilla kielillä
    diffs = []; n = 0; subs_bad = []
    for lang in ("fi", "sv", "en"):
        pg.evaluate(f"window.LAKITV.setLang('{lang}')"); pg.wait_for_timeout(150)
        js = pg.evaluate("""() => { const L = window.LAKITV, out = {};
            for (const ch of L.CHANNELS) for (let i = 0; i < 9; i++) { const x = L.itemIndexGet(ch.page + i + 1); if (!x) continue; const p = L.getPage(ch.page + i + 1);
              out[x.it.id] = {subs: p.subs.length, trunc: !!p.truncated, detail: !!p.detail}; }
            return out; }""")
        for k, items in D["kanavat"].items():
            for it in items:
                j = js.get(it["id"])
                if not j: continue
                n += 1
                if j["subs"] != 1 or not j["detail"]: subs_bad.append((lang, it["id"], j))
                if (L.item_rows(it, k, D, lang) <= 23) != (not j["trunc"]): diffs.append((lang, it["id"], L.item_rows(it, k, D, lang), j))
    check(f"jokainen juttu on yksi sivu ja sillä on lähdetiedot ({n} juttu-kieliparia)", n > 100 and not subs_bad, subs_bad[:3])
    check("rivibudjetti vastaa sivun katkaisua", not diffs, diffs[:5])
    pg.evaluate("window.LAKITV.setLang('fi')"); pg.wait_for_timeout(150)

    # 2. 201: tiivistelmäsivu ilman lisätietoja, alarivillä NÄYTÄ LÄHDETIEDOT; lähdetiedoissa asiasanat, aiheet, seuranta, lähde, palaute
    kko = D["kanavat"]["kko"][0]
    first = goto(pg, 201)
    check("201: tekstin alku sivulla", any(kko["teksti"][:20].upper() in l.upper() for l in first), first[4:8])
    check("201: ei asiasanoja, aiheita, seurantaa eikä lähdettä tiivistelmäsivulla", not any(any(w in l for w in ("ASIASANAT", "AIHEET", "SEURAA ASIAA", "LÄHDE ▶")) for l in first[:23]))
    check("201: alarivi NÄYTÄ LÄHDETIEDOT · SEURAA ASIAA ▶", "NÄYTÄ LÄHDETIEDOT" in first[23] and "SEURAA ASIAA" in first[23] and "▶" in first[23], first[23])
    if kko.get("lopputulos"):
        check("201: LOPPUTULOS: tiivistelmäsivulla", any(l.strip().startswith("LOPPUTULOS:") for l in first))
    check("201: ei 1/2-merkintää kaistalla", "/" not in first[1].split("  ")[-1] and "1/" not in first[1], first[1])
    det = detail(pg, 201)
    check("201: lähdetiedot avautuu samalle numerolle", pg.evaluate("window.LAKITV.state.current") == 201 and pg.evaluate("window.LAKITV.state.detail") is True)
    check("201: lähdetiedot: kaista LÄHDETIEDOT, ASIASANAT, AIHEET, SEURAA ASIAA", "LÄHDETIEDOT" in det[1] and all(any(w in l for l in det) for w in ("ASIASANAT", "AIHEET", "SEURAA ASIAA")), det)
    check("201: lähdetiedot: LÄHDE ▶ ja PALAUTE ▶ alarivillä, ◀ TAKAISIN JUTTUUN", "LÄHDE" in det[23] and "PALAUTE" in det[23] and any("TAKAISIN JUTTUUN" in l for l in det), det[21:24])
    fb = pg.evaluate("[...document.querySelectorAll('#rows a[href]')].map(a => a.href).filter(h => h.includes('/issues'))")
    check("201: palautelinkki osoittaa GitHub-issueihin", len(fb) == 1, fb)
    if kko.get("tekstityyppi") == "virallinen tiivistelmä":
        check("201: virallinen tiivistelmä merkitty vain lähdetiedoissa", any("VIRALLINEN TIIVISTELMÄ" in l.upper() for l in det) and not any("VIRALLINEN" in l.upper() for l in first))
    check("201: ei tekoälymainintaa jutussa", not any("TEKOÄLY" in l.upper() for l in first + det))
    pg.click("a[data-act='detail']"); pg.wait_for_timeout(150)
    check("201: TAKAISIN JUTTUUN palaa tiivistelmään", pg.evaluate("window.LAKITV.state.detail") is False and "NÄYTÄ LÄHDETIEDOT" in pg.evaluate(rows_js)[23])
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(150); d1 = pg.evaluate("window.LAKITV.state.detail")
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(150); d2 = pg.evaluate("window.LAKITV.state.detail"); c2 = pg.evaluate("window.LAKITV.state.current")
    pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(150); d3 = pg.evaluate("window.LAKITV.state.detail")
    check("201: ▶ avaa lähdetiedot, ◀ sulkee, sivu ei vaihdu", d1 is True and d2 is True and c2 == 201 and d3 is False, (d1, d2, c2, d3))
    pg.evaluate("window.LAKITV.go(202)"); pg.wait_for_timeout(250)
    check("sivunvaihto sulkee lähdetiedot", pg.evaluate("window.LAKITV.state.detail") is False)

    # 3. katkaisu: pisin juttu näkyy yhdellä sivulla, teksti päättyy kolmeen pisteeseen, LOPPUTULOS säilyy
    long_item = max((it for lst in D["kanavat"].values() for it in lst), key=lambda it: len(it.get("teksti") or ""))
    ln = pg.evaluate("""(id) => { const L = window.LAKITV; for (const ch of L.CHANNELS) for (let i = 0; i < 9; i++) { const x = L.itemIndexGet(ch.page + i + 1); if (x && x.it.id === id) return ch.page + i + 1; } return null; }""", long_item["id"])
    if ln:
        rows = goto(pg, ln)
        pgj = pg.evaluate(f"(() => {{ const p = window.LAKITV.getPage({ln}); return {{subs: p.subs.length, trunc: !!p.truncated}}; }})()")
        txt = [l.rstrip() for l in rows[4:23] if l.strip() and not l.strip().startswith(("LOPPUTULOS", "EI LAINVOIMAINEN", "NÄYTÄ"))]
        # teksti päättyy kokonaiseen virkkeeseen (tai viimeisenä keinona …), ei kesken sanan
        last_text = next((l for l in reversed(txt) if l.strip()), "")
        check(f"{ln}: pitkä teksti lyhennetty yhdelle sivulle kokonaisin virkkein", pgj["subs"] == 1 and pgj["trunc"] and (last_text.strip().endswith(("…", ".", "!", "?", ".”", ".)")) ), (pgj, rows[12:23]))
        full_words = (long_item.get("teksti") or "").split()
        shown = " ".join(l.strip() for l in txt)
        check(f"{ln}: sivulla näkyy vähintään puolet tilasta (≥25 sanaa)", len(shown.split()) >= 25 and len(shown.split()) < len(full_words), (len(shown.split()), len(full_words)))
        if long_item.get("lopputulos"):
            check(f"{ln}: LOPPUTULOS säilyy lyhennetylläkin sivulla", any(l.strip().startswith("LOPPUTULOS:") for l in rows), rows[15:23])
        det3 = detail(pg, ln)
        check(f"{ln}: lähdetiedoissa Lyhennetty-rivi", any("LYHENNETTY" in l.upper() for l in det3), det3[14:22])

    # 4. uusi juttu: UUSI vilkkuu kaistalla
    fresh = pg.evaluate("""() => { const L = window.LAKITV; for (const ch of L.CHANNELS) for (let i = 0; i < 9; i++) { const n = ch.page + i + 1, x = L.itemIndexGet(n);
        if (x && (Date.now() - Date.parse((x.it.julkaistu || '').length === 10 ? x.it.julkaistu + 'T06:00:00+03:00' : (x.it.julkaistu || '') + ':00+03:00')) / 36e5 <= 24) return n; } return null; }""")
    if fresh:
        band = goto(pg, fresh)[1]
        check(f"{fresh}: UUSI kaistalla ja vilkkuu", "UUSI" in band and pg.evaluate("!!document.querySelectorAll('#rows .row')[1].querySelector('.fl')"), band)
    else:
        print("skip: ei tuoretta juttua")

    # 5. lausuntokierros: määräaika tiivistelmäsivulla, kalenterilinkki lähdetiedoissa seurannan rivillä
    laus = pg.evaluate("""() => { const L = window.LAKITV; for (let i = 0; i < 9; i++) { const x = L.itemIndexGet(741 + i); if (x && x.it.maaraaika >= new Date().toISOString().slice(0, 10)) return 741 + i; } return null; }""")
    if laus:
        f2 = goto(pg, laus); l2 = detail(pg, laus)
        check(f"{laus}: LAUSUNNOT VIIMEISTÄÄN tiivistelmäsivulla", any("LAUSUNNOT VIIMEISTÄÄN" in l for l in f2), f2[3:6])
        check(f"{laus}: KALENTERIIN samalla rivillä kuin SEURAA ASIAA (lähdetiedot)", any("SEURAA ASIAA" in l and "KALENTERIIN" in l for l in l2), [l for l in l2 if "SEURAA" in l])
    else:
        print("skip: ei avointa lausuntokierrosta")

    # 6. validate: ylipitkä teksti on vanhalle jutulle huomautus LYHENNÄ (sivusto rakentuu silti) ja uudelle jutulle virhe YLI SIVUN
    E, W = L.validate(D)
    check("validate: LYHENNÄ-huomautus pisimmälle (vanhalle) jutulle, ei virhettä", any(w.startswith("LYHENNÄ") and long_item["id"] in w for w in W)
          and not any("YLI SIVUN" in e and long_item["id"] in e for e in E), (E[:3], W[:3]))
    fresh_d = copy.deepcopy(D)
    for lst in fresh_d["kanavat"].values():
        for it in lst:
            if it["id"] == long_item["id"]: it["lisatty"] = L.ONE_PAGE_SINCE + "T07:00"
    E1, _ = L.validate(fresh_d)
    check("validate: sama juttu uutena -> YLI SIVUN -virhe", any(e.startswith("YLI SIVUN") and long_item["id"] in e for e in E1), E1[:3])
    short = copy.deepcopy(D)
    for lst in short["kanavat"].values():
        for it in lst:
            for f in ("teksti", "teksti_sv", "teksti_en"):
                if it.get(f): it[f] = " ".join(it[f].split()[:25])
            for f in ("lopputulos", "lopputulos_sv", "lopputulos_en"):
                if it.get(f): it[f] = " ".join(it[f].split()[:10])
    E2, W2 = L.validate(short)
    check("validate: lyhennetyt tekstit -> ei YLI SIVUN- eikä LYHENNÄ-rivejä", not any("YLI SIVUN" in e for e in E2) and not any(w.startswith("LYHENNÄ") for w in W2),
          [e for e in E2 if "YLI SIVUN" in e][:3] + [w for w in W2 if w.startswith("LYHENNÄ")][:3])

    # 7. ohje 199 kertoo tekoälystä ja lähdetiedoista
    help_txt = "\n".join(l for s in range(pg.evaluate("window.LAKITV.getPage(199).subs.length")) for l in pg.evaluate(f"(s => {{ window.LAKITV.show(199, s, true); return {rows_js}; }})({s})")).upper()
    check("199: tekoälymaininta ja lähdetiedot ohjeessa", "TEKOÄLY" in help_txt and "LÄHDETIEDOT" in help_txt)
    check("ei JS-virheitä", not errs, errs)
    b.close()
print(f"{ok} / {ok + fail} OK")
sys.exit(1 if fail else 0)
