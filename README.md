# LAKI-TV

**Juridinen teksti-TV.** Suomen oikeuselämän tärkeimmät uudet asiat – korkeimpien oikeuksien ennakkopäätökset, EU-tuomioistuimen ja EIT:n ratkaisut, laillisuusvalvojien päätökset, hallituksen esitykset, lausuntokierrokset ja voimaan tulevat lait – 1980-luvun teksti-TV:n muodossa, kolmella kielellä (suomi, ruotsi, englanti), päivittyen kahdesti päivässä.

*English summary at the end.*

---

## Mitä sivulla on

| Sivut | Sisältö |
|---|---|
| 100 | Etusivu: päivän kärki, pääuutiset, kanavat |
| 101–105 | Tänään, viikon tärkeimmät, kalenteri 30 pv, päivän tilanne, arkisto |
| 107 | Aamukooste (sama kooste, jonka Slack/Teams-kanava saa) |
| 108 | Seurannassa: lukijan seuraamat asiat ja niiden tila |
| 109 | Jakelu: RSS, JSON, Markdown, kalenteri, viikkokatsaus |
| 150 | Päivän visa |
| 190, 199 | Hakemisto, ohje |
| 198 | Tila: lähteet, ajot, arkisto (lähdevahti) |
| 200–599 | Tuomioistuimet ja valvojat: KKO, EUT, EIT, ICJ, KHO, OKV/EOA, HAO, muut, KKV, Fiva, TSV |
| 700–749 | Eduskunta: HE-tulostaulu, hallituksen esitykset, lausuntokierrokset |
| 800–801 | Voimaan tulevat lait ja EU-säädökset |
| 851–869 | Aiheet (sote, tietosuoja, työ, vero, …) |
| 888 | Viimeksi avattu juttu selkeällä kielellä |

Jokaisella jutulla on virallinen tiivistelmä tai neutraali referaatti, selkokielinen versio, aiheet ja linkki viralliseen lähteeseen. Lukija voi **seurata asiaa** (HE:n käsittelyvaihe, EIT-jutun vaihe, lausuntoajan määräaika) ja **lisätä määräajan kalenteriinsa** itse – Google, Outlook, .ics tai tilattava kalenteriosoite. Mitään ei lisätä automaattisesti.

Sivu ei kerää lukijoista mitään: ei evästeitä, ei tunnisteita, ei analytiikkaa, ei yhteyksiä kolmansiin palveluihin. Omat aiheet ja seurannat tallentuvat vain lukijan selaimeen.

## Miten se toimii

```
lähteet (KKO, KHO, Finlex, eduskunta, curia, HUDOC, …)
        │  tools/lakitv.py scan / text / add / he-update / vt-update
        ▼
   data.json  ──inject──▶  laki-tv.html  (yksi tiedosto: HTML + CSS + JS + data + fontit)
        │
        └──feed──▶  feed.xml · feed-sv.xml · feed-en.xml · feed.json · lakitv.md · kalenteri.txt
        └──viikkokatsaus──▶  viikkokatsaus.html / .pdf  (maanantaisin)
        └──digest --muoto slack|teams ──▶ post  (ylläpitäjän webhook)
        └──ghpush (vain data.json)──▶  GitHub ──Actions: validate + build + feed + website──▶  verkkosivusto (GitHub Pages)
```

* **Sivu** on yksi HTML-tiedosto ilman riippuvuuksia. Teksti-TV-moottori piirtää 40×25 merkin sivut datasta selaimessa; kaikki sivut (myös kalenteri, viikon tärkeimmät ja aiheet) lasketaan datasta ajon aikana.
* **Työkalu** `tools/lakitv.py` (Python 3.10+, vain `lxml` lisäksi) tekee kaiken datan käsittelyn: lähteiden skannauksen, lisäyksen, tarkistuksen (`validate`), arkistoinnin, eduskunnan ja Finlexin avoimen datan päivitykset, syötteet ja koosteet.
* **Verkkosivusto** on sama sivu julkisessa osoitteessa: `tools/website.py` lisää hakukone- ja jakotiedot (Open Graph -kuva on sivu 100), PWA-manifestin ja service workerin (toimii ilman yhteyttä), oikean `.ics`-kalenterin, RSS-vaihtoehdot, `robots.txt`:n ja sivukartan. `.github/workflows/pages.yml` rakentaa sen varaston koodista ja julkaisee GitHub Pagesiin aina, kun `data.json` tai koodi muuttuu; päivitysajo työntää vain `data.json`-tiedoston (`tools/ghpush.py`), ja `validate` tarkistaa datan ennen julkaisua. Pystytys: `docs/JULKAISU.md`.
* **Päivitys** on agentin ajo, jonka ohje on `trigger_prompt.txt`: agentti ajaa työkalun komennot, valitsee juridisesti merkittävät uutuudet, kirjoittaa tiivistelmät ja käännökset, ja julkaisee. Työkalu tarkistaa koneellisesti, ettei agentti keksi mitään: lähteen on vastattava, virallisen tiivistelmän on löydyttävä lähteestä sanatarkasti, ja selkoversion luvut on löydyttävä tekstistä.

## Käyttö

