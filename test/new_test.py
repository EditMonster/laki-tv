# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""Uudet ominaisuudet: viikon tärkeimmät (102), kalenteri (103/104), arkisto (105), ruotsi, tilauslomake."""
import json, copy, subprocess, datetime, sys
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))   # testikello: tänään klo 21 Helsinki
BASE = _ROOT + "/"
HKI = ZoneInfo("Europe/Helsinki")
ok = []
def check(name, cond, info=""):
    ok.append(bool(cond)); print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))

now = datetime.datetime.now(HKI)
today = now.date()
monday = today - datetime.timedelta(days=today.weekday())
def ts(d, h=9, m=0): return f"{d.isoformat()}T{h:02d}:{m:02d}"

def make(extra_items, arch=None, extra_channels=None):
    d = json.load(open(BASE + "test/fixture_data.json"))
    d = copy.deepcopy(d)
    # tyhjennä tämän viikon jutut, jotta testi on deterministinen
    for k, l in d["kanavat"].items():
        l[:] = [x for x in l if x["julkaistu"][:10] < monday.isoformat()]
    d["kanavat"]["kko"] = extra_items + d["kanavat"]["kko"]
    d["kanavat"]["kko"] = d["kanavat"]["kko"][:9]
    d["arkisto"] = arch or []
    for k, v in (extra_channels or {}).items():   # uudet kanavat (yrityskaupat, vero): testidata on niitä vanhempaa; lisätään viikkosuodatuksen jälkeen
        d["kanavat"][k] = v
    json.dump(d, open("/tmp/t_data.json", "w"), ensure_ascii=False)
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "inject", BASE + "test/fixture.html", "/tmp/t_data.json", "/tmp/t_page.html", "--force"], capture_output=True, text=True)
    assert "OK" in r.stdout, r.stdout + r.stderr

def item(i, paino, julk, lisatty=None):
    x = {"id": f"T:{i}", "tunnus": f"T:{i}", "otsikko": f"TESTIJUTTU {i}", "otsikko_sv": f"TESTNYHET {i}", "pvm": julk[:10], "pvm_selite": "annettu",
         "julkaistu": julk, "paino": paino, "teksti": "Testi.", "teksti_sv": "Test.", "tekstityyppi": "tiivistelmä", "selko": "Testi.", "selko_sv": "Test.",
         "lahde": "https://example.org/", "aiheet": ["rikos"]}
    if lisatty: x["lisatty"] = lisatty
    return x

def week_titles(pg):
    pg.evaluate("window.LAKITV.go(102)"); pg.wait_for_timeout(400)
    return pg.evaluate("window.LAKITV.weekTop(new Date().toISOString().slice(0,10) ? (()=>{const d=new Date(); return null})() : null, 10)") if False else \
        pg.evaluate("""() => { const t = new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Helsinki'}).format(new Date());
          const d = new Date(t + 'T12:00:00Z'); const mon = new Date(d - ((d.getUTCDay() + 6) % 7) * 864e5).toISOString().slice(0,10);
          return window.LAKITV.weekTop(mon, 10).map(x => x.it.id); }""")

