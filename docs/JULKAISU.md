# Julkaisu ja ylläpito

LAKI-TV:llä on kaksi julkaisupaikkaa. **Artifakti** (claude.ai) on moottori: ajastettu päivitysajo kirjoittaa sinne datan ja jakelutiedostot. **Verkkosivusto** (GitHub Pages, oma domain) on julkinen osoite lukijoille, hakukoneille, RSS-lukijoille ja kalentereille: sama sivu hakukone- ja jakotiedoilla, PWA:na ja oikealla `.ics`-kalenterilla. Sivusto rakennetaan artifaktista työnnetystä sisällöstä, joten kumpaakaan ei ylläpidetä käsin.

## 1. Artifakti (moottori)
1. `python3 build.py` tuottaa `laki-tv.html`.
2. Julkaise se artifaktina. Kyvyt (capabilities): `db` säännöllä `asetukset` (read owner, write owner), `user`, `downloads`. Mitään muuta tietokantapolkua ei tarvita: sivu ei tallenna lukijoista mitään.
3. Julkaise rinnalle `tools/lakitv.py` nimellä `tools/lakitv.py.txt` (contentType text/plain) sekä `feed`-komennon tiedostot.
4. Ajastetut ajot: `docs/trigger_prompt.txt` (pääajo klo 6.45 ja 14.45 Europe/Helsinki) ja `docs/trigger_prompt_varmistus.txt` (klo 8.15, tekee aamuajon vain jos se jäi väliin). Ajo ei koskaan muuta sivun koodia, vain JSON-lohkon ja jakelutiedostot.

## 2. Verkkosivusto (GitHub Pages)

### Kertaluonteinen pystytys
1. Luo GitHubiin **julkinen** varasto (esim. `laki-tv`) ja työnnä tämän paketin sisältö sinne (`git init && git add -A && git commit -m "LAKI-TV" && git push`). Mukana oleva `source/`-kansio on sivun ja syötteiden tuorein tilannekuva, joten sivusto syntyy heti ensimmäisestä työnnöstä.
2. Varaston asetukset → **Pages** → Build and deployment → Source: **GitHub Actions**. Työnkulku `.github/workflows/pages.yml` rakentaa sivuston (`tools/website.py`) ja julkaisee sen aina, kun `source/` tai `data.json` muuttuu.
3. Sivusto on osoitteessa `https://<tunnus>.github.io/laki-tv/` muutaman minuutin kuluttua. Actions-välilehti näyttää ajon.

### Sisällön peilaus artifaktista
Päivitysajo työntää julkaisun jälkeen `data.json`-tiedoston sekä sivun ja syötteet `source/`-kansioon työkalulla `tools/ghpush.py` (yksi commit GitHubin Git Data -rajapinnalla, ei git-ohjelmaa, ei tokeneita paketissa). Pystytys:
1. Yhdistä GitHub claude.ai:n Connectors-asetuksissa (sama tili, jolla ajot ajetaan) ja anna sille oikeus varastoon.
2. Avaa sivun JAKELU-paneeli omistajana ja kirjoita kenttään *GitHub-varasto* nimi muodossa `omistaja/laki-tv`. Se tallentuu dokumenttiin `asetukset/jakelu` (vain omistajan luettavissa) webhookien rinnalle.
3. Päivitysajon ohjeeseen lisätään peilausaskel (ajo lukee `github_repo`-kentän, hakee `tools/ghpush.py.txt`:n artifaktista ja työntää `data.json`-tiedoston, sivun ja syötteet). Tämä askel päätetään ja lisätään erikseen – ajo ohittaa peilauksen, kunnes se on ohjeessa. Askel edellyttää, että `tools/ghpush.py` on julkaistu artifaktin rinnalle nimellä `tools/ghpush.py.txt` (contentType text/plain) kuten `tools/lakitv.py.txt`.
4. Ensimmäisen ajon raportti kertoo, onnistuiko työntö (commitin tunnus) vai ei (syy). Jos istunnolla ei ole GitHub-yhteyttä, ajo kirjaa sen eikä yritä muuta.