```sh
# rakenna sivu osista (part_css.html + part_body.html + part_js.html + data.json + fontit)
python3 build.py

# päivitysajon komennot (ks. trigger_prompt.txt)
python3 tools/lakitv.py extract laki-tv.html data.json     # data ulos sivusta
python3 tools/lakitv.py scan data.json                      # uudet julkaisut lähteistä -> ehdokkaat.json
python3 tools/lakitv.py text URL                            # lähteen teksti tiivistelmää varten
python3 tools/lakitv.py add data.json kko kohde.json        # lisää juttu (tarkistaa lähteen)
python3 tools/lakitv.py he-update data.json                 # eduskunnan HE-tulostaulu
python3 tools/lakitv.py vt-update data.json                 # Finlex: voimaan tulevat lait
python3 tools/lakitv.py validate data.json                  # kaikki tarkistukset
python3 tools/lakitv.py inject laki-tv.html data.json uusi.html
python3 tools/lakitv.py feed data.json --out jakelu         # RSS, JSON, Markdown, kalenteri
python3 tools/lakitv.py viikkokatsaus data.json --out jakelu/viikkokatsaus
python3 tools/lakitv.py digest data.json --laji aamu --muoto slack --out slack.json
python3 tools/lakitv.py post slack.json https://hooks.slack.com/…

# verkkosivusto (GitHub Pages tekee tämän itse; paikallisesti:)
python3 tools/assets.py                                     # kuvakkeet ja jakokuva (kerran)
python3 tools/website.py --page laki-tv.html --feeds jakelu --out site --base https://tunnus.github.io/laki-tv/
python3 tools/ghpush.py tunnus/laki-tv data.json=data.json

# testit (Playwright + Chromium)
./test/run_all.sh
```

`python3 tools/lakitv.py` ilman argumentteja tulostaa kaikki komennot.

## Datamalli

Sivun sisällä on `<script type="application/json" id="laki-tv-data">`. Kaava on kuvattu sivun HTML-kommentissa (`part_body.html`). Pääosat: `kanavat` (13 kanavaa, enintään 9 juttua kussakin), `arkisto` (35 pv), `voimaantulot`, `eu_voimaantulot`, `he_tila`, `he_muutokset`, `visa`, `_ajot` ja `_lahteet` (lähdevahti). Ruotsi ja englanti ovat samojen kenttien `_sv`- ja `_en`-päätteisiä versioita; puuttuva käännös näytetään suomeksi ja merkitään.

## Rajoitukset, jotka kannattaa tietää

* Tiivistelmät ja käännökset ovat tekoälyn tuottamia. Työkalu tarkistaa koneellisesti sen, minkä voi (lähde vastaa, virallinen tiivistelmä täsmää, luvut täsmäävät, päivämäärät ovat kalenterissa), mutta ei juridista tulkintaa. Jokaisessa jutussa on linkki viralliseen lähteeseen, ja lukijan on syytä käyttää sitä.
* Päivitys riippuu ajastetusta agenttiajosta. Jos ajo jää väliin, sivu näyttää yli 20 tuntia vanhan tiedon varoituksena, ja sivu 198 kertoo, mitkä lähteet ovat hiljentyneet.
* Artifaktin syöte- ja kalenteriosoitteet toimivat vain selaimessa linkillä jaettuna; palvelimelta haettuna (RSS-lukijat, kalenteripalvelut) claude.ai vastaa tarkistussivulla. Verkkosivuston osoitteet toimivat kaikkialla, ja siellä kalenteri on oikea `kalenteri.ics`. Artifaktissa kalenteritiedosto on `kalenteri.txt` (iCalendar-sisältö), koska alusta ei tarjoile `.ics`-päätettä.

## Lisenssit

* Koodi ja sivun rakenne: MIT (`LICENSE`).
* Fontit: Bedstead (bjh21, CC0 1.0) ja siitä johdettu LakiCaps (CC0 1.0), joissa Ä, Ö ja Å ovat yhtä korkeita kuin muut isot kirjaimet.
* Sisältö: tuomioistuinten, viranomaisten ja eduskunnan julkaisemat tiedot ovat julkisia; tiivistelmät linkittävät aina alkuperäiseen lähteeseen.

Tämä on riippumaton harrastus- ja oppimisprojekti. Se ei ole oikeudellista neuvontaa eikä liity mihinkään viranomaiseen tai asianajotoimistoon.

---

## English summary

**LAKI-TV** is a legal-news teletext for Finland: Supreme Court and Supreme Administrative Court precedents, CJEU and ECtHR rulings, decisions of the Chancellor of Justice and the Parliamentary Ombudsman, government bills with their parliamentary stage, consultation deadlines and acts entering into force – rendered as 1980s-style teletext pages in Finnish, Swedish and English, updated twice a day.

The page is a single dependency-free HTML file; a 40×25 teletext engine renders every page from the embedded JSON. `tools/website.py` wraps it into a public website (metadata, Open Graph image, PWA with offline cache, real `.ics` calendar) that GitHub Actions builds from the repository's own code and publishes to GitHub Pages whenever the update run pushes a new `data.json` with `tools/ghpush.py` (data is validated before deploy). A Python tool (`tools/lakitv.py`) handles scanning official sources, adding and validating items, parliamentary and Finlex open-data updates, feeds (RSS/JSON/Markdown/iCalendar), a weekly PDF review and Slack/Teams digests. The update itself is an agent run following `trigger_prompt.txt`; the tool enforces that nothing is invented (the source must respond, official summaries must match verbatim, numbers in plain-language versions must appear in the text, dates must exist). Readers can follow items and add deadlines to their own calendar manually; the page stores nothing about its readers and makes no third-party requests.

Code: MIT. Fonts: Bedstead (CC0) and the derived LakiCaps (CC0). Not legal advice; an independent student project.
