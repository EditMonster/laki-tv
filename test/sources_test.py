"""Uusien skannerilähteiden (10/2026) jäsennystestit tallennetuilla sivuilla: ei verkkoa.
Yrityskaupat (KKV, komissio), PeVL, EU-asetukset, KVL, lautakunnat (YVTltk, KRIL), komission kilpailutiedotteet."""
import sys, json, re, os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
sys.path.insert(0, _ROOT + "/tools")
import lakitv as L
F = _ROOT + "/test/fixtures/"
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)

def rd(name): return open(F + name, encoding="utf-8").read()

# verkko korvataan: osoite -> tallennettu sivu
PAGES = {
    "https://www.kkv.fi/paatokset/kilpailuasiat/yrityskauppavalvonta/": rd("kkv_yrityskaupat.html"),
    "https://www.kkv.fi/paatokset/vireilla-olevat-yrityskaupat/": rd("kkv_vireilla.html"),
    "https://www.yvtltk.fi/feed/rss-feed?post_type=tapausseloste": rd("yvtltk_rss.xml"),
    "https://www.kuluttajariita.fi/feed/rss-feed?post_type=paatos": rd("kril_rss.xml"),
    "https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/377073/kvl0222026/": rd("kvl_2026_22.html"),
    "https://www.vero.fi/sitemap.xml": ('<?xml version="1.0"?><urlset><url><loc>https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/377073/kvl0222026/</loc>'
                                         f'<lastmod>{L.now().date().isoformat()}T10:00:00+03:00</lastmod></url><url><loc>https://www.vero.fi/harmaa-talous/</loc><lastmod>2026-10-19T14:00:10+03:00</lastmod></url>'
                                         '<url><loc>https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/1/kvl0012020/</loc><lastmod>2020-01-01T10:00:00+03:00</lastmod></url></urlset>'),
}
def fake_get_text(url, **k):
    for u, body in PAGES.items():
        if url == u or url.startswith(u):
            return body
    if "kuluttajariita.fi/paatokset/" in url: return rd("kril_paatos.html")
    if "yvtltk.fi/tapausselosteet/" in url: return rd("yvtltk_seloste.html")
    if "presscorner/api/search" in url: return rd("presscorner.json")
    raise OSError("ei verkkoa testissä: " + url)
L.get_text = fake_get_text
L.SCAN_CTX["data"] = {"kanavat": {k: [] for k in L.CH_KEYS}, "arkisto": [], "_nahty": []}

# 1. KKV: päätökset ja vireillä olevat
r = L.src_kkv_yrityskaupat()
dec = [x for x in r if x["vaihe"] == "päätös"]; pend = [x for x in r if x["vaihe"] == "vireillä"]
ok(len(dec) >= 3 and dec[0]["otsikko"] == "Nimlas Finland Oy / Tammelan Talotekniikka Oy" and dec[0]["julkaistu"] == "2026-10-15"
   and dec[0]["laji"] == "Yrityskaupan hyväksyminen sellaisenaan" and dec[0]["tunnus"] == "KKV/1410/14.00.10/2026", "KKV-YK: päätöslista (otsikko, pvm, laji, tunnus)", dec[:1])
ok(len(pend) == 3 and pend[0]["kuuleminen"] == "2026-10-23" and "(kuuleminen" not in pend[0]["otsikko"] and pend[0]["valmis"], "KKV-YK: vireillä olevat (kuulemisen määräaika)", pend[:1])