d0 = monday
first_day = min(today, d0 + datetime.timedelta(days=0))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.clock.set_fixed_time(_FIXED)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    # 1) viikon järjestys ja pysyvyys
    base = [item(1, 5, ts(d0, 8), ts(d0, 8)), item(2, 5, ts(d0, 9), ts(d0, 9)), item(3, 4, ts(d0, 7), ts(d0, 7)), item(4, 3, ts(d0, 10), ts(d0, 10))]
    make(base); pg.goto("file:///tmp/t_page.html"); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    ids = week_titles(pg)
    check("102: paino ensin, sitten lisäysaika", ids[:4] == ["T:1", "T:2", "T:3", "T:4"], ids)
    rows = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("102: otsikko VIIKON TÄRKEIMMÄT", "VIIKON TÄRKEIMMÄT" in rows.upper(), rows[:200])
    later_same = base + [item(5, 5, ts(d0, 6), ts(today, 23, 50))]   # julkaistu aiemmin, mutta tuli LAKI-TV:hen myöhemmin
    make(later_same); pg.goto("file:///tmp/t_page.html"); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    ids2 = week_titles(pg)
    check("102: samanpainoinen myöhemmin tullut ei syrjäytä", ids2[:3] == ["T:1", "T:2", "T:5"], ids2)
    # 2) kalenteri ja päivän tilanne
    make(base); pg.goto("file:///tmp/t_page.html"); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(103)"); pg.wait_for_timeout(400)
    cells = pg.locator("#rows a[data-day]")
    check("103: päiväsolut linkkeinä", cells.count() >= 31, cells.count())
    yday = (today - datetime.timedelta(days=1)).isoformat()
    pg.locator(f"#rows a[data-day='{yday}']").first.click(); pg.wait_for_timeout(500)
    cur = pg.evaluate("window.LAKITV.state.current")
    check("103 -> 104 eilinen", cur == 104 and pg.evaluate("location.hash") == "#d=" + yday, (cur, pg.evaluate("location.hash")))
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("104: tilanne päivän päättyessä", "PÄIVÄN PÄÄTTYESSÄ" in txt.upper(), txt[:300])
    pg.keyboard.press("r"); pg.wait_for_timeout(400)
    check("104: punainen = edellinen päivä", pg.evaluate("window.LAKITV.state.day") == (today - datetime.timedelta(days=2)).isoformat(), pg.evaluate("window.LAKITV.state.day"))
    pg.keyboard.press("Backspace"); pg.wait_for_timeout(400)
    check("takaisin palaa edelliseen päivään", pg.evaluate("window.LAKITV.state.day") == yday and pg.evaluate("window.LAKITV.state.current") == 104)
    pg.goto("file:///tmp/t_page.html#d=" + yday); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    check("#d= avaa päivän suoraan", pg.evaluate("window.LAKITV.state.current") == 104 and pg.evaluate("window.LAKITV.state.day") == yday)
    # päiväsivun etusivu ei näytä myöhemmin lisättyjä
    make(base + [item(9, 5, ts(today, 0, 5), ts(today, 0, 5))]); pg.goto("file:///tmp/t_page.html#d=" + yday); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("104: tänään lisätty ei näy eilisen etusivulla", "TESTIJUTTU 9" not in txt.upper(), txt[:400])
    # 3) arkisto
    arch = [{"id": "ARK:1", "k": "kho", "tunnus": "ARK:1", "otsikko": "ARKISTOITU JUTTU", "otsikko_sv": "ARKIVERAD NYHET", "pvm": yday, "julkaistu": yday + "T10:00",
             "paino": 4, "aiheet": ["vero"], "teksti": "Arkiston teksti.", "teksti_sv": "Arkivets text.", "tekstityyppi": "tiivistelmä", "lahde": "https://example.org/a"}]
    make(base, arch); pg.goto("file:///tmp/t_page.html#j=ARK%3A1"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("#j= avaa arkistojutun 105", pg.evaluate("window.LAKITV.state.current") == 105 and "ARKISTOITU JUTTU" in txt.upper(), txt[:200])
    pg.evaluate("window.LAKITV.go(104, false, {day:'%s'})" % yday); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("104: arkistojuttu näkyy päivän jutuissa (ARK)", "ARKISTOITU JUTTU" in txt.upper() and "ARK" in txt, txt[:500])
    pg.keyboard.press("f"); pg.fill("#q", "arkistoitu"); pg.wait_for_timeout(300)
    check("haku löytää arkistojutun", "ARK" in pg.inner_text("#qResults"), pg.inner_text("#qResults")[:200])
    pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    check("hakutulos avaa 105", pg.evaluate("window.LAKITV.state.current") == 105)
    # 3b) etusivun 24 tunnin ikkuna: juttu on pääuutisissa enintään 24 h siitä, kun se tuli LAKI-TV:hen (lisatty) tai julkaistiin
    yday1, yday2 = today - datetime.timedelta(days=1), today - datetime.timedelta(days=2)
    front = [item(11, 5, ts(yday1, 10), ts(yday1, 10)),          # julkaistu ja lisätty eilen klo 10 (35 h sitten): ei etusivulla
             item(12, 5, ts(yday2, 10), ts(today, 15)),        # julkaistu toissapäivänä, tuli LAKI-TV:hen tänään klo 15: etusivulla
             item(13, 3, ts(today, 19)),                       # julkaistu tänään klo 19 ilman lisatty-kenttää: etusivulla
             item(14, 4, ts(today, 8), ts(today, 8))]          # 13 h sitten: etusivulla, painon mukaan ennen T:13
    make(front); pg.goto("file:///tmp/t_page.html#p100"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(100)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("100: yli 24 h sitten tullut juttu ei ole pääuutisissa", "TESTIJUTTU 11" not in txt, txt[:400])
    check("100: aiemmin julkaistu mutta alle 24 h sitten lisätty juttu on pääuutisissa", "TESTIJUTTU 12" in txt, txt[:400])
    check("100: alle 24 h sitten julkaistu juttu ilman lisatty-kenttää on pääuutisissa", "TESTIJUTTU 13" in txt, txt[:400])
    check("100: kärki on 24 tunnin painavin", txt.index("TESTIJUTTU 12") < txt.index("TESTIJUTTU 14") < txt.index("TESTIJUTTU 13"), txt[:400])
    make([item(15, 5, ts(yday1, 10), ts(yday1, 10))]); pg.goto("file:///tmp/t_page.html#p100"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(100)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("100: ilman 24 tunnin juttuja etusivu kertoo sen eikä nosta vanhaa kärjeksi", "TESTIJUTTU 15" not in txt and "EI UUSIA JUTTUJA 24 TUNNIN AIKANA" in txt and "TÄNÄÄN 101" in txt and "VIIKKO 102" in txt, txt[:600])
    # 3c) uudet kanavat 520 YRITYSKAUPAT ja 650 VEROTUS: kanavasivu, juttusivu, kanavaluettelo ja tyhjä kanava
    yk = dict(item(21, 4, ts(today, 10), ts(today, 10)), **{"id": "kkv-1410-14-00-10-2026", "tunnus": "KKV/1410/14.00.10/2026", "otsikko": "NIMLAS / TAMMELAN TALOTEKNIIKKA", "otsikko_sv": "NIMLAS / TAMMELAN TALOTEKNIIKKA", "lopputulos": "Hyväksytty sellaisenaan.", "aiheet": ["kilpailu", "yhtio"]})
    ve = dict(item(22, 3, ts(today, 9), ts(today, 9)), **{"id": "KVL:2026/22", "tunnus": "KVL:2026/22", "otsikko": "PORAOHJAIMEN ALV-KOHTELU", "otsikko_sv": "MOMS PÅ BORRGUIDE", "lainvoimainen": True, "aiheet": ["vero"]})
    pv = dict(item(23, 4, ts(today, 8), ts(today, 8)), **{"id": "pevl-30-2026", "tunnus": "PeVL 30/2026 vp", "otsikko": "PEVL: HALLINTOVALIOKUNNALLE", "otsikko_sv": "GRUU TILL FÖRVALTNINGSUTSKOTTET", "vaihe": "HE 52/2026 vp, HaV käsittelee", "vaihe_sv": "RP 52/2026 rd, FvU behandlar", "aiheet": ["hallinto"]})
    make([], extra_channels={"yrityskaupat": [yk], "vero": [ve], "he": [pv]}); pg.goto("file:///tmp/t_page.html#p520"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(520)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("520: yrityskaupat-kanavasivu", "YRITYSKAUPAT" in txt and "NIMLAS" in txt and "521" in txt, txt[:400])
    pg.evaluate("window.LAKITV.go(521)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("521: yrityskauppajuttu (tunnus ja lopputulos)", "KKV/1410/14.00.10/2026" in txt and "HYVÄKSYTTY SELLAISENAAN" in txt, txt[:500])
    pg.evaluate("window.LAKITV.go(650)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("650: verotus-kanavasivu (KVL)", "VEROTUS" in txt and "PORAOHJAIMEN" in txt and "651" in txt, txt[:400])
    pg.evaluate("window.LAKITV.go(190)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("190: kanavaluettelossa 520 ja 650", "520" in txt and "YRITYSKAUP" in txt and "650" in txt and "VEROTUS" in txt, txt[:600])
    pg.click("#kSv"); pg.wait_for_timeout(400); pg.evaluate("window.LAKITV.go(520)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("520 SV: FÖRETAGSFÖRVÄRV", "FÖRETAGSFÖRVÄRV" in txt, txt[:300])
    pg.evaluate("window.LAKITV.go(651)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("651 SV: KVL-tunnus näytetään CSN-muodossa", "CSN:2026/22" in txt and "KVL:2026/22" not in txt, txt[:300])
    pg.evaluate("window.LAKITV.go(701)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("701 SV: PeVL-tunnus näytetään GrUU-muodossa", "GRUU 30/2026 RD" in txt and "PEVL 30/2026" not in txt and "RP 52/2026" in txt, txt[:400])
    pg.click("#kFi"); pg.wait_for_timeout(300)
    make([]); pg.goto("file:///tmp/t_page.html#p650"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(650)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')").upper()
    check("650: kanava puuttuu datasta -> sivu näkyy tyhjänä, ei virhettä", "VEROTUS" in txt and "EI NÄY" not in txt and not errs, (txt[:300], errs[:2]))
    # 4) ruotsi
    make(base + [item(6, 5, ts(today, 9), ts(today, 9))]); pg.goto("file:///tmp/t_page.html#p100"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    pg.click("#kSv"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("SV: etusivu ruotsiksi", "HUVUDNYHETER" in txt.upper() and "TESTNYHET 6" in txt.upper(), txt[:300])
    check("SV: kaukosäädin ruotsiksi", pg.inner_text("#kSearch").strip().upper() == "SÖK" and pg.get_attribute("html", "lang") == "sv")
    pg.reload(); pg.wait_for_timeout(500)
    check("SV: valinta muistetaan", pg.evaluate("document.documentElement.lang") == "sv")
    pg.evaluate("window.LAKITV.go(201)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("SV: juttusivu (HD-tunnus tai ruotsi)", "TESTNYHET" in txt.upper() or "HD:" in txt.upper(), txt[:200])
    pg.click("#kFi"); pg.wait_for_timeout(300)
    check("FI takaisin", pg.evaluate("document.documentElement.lang") == "fi" and pg.inner_text("#kSearch").strip().upper() == "HAKU")
    # 5) JAKELU ilman isäntää: paneeli aukeaa, ei ylläpitäjälomaketta
    pg.click("#kSub"); pg.wait_for_timeout(600)
    check("JAKELU avaa jakelupaneelin", pg.get_attribute("#tabKal", "aria-selected") == "true" and pg.locator("#paneKal a.pn-btn", has_text="JSON").count() == 1)
    check("ilman isäntää ei ylläpitäjälomaketta", not pg.is_visible("#jakeluAdmin"))
    pg.keyboard.press("Escape")
    # 6) omistajan webhook-lomake mock-tietokannalla (mobiili)
    pg2 = b.new_page(viewport={"width": 390, "height": 844})
    pg2.clock.set_fixed_time(_FIXED)
    pg2.add_init_script("""
      window.__store = {}; window.__writes = [];
      const ref = p => ({ get: async () => ({exists: p in window.__store, data: () => window.__store[p]}),
                          set: async v => { window.__writes.push(['set', p, v]); window.__store[p] = v; } });
      window.claude = { use: async n => n === 'db' ? {doc: ref} : n === 'user' ? {id: async () => 'u_test123', isOwner: async () => true} : null };
    """)
    e2 = []; pg2.on("pageerror", lambda e: e2.append(str(e)))
    pg2.goto("file:///tmp/t_page.html"); pg2.wait_for_timeout(500); pg2.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg2.wait_for_timeout(300)
    pg2.click("#kSub"); pg2.wait_for_timeout(800)
    check("omistaja näkee webhook-lomakkeen", pg2.is_visible("#jakeluAdmin"))
    pg2.fill("#whSlack", "http://hooks.slack.com/x"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(200)
    check("validointi: https", "https" in pg2.inner_text("#whStatus"))
    pg2.fill("#whSlack", "https://hooks.slack.com/services/T/B/x"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(400)
    w = pg2.evaluate("window.__writes")
    check("webhook tallentuu asetukset/jakelu", w and w[-1][1] == "asetukset/jakelu" and w[-1][2]["slack_webhook"].startswith("https://hooks.slack.com"), w)
    pg2.fill("#ghRepo", "https://github.com/x/y"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(200)
    check("validointi: github_repo omistaja/nimi tai gist", "gist" in pg2.inner_text("#whStatus") and len(pg2.evaluate("window.__writes")) == len(w))
    pg2.fill("#ghRepo", "gist:0123456789abcdef0123456789abcdef"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(400)
    check("gist-muoto hyväksytään", pg2.evaluate("window.__writes")[-1][2].get("github_repo", "").startswith("gist:"))
    pg2.fill("#ghRepo", "omistaja/laki-tv"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(400)
    w = pg2.evaluate("window.__writes")
    check("github_repo tallentuu samaan dokumenttiin", w[-1][2].get("github_repo") == "omistaja/laki-tv" and w[-1][2]["slack_webhook"].startswith("https://"), w[-1])
    # datavaraston avain: salasanakenttä, muotovaatimus, tallentuu vain omistajan dokumenttiin
    check("avainkenttä on salasanakenttä", pg2.get_attribute("#ghToken", "type") == "password")
    pg2.fill("#ghToken", "salasana123"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(200)
    check("validointi: avaimen muoto", "github_pat" in pg2.inner_text("#whStatus") and len(pg2.evaluate("window.__writes")) == len(w))
    pg2.fill("#ghToken", "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(400)
    w = pg2.evaluate("window.__writes")
    check("avain tallentuu asetukset/jakelu-dokumenttiin", w[-1][1] == "asetukset/jakelu" and w[-1][2].get("github_token", "").startswith("github_pat_"))
    check("avain ei päädy selaimen muistiin", "github_pat" not in pg2.evaluate("JSON.stringify(Object.assign({}, localStorage))"))
    sw = pg2.evaluate("document.documentElement.scrollWidth <= innerWidth")
    check("mobiili: ei vaakavieritystä paneelissa", sw)
    # 7) aamukooste 107
    make(base + [item(7, 5, ts(today, 6, 0), ts(today, 6, 30))]); pg.goto("file:///tmp/t_page.html#p107"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("107: aamukooste rakentuu", "AAMUKOOSTE" in txt.upper() and ("PÄIVÄN KÄRKI" in txt.upper() or "UUDET JUTUT" in txt.upper()), txt[:300])
    # 8) Eduskunnassa (he_muutokset), TILA 198, palaute
    d = json.load(open(BASE + "test/fixture_data.json")); d = copy.deepcopy(d)
    d["he_muutokset"] = [{"he": "HE 77/2026 vp", "nimi": "Syyttäjälaitoslaki", "nimi_sv": "Åklagarväsendet", "vanha": 4, "uusi": 5, "valiokunta": "LaV", "pvm": today.isoformat(), "havaittu": today.isoformat()}]
    d["_lahteet"] = {"KKO": {"aika": ts(today, 6, 50), "n": 0, "hiljaa": ts(today, 6, 50), "hist": [10, 10, 0]}, "KHO": {"aika": ts(today, 6, 50), "n": 6, "hist": [6]}}
    d["_ajot"] = [{"aika": ts(today, 6, 55), "uusia": 3, "juttuja": 100, "hiljaa": ["KKO"]}]
    json.dump(d, open("/tmp/t_data.json", "w"), ensure_ascii=False)
    subprocess.run(["python3", BASE + "tools/lakitv.py", "inject", BASE + "test/fixture.html", "/tmp/t_data.json", "/tmp/t_page.html", "--force"], capture_output=True, text=True)
    pg.goto("file:///tmp/t_page.html#p101"); pg.reload(); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    alltxt = pg.evaluate("""() => { const L = window.LAKITV; let t = ''; const n = L.getPage(101).subs.length; for (let s = 0; s < n; s++) { L.show(101, s); t += [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n'); } return t; }""")
    check("101: EDUSKUNNASSA-osio vaihemuutoksesta", "EDUSKUNNASSA" in alltxt and "SYYTTÄJÄLAITOSLAKI" in alltxt.upper(), alltxt[:200])
    pg.evaluate("window.LAKITV.go(720)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("720: muuttunut HE merkitty ▲", "▲" in txt, txt[:200])
    pg.evaluate("window.LAKITV.go(198)"); pg.wait_for_timeout(400)
    txt = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    check("198: lähdevahti näyttää HILJAA", "HILJAA" in txt and "KKO" in txt and "OK" in txt, txt[:400])
    pg3 = b.new_page(viewport={"width": 1280, "height": 820})
    pg3.clock.set_fixed_time(_FIXED)
    e3 = []; pg3.on("pageerror", lambda e: e3.append(str(e)))
    pg3.goto("file:///tmp/t_page.html#p201"); pg3.wait_for_timeout(500); pg3.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg3.wait_for_timeout(300)
    alltxt = pg3.evaluate("""() => { const L = window.LAKITV; let t = ''; const n = L.getPage(201).subs.length; for (let s = 0; s < n; s++) { L.show(201, s); t += [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n'); } if (L.getPage(201).detail) { L.toggleDetail(); t += '\\n' + [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n'); } return t; }""")
    check("palauterivi osoittaa GitHub-issueihin", "PALAUTE" in alltxt and any(h.startswith("https://github.com/") and h.endswith("/issues") for h in pg3.evaluate("[...document.querySelectorAll('#rows a[href]')].map(a => a.href)")), alltxt[-200:])
    check("ei JS-virheitä", not errs and not e2 and not e3, errs + e2 + e3)
    b.close()
print(f"{sum(ok)} / {len(ok)} OK")
import sys as _sys; _sys.exit(0 if all(ok) else 1)
