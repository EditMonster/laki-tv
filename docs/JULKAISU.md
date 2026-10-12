# Verkkosivuston pystytys ja automaattinen päivitys

LAKI-TV:n verkkosivusto rakennetaan GitHub Actionsissa tämän varaston koodista ja julkaistaan GitHub Pagesiin.
Sisältö tulee **erillisestä datavarastosta**, johon ajastettu päivitysajo työntää vain `data.json`-tiedoston.

## Turvamalli

| Osa | Mitä saa tehdä | Millä oikeudella |
|---|---|---|
| Päivitysajo (agentti) | työntää `data.json`-tiedoston datavarastoon | fine-grained token, joka on rajattu vain datavarastoon ja Contents-oikeuteen; `tools/ghpush.py` kieltäytyy muista tiedostoista ja tunnuksilta näyttävästä sisällöstä |
| Koodivarasto (tämä) | rakentaa ja julkaisee sivuston | vain omistaja työntää koodia (GitHub Desktop); Actions-oikeudet vain lukuun ja Pages-julkaisuun |
| Actions-työnkulku `pages.yml` | hakee datan datavarastosta tunneittain, tarkistaa sen (`validate`) ja julkaisee, jos data on uudempi kuin sivustolla | ei tunnuksia; datavarasto on julkinen |
| `vahti.yml` | hälyttää sähköpostilla, jos data on yli 20 tuntia vanhaa | ei tunnuksia |

Vaikka ajon avain vuotaisi, sillä ei pääse koodivarastoon: pahimmillaan datavarastoon voisi työntää väärää dataa, jonka `validate` ja sivun rakenne rajaavat tekstisisällöksi. Avain kannattaa silti uusia vuosittain (tokenin voimassaoloaika).

## Pystytys

1. **Datavarasto.** Luo GitHubissa uusi julkinen varasto `laki-tv-data` (valitse "Add a README file", jotta main-haara syntyy). Älä anna Claude-GitHub-sovellukselle pääsyä siihen: avain hoitaa työnnön, ja näin ajon istunto ei saa muita oikeuksia.
2. **Avain.** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token. Nimi `laki-tv-ajo`, voimassaolo enintään vuosi, Repository access: *Only select repositories* → `laki-tv-data`, Permissions → Repository permissions → *Contents: Read and write* (Metadata tulee automaattisesti). Kopioi avain talteen; se näytetään vain kerran.
3. **Ajon asetus.** Avaa LAKI-TV-artifakti omistajana → JAKELU → *Viestikanavat (ylläpitäjä)*: datavarasto `omistaja/laki-tv-data` ja avain. Ne tallentuvat sivun omistajalle rajattuun asetukseen (`asetukset/jakelu`), josta vain päivitysajo lukee ne.
4. **Koodivarasto.** Settings → Pages → Source: *GitHub Actions*. Jos datavaraston nimi on muu kuin `EditMonster/laki-tv-data`, lisää Settings → Secrets and variables → Actions → Variables: `LAKITV_DATA_REPO` = `omistaja/laki-tv-data`. Oma verkkotunnus: muuttuja `LAKITV_DOMAIN` ja DNS-CNAME GitHub Pagesiin.
5. **Tarkistus.** Seuraavan ajon raportissa lukee "GitHub-peilaus: commit …". Actions-välilehdellä `pages` ajaa tunneittain; ilman uutta dataa se päättyy heti ("Ei uutta dataa – ei julkaista").

## Käsin päivitys

Jos ajo ei pääse GitHubiin, datan voi viedä käsin: `python3 tools/lakitv.py extract laki-tv.html data.json` artifaktin sivusta, commit datavarastoon – tai tämän varaston `data.json`-tiedostoon, jota työnkulku käyttää varalla, jos datavarastoa ei saada luettua.

## Pystytys paikallisesti

```sh
python3 build.py                                   # laki-tv.html ja preview.html
python3 tools/lakitv.py feed data.json --out jakelu
python3 tools/website.py --page laki-tv.html --feeds jakelu --out site --base https://tunnus.github.io/laki-tv/
python3 -m http.server -d site 8000               # http://localhost:8000/
```