# 2. Komission yrityskauppavalvonta: suomalainen osapuoli tunnistetaan ilmoituksen tekstistä; muut jätetään pois; päätös tunnetusta asiasta mukaan
L._sparql = lambda q, timeout=90: [
    {"celex": {"value": "52026M12540"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Ennakkoilmoitus yrityskeskittymästä (Asia M.12540 – AP EJENDOMME / CAPMAN AIFM / HOTEL) – Yksinkertaistettuun menettelyyn mahdollisesti soveltuva asia"}},
    {"celex": {"value": "52026M12661"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Ennakkoilmoitus yrityskeskittymästä (Asia M.12661 – VERITAS / BODYCOTE)"}},
    {"celex": {"value": "52026M12516(01)"}, "pub": {"value": "2026-10-19"}, "title": {"value": "Ilmoitetun keskittymän vastustamatta jättäminen (Asia M.12516 – KESKO / DAHL)"}},
    {"celex": {"value": "52026M12000(01)"}, "pub": {"value": "2026-10-19"}, "title": {"value": "Ilmoitetun keskittymän vastustamatta jättäminen (Asia M.12000 – A / B)"}}]
TEXTS = {"52026M12540": "Ennakkoilmoitus\n1.\nKomissio vastaanotti ilmoituksen.\nIlmoitus koskee seuraavia yrityksiä:\n— AP Ejendomme A/S (AP, Tanska)\n— CapMan AIFM Oy (CapMan, Suomi)\n2.\nKyseisten yritysten liiketoiminnan sisältö on seuraava:\n— AP on kiinteistösijoitusyhtiö.\n— CapMan hallinnoi rahastoja.\n3.\nKomissio katsoo.",
         "52026M12661": "Ennakkoilmoitus\n1.\nIlmoitus koskee seuraavia yrityksiä:\n— Veritas Capital (Veritas, Yhdysvallat)\n— Bodycote plc (Bodycote, Yhdistynyt kuningaskunta)\n2.\nKyseisten yritysten liiketoiminnan sisältö on seuraava:\n— Veritas on sijoitusyhtiö.\n3.\nKomissio katsoo."}
L.cellar_text = lambda celex, url, maxc, lang="FI": {"teksti": TEXTS[celex]}
L.SCAN_CTX["data"]["kanavat"]["yrityskaupat"] = [{"id": "eu-m-12516", "lahde": "https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:52026M12516"}]
r = L.src_eu_yrityskaupat()
ok([x["tunnus"] for x in r] == ["M.12540", "M.12516"] and r[0]["maat"] == ["Tanska", "Suomi"] and r[0]["id_ehdotus"] == "eu-m-12540" and "CapMan hallinnoi" in r[0]["kuvaus"],
   "EU-YK: Suomi-osapuoli mukaan, ulkomainen pois, tunnetun asian päätös mukaan", [(x["tunnus"], x.get("maat")) for x in r])
ok(r[1]["paivitys"] and r[1]["laji"].startswith("komissio hyväksyi"), "EU-YK: vastustamatta jättäminen merkitään päivitykseksi", r[1])

# 3. EU-asetukset: täytäntöönpanoasetukset pois, EP+neuvosto, neuvosto ja delegoidut mukaan; muut kielet
def sparql_reg(q, timeout=90):
    if "VALUES ?celex" in q:
        lang = "SWE" if "/SWE>" in q else "ENG"
        return [{"celex": {"value": "32026R2269"}, "title": {"value": "Europaparlamentets och rådets förordning (EU) 2026/2269" if lang == "SWE" else "Regulation (EU) 2026/2269 of the European Parliament and of the Council"}}]
    return [{"celex": {"value": "32026R2269"}, "date": {"value": "2026-10-07"}, "pub": {"value": "2026-10-09"}, "eif": {"value": "2026-10-10"}, "trans": {"value": "2027-01-01"},
             "title": {"value": "Euroopan parlamentin ja neuvoston asetus (EU) 2026/2269, annettu 7 päivänä lokakuuta 2026, testistä"}},
            {"celex": {"value": "32026R2311"}, "date": {"value": "2026-10-19"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Komission täytäntöönpanoasetus (EU) 2026/2311, annettu 19 päivänä lokakuuta 2026, lopullisen polkumyyntitullin käyttöön ottamisesta"}},
            {"celex": {"value": "32026R1536"}, "date": {"value": "2026-07-06"}, "pub": {"value": "2026-10-14"}, "eif": {"value": "2026-12-07"}, "title": {"value": "Komission delegoitu asetus (EU) 2026/1536, annettu 6 päivänä heinäkuuta 2026, testistä"}}]
L._sparql = sparql_reg
r = L.src_eu_asetukset()
ok([x["tunnus"] for x in r] == ["Asetus (EU) 2026/2269", "Asetus (EU) 2026/1536"] and r[0]["laatija"] == "EP ja neuvosto" and r[1]["laatija"] == "komissio (delegoitu)"
   and r[0]["otsikko_sv"].startswith("Europaparlamentets") and r[0]["otsikko_en"].startswith("Regulation") and "sovelletaan 1.1.2027" in r[0]["kuvaus"] and r[0]["eli"] == "http://data.europa.eu/eli/reg/2026/2269/oj",
   "EU-ASETUS: täytäntöönpanoasetus pois, nimikkeet sv/en, soveltamispäivä, ELI", [(x["tunnus"], x["laatija"], x["kuvaus"]) for x in r])

# 4. PeVL eduskunnan avoimesta datasta
d = json.load(open(F + "pevl_30_2026.json")); row = dict(zip(d["columnNames"], d["rowData"][0]))
ok(L._is_pevl_doc(row) and not L._is_he_doc(row), "PeVL: asiakirja tunnistetaan (ei HE)")
x = L.pevl_item(row, re.match(r"PeVL (\d+)/(\d{4}) vp$", row["Eduskuntatunnus"]))
ok(x["kanava"] == "he" and x["tunnus"] == "PeVL 30/2026 vp" and x["he"] == "HE 52/2026 vp" and x["vastaanottaja"] == "Hallintovaliokunnalle"
   and x["paatosesitys"].startswith("Perustuslakivaliokunta esittää") and x["url"].endswith("PeVL+30/2026") and x["otsikko"].startswith("PeVL: Hallituksen esitys"),
   "PeVL: kohde-HE, vastaanottaja, päätösesitys, osoite", x)
ok(L.api_url_for("https://www.eduskunta.fi/valtiopaivaasiakirjat/PeVL+30/2026") == ("pevl", 30, 2026), "PeVL: osoite ohjataan rajapintaan (text)")

# 5. KVL vero.fi:n sivukartasta ja ratkaisusivulta
r = L.src_kvl()
ok(len(r) == 1 and r[0]["tunnus"] == "KVL:2026/22" and r[0]["annettu"] == "2026-08-21" and r[0]["lainvoimainen"] == "Lainvoimainen"
   and r[0]["asiasanat"].startswith("Arvonlisävero, Hammasproteesi") and r[0]["kuvaus"].startswith("A Oy valmisti ja myi poraohjaimia") and r[0]["kanava"] == "vero",
   "KVL: sivukartta (vain tuoreet ratkaisusivut) + tunnus, antopäivä, lainvoimaisuus, asiasanat, teksti", r[:1])

# 6. Lautakunnat: RSS + sivu; KRIL vain täysistuntoratkaisut
r = L.SOURCES["YVTLTK"]()
ok(len(r) == 3 and r[0]["kanava"] == "muut" and r[0]["elin"].startswith("Yhdenvertaisuus") and r[0]["annettu"] == "2026-10-08" and r[0]["lainvoimainen"] == "Ei lainvoimainen"
   and r[0]["asiasanat"].startswith("Hyvitys, Perusopetus") and r[0]["kuvaus"].startswith("Kevätjuhla") and r[0]["julkaistu"].startswith("2026-10-08T"), "YVTLTK: RSS ja selosteen metatiedot", r[:1])
r = L.SOURCES["KRIL"]()
ok(len(r) == 3 and all(x["taysistunto"] for x in r) and r[0]["diaari"] == "D/984/34/2026" and r[0]["annettu"] == "2026-10-12" and r[0]["kuvaus"].startswith("Kuluttaja tilasi"),
   "KRIL: täysistuntopäätökset, diaari, antopäivä, selostus", r[:1])

# 7. Komission kilpailutiedotteet: otsikkosuodatus ja yksinkertaistetut yrityskauppahyväksynnät pois
r = L.src_eu_kilpailu()
ok([x["otsikko"][:20] for x in r] == ["Commission fines Kin", "State aid: Commissio"] and r[0]["url"].endswith("/ip_26_2100") and r[0]["kanava"] == "kilpailu" and r[1]["julkaistu"] == "2026-10-07",
   "EU-KILPAILU: sakot ja valtiontuki mukaan, puheet ja rutiinihyväksynnät pois", [x["otsikko"] for x in r])

# 8. validate: uudet kanavat kelpaavat; puuttuvat kanavat ovat huomautus, tuntematon kanava virhe
base = json.load(open(_ROOT + "/data.json", encoding="utf-8"))
E, W = L.validate(base)
ok(not any("kanavat" in e for e in E), "validate: data ilman uusia kanavia ei ole virhe" + (" (puuttuvat huomautuksena)" if any("kanavat puuttuvat" in w for w in W) or set(L.CH_KEYS) <= set(base["kanavat"]) else ""), E[:3])
bad = dict(base); bad["kanavat"] = dict(base["kanavat"]); bad["kanavat"]["tuntematon"] = []
ok(any("kanavat-avaimet" in e for e in L.validate(bad)[0]), "validate: tuntematon kanava on virhe")
ok(L.CH_PAGE["yrityskaupat"] == 520 and L.CH_PAGE["vero"] == 650 and L.CH_NAMES["vero"][1] == "Beskattning", "kanavat: sivunumerot ja nimet")
ok("HE" in L.ZERO_OK and "KVL" in L.ZERO_OK, "ZERO_OK: harvoin julkaisevat lähteet eivät hälytä tyhjästä")

# 9. Presscorner-tiedotteen teksti luetaan documents-rajapinnasta (sivu on JavaScript-sovellus)
_pc_urls = []
def fake_fetch(url, **k):
    _pc_urls.append(url)
    return rd("presscorner_doc.json").encode("utf-8")
L.fetch = fake_fetch
r = L._text("https://ec.europa.eu/commission/presscorner/detail/en/ip_26_2178", 5000)
ok(_pc_urls == ["https://ec.europa.eu/commission/presscorner/api/documents?reference=IP/26/2178&language=en"] and r["julkaistu"] == "2026-10-19"
   and r["otsikko"].startswith("Commission sends Statement") and r["teksti"].startswith("The European Commission has informed KKR & Co.") and "\nThe merger investigation\n" in r["teksti"]
   and r["teksti"].endswith("Point one\nPoint two"), "text: presscorner-tiedote rajapinnasta (viite, päivä, teksti)", r)

print(("KAIKKI OK" if not fails else f"{len(fails)} virhettä: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