Käsin peilaus (ilman ajoa, esim. omalta koneelta): `GITHUB_TOKEN=<fine-grained PAT, Contents: read/write> python3 tools/ghpush.py omistaja/laki-tv -m "LAKI-TV 4.10." data.json=data.json laki-tv.html=source/laki-tv.html out=source` – tai ilman tokenia, kun `gh`-komento on kirjautuneena.

### Vahti
`.github/workflows/vahti.yml` tarkistaa joka aamu, että `data.json` on alle 20 tuntia vanha; muuten työnkulku epäonnistuu ja GitHub lähettää varaston omistajalle sähköpostin. Näin huomaat sekä väliin jääneen ajon että katkenneen peilauksen ilman, että sivua tarvitsee käydä katsomassa.

### Oma domain
1. Osta domain (esim. `laki-tv.fi`, Traficomin rekisteröidyn välittäjän kautta).
2. DNS: `www` → CNAME `<tunnus>.github.io.`; juuri (apex) → A-tietueet `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` (ja AAAA `2606:50c0:8000::153` … `8003::153`).
3. Varaston asetukset → Pages → Custom domain: kirjoita domain, odota DNS-tarkistus, valitse **Enforce HTTPS**.
4. Varaston asetukset → Secrets and variables → Actions → Variables: `LAKITV_DOMAIN = laki-tv.fi` (kirjoittaa `CNAME`-tiedoston joka julkaisuun). Canonical- ja og:url-osoitteet seuraavat automaattisesti Pages-asetuksen osoitetta.

### Mitä sivusto sisältää
`tools/website.py` tuottaa kansion `site/`: `index.html` (sivu + `<head>`: kuvaus, canonical, Open Graph/Twitter, RSS-vaihtoehdot, manifest), `feed*.xml`, `feed.json`, `lakitv.md`, `kalenteri*.ics` (tekstitiedostoista uudelleennimettyinä; myös sivun sisäiset viittaukset vaihdetaan), `viikkokatsaus.html/.pdf`, `manifest.webmanifest`, `sw.js` (verkko ensin, välimuisti varalla: viimeisin sisältö näkyy ilman yhteyttä), kuvakkeet, `og.png` (sivu 100, päivitetään joka julkaisussa Playwrightilla; epäonnistuessa jää edellinen), `robots.txt`, `sitemap.xml`, `404.html`, `.nojekyll` ja tarvittaessa `CNAME`. Sivuston osoitteessa `window.claude` puuttuu, joten `.ics`-nappi lataa tiedoston suoraan ja JAKELU-paneelin ylläpitolomake ei näy.

Kuvakkeet ja oletusjakokuva tehdään kerran komennolla `python3 tools/assets.py` (kansioon `assets/`).

## Palautekanava
`part_js.html`: `const FEEDBACK_URL = "";` – anna GitHub-issuiden osoite (`https://github.com/<tunnus>/laki-tv/issues`) tai `mailto:`-osoite, niin juttusivuille tulee ILMOITA VIRHEESTÄ -rivi. Tyhjänä riviä ei näytetä.

## Slack/Teams
Sivun omistaja avaa JAKELU-paneelin kirjautuneena ja antaa webhook-osoitteet. Ne tallentuvat vain omistajan luettavaan dokumenttiin `asetukset/jakelu`; päivitysajo lähettää aamukoosteen ja painon 5 jutut iltapäivällä.

## Testit
`./test/run_all.sh` rakentaa sivun, siirtää kiinteän testidatan (`test/fixture_base.json`, 30.9.2026) tähän päivään ja ajaa kaikki sarjat Playwrightilla (Chromium), lopuksi `test/site_test.py`, joka rakentaa sivuston alipolkuun `/laki-tv/` paikalliselle palvelimelle ja tarkistaa metatiedot, syötteet, `.ics`-kalenterin, manifestin, service workerin ja offline-tilan, latauksen ja syvälinkit. Vaatii `pip install playwright lxml fonttools && playwright install chromium`.
