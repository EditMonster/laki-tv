# Verkkosivuston pystytys ja automaattinen päivitys

LAKI-TV:n verkkosivusto rakennetaan GitHub Actionsissa tämän varaston koodista ja julkaistaan GitHub Pagesiin.
Sisältö tulee **erillisestä datavarastosta** – GitHub-gististä – johon ajastettu päivitysajo työntää vain `data.json`-tiedoston.
(Gist siksi, että Claude-istunnon git-välityspalvelin estää työnnöt tavallisiin varastoihin, joita istuntoon ei ole liitetty;
gist.github.com kulkee sen ohi. Tavallinen varasto `omistaja/nimi` toimii muissa ympäristöissä samalla tavalla.)

## Turvamalli

| Osa | Mitä saa tehdä | Millä oikeudella |
|---|---|---|
| Päivitysajo (agentti) | työntää `data.json`-tiedoston gistiin | classic token, jolla on vain gist-oikeus (ei repo- eikä tilioikeuksia); `tools/ghpush.py` kieltäytyy muista tiedostoista, tunnuksilta näyttävästä sisällöstä ja datasta, joka ei läpäise `validate`-tarkistusta |
| Koodivarasto (tämä) | rakentaa ja julkaisee sivuston | vain omistaja työntää koodia (GitHub Desktop); Actions-oikeudet vain lukuun ja Pages-julkaisuun |
| Actions-työnkulku `pages.yml` | hakee datan gististä kaksi kertaa tunnissa, tarkistaa sen (`validate`) ja julkaisee, jos data on uudempi kuin sivustolla | ei tunnuksia; gistin raw-osoite on luettavissa ilman kirjautumista |
| Sivun suora data | julkaistu sivu hakee itse gistin uusimman `data.json`-tiedoston ja näyttää sen, jos se on uudempi kuin sivuston kopio | ei tunnuksia; vain rakennetarkistuksen läpäisevä ja vähintään puolet nykyisestä juttumäärästä sisältävä data kelpaa |
| `vahti.yml` | hälyttää sähköpostilla, jos data on yli 20 tuntia vanhaa | ei tunnuksia |

Vaikka ajon avain vuotaisi, sillä ei pääse koodivarastoon eikä tiliin: pahimmillaan gistiin voisi työntää väärää dataa, jonka `validate` ja sivun rakenne rajaavat tekstisisällöksi. Avain kannattaa silti uusia vuosittain (tokenin voimassaoloaika).

## Pystytys

1. **Gist.** gist.github.com → tiedostonimi `data.json`, sisältö `{}` → *Create secret gist* (tai public; sisältö on joka tapauksessa julkista). Osoitteen loppuosa on gistin tunnus (32 merkkiä).
2. **Avain.** GitHub → Settings → Developer settings → Personal access tokens → *Tokens (classic)* → Generate new token (classic). Nimi `laki-tv-ajo`, voimassaolo enintään vuosi, rasti vain **gist**. Kopioi avain talteen; se näytetään vain kerran.
3. **Ajon asetus.** Avaa LAKI-TV-artifakti omistajana → NÄPPÄIMISTÖ → JAKELU → *Viestikanavat (ylläpitäjä)*: datavarasto `gist:TUNNUS` ja avain. Ne tallentuvat sivun omistajalle rajattuun asetukseen (`asetukset/jakelu`), josta vain päivitysajo lukee ne.
4. **Koodivarasto.** Settings → Pages → Source: *GitHub Actions*. Gistin tunnus (8cdf55f7…) on työnkulussa oletusarvona; toisen gistin tai varaston voi antaa muuttujalla `LAKITV_DATA_REPO` (`gist:TUNNUS` tai `omistaja/nimi`) tai suoralla osoitteella `LAKITV_DATA_URL` (Settings → Secrets and variables → Actions → Variables). Oma verkkotunnus: muuttuja `LAKITV_DOMAIN` ja DNS-CNAME GitHub Pagesiin.
5. **Tarkistus.** Seuraavan ajon raportissa lukee "GitHub-peilaus: commit …". Actions-välilehdellä `pages` ajaa kaksi kertaa tunnissa; ilman uutta dataa se päättyy heti ("Ei uutta dataa – ei julkaista"). Sivun 198 TILA rivillä *Päivitetty* lukee **SUORA**, kun näytetty data on haettu gististä eikä sivuston omasta kopiosta.

## Miksi sivu hakee datan itse

GitHub viivästää ja jättää väliin ajastettuja Actions-ajoja etenkin uusissa varastoissa (dokumentoitu rajoitus: "schedule event can be delayed … some queued jobs may be dropped"). Siksi sivusto ei nojaa pelkästään rakennusajoon: `tools/website.py --data-url` kirjoittaa sivulle `<meta name="lakitv-data">`-rivin, ja sivu hakee käynnistyessään gistin uusimman datan (CORS sallittu, välimuisti 5 min). Uudempi data talletetaan välilehden `sessionStorage`-muistiin ja sivu latautuu uudelleen samalle sivulle – heti, jos lukija ei ole vielä tehnyt mitään, muuten seuraavassa sivunvaihdossa. Artifaktissa ja paikallisessa kopiossa meta-riviä ei ole, eikä mitään haeta. Syötteet (RSS, JSON, kalenteri, viikkokatsaus) päivittyvät vasta rakennusajossa.

## Käsin päivitys

Jos ajo ei pääse GitHubiin, datan voi viedä käsin: `python3 tools/lakitv.py extract laki-tv.html data.json` artifaktin sivusta, ja sisältö gistiin (Edit) – tai tämän varaston `data.json`-tiedostoon, jota työnkulku käyttää varalla, jos gistiä ei saada luettua tai se on vielä tyhjä.

## Pystytys paikallisesti

```sh
python3 build.py                                   # laki-tv.html ja preview.html
python3 tools/lakitv.py feed data.json --out jakelu
python3 tools/website.py --page laki-tv.html --feeds jakelu --out site --base https://tunnus.github.io/laki-tv/
python3 -m http.server -d site 8000               # http://localhost:8000/
```
