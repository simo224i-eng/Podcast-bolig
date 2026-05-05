# Bolius-podcast — byggeteknik som lyd

Genererer automatisk en dansk podcast-feed med oplæste Bolius-artikler om byggeteknik, så du kan abonnere i Apple Podcasts/Overcast og lytte mens du arbejder.

## Hvad det gør

Læser en liste af Bolius-URL'er fra `articles.txt`, henter og renser artikelteksten med trafilatura, syntetiserer en mp3 med Microsofts gratis edge-tts (dansk stemme), og bygger en gyldig podcast RSS 2.0-feed med iTunes-tags. GitHub Actions kører hele molevitten hver søndag og committer mp3'er + `feed.xml` tilbage til repoet, så GitHub Pages kan hoste det.

Alt er gratis — ingen API-nøgler, ingen abonnementer.

## Setup lokalt

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Kør lokalt

```bash
python -m src.main --verbose
```

Det opretter `docs/<slug>-<hash>.mp3` for hver ny artikel og skriver `docs/feed.xml`. Allerede behandlede artikler (registreret i `state/processed.json`) springes over ved næste kørsel.

Andre flag:

```bash
# Skift stemme (default: da-DK-JeppeNeural; alternativ: da-DK-ChristelNeural)
python -m src.main --voice da-DK-ChristelNeural

# Find aktuelle Bolius-URL'er for et emne (når en URL i articles.txt er 404)
python -m src.main --find-topic skimmel
python -m src.main --find-topic "tag levetid" --limit 5
```

## Tilføj nye artikler

1. Find URL'er på [bolius.dk](https://www.bolius.dk) (eller brug `--find-topic`).
2. Tilføj én pr. linje i `articles.txt`. Linjer der starter med `#` ignoreres.
3. Commit + push. GitHub Action kører søndag aften — eller trigger manuelt fra fanen **Actions → Generate podcast → Run workflow**.

## Deploy til GitHub Pages

1. Push til GitHub.
2. **Settings → Pages**:
   - **Source**: `Deploy from a branch`
   - **Branch**: `main`, folder `/docs`
3. Vent et minut. Din feed-URL bliver:
   ```
   https://<dit-brugernavn>.github.io/<repo-navn>/feed.xml
   ```
4. (Valgfrit) Sæt en `AUDIO_BASE_URL`-variabel i workflow-environment hvis du hoster lyd andetsteds. Default udledes af `GITHUB_REPOSITORY`.

## Abonnér i Apple Podcasts

Apple Podcasts-app: **File / Library → Add a Show by URL** → indsæt feed-URL'en. I Overcast: **+ → Add URL**. I de fleste andre podcast-apps: søg efter "Add by URL" eller "Add RSS feed".

Bemærk: Apple's katalog tager nogle dage at indeksere offentlige feeds, men private abonnementer via "Add by URL" virker med det samme.

## Skift stemme

To steder du kan ændre default-stemmen:

- **Engangsbasis**: `python -m src.main --voice da-DK-ChristelNeural`
- **Permanent**: rediger `DEFAULT_VOICE` i `src/tts.py`, eller sæt env-variablen `TTS_VOICE`. I GitHub Actions kan du sætte den under workflow_dispatch-input.

Tilgængelige danske stemmer (edge-tts):
- `da-DK-JeppeNeural` — mandlig (default)
- `da-DK-ChristelNeural` — kvindelig

Liste alle: `edge-tts --list-voices | grep da-DK`.

## Hvordan det er bygget

```
src/scrape.py     Hent og rens artikeltekst (requests + trafilatura)
src/tts.py        Edge-TTS wrapper med chunking til lange tekster
src/feed.py       RSS 2.0 + iTunes-tags via feedgen
src/main.py       Orkestrering, state-tracking, CLI

state/processed.json    Hvilke URL'er der allerede er konverteret
docs/                 mp3-filer + feed.xml (committes til repoet)
```

### Designvalg

- **Trafilatura** valgt over readability/newspaper3k fordi den er bedst til skandinaviske sider og fjerner mest boilerplate uden tuning.
- **Edge-TTS** brugt i streaming-mode, og chunks (>3000 tegn) appendes som rå mp3-bytes. mp3-frames kan koncateneres binært uden re-kodning, så vi undgår `pydub`/`ffmpeg`-afhængighed.
- **Feedgen** giver os iTunes-tags out of the box; vi sorterer episoder nyeste-først i Python frem for at stole på feedgen's interne orden.
- **Idempotent**: `processed.json` er nøglen. Slet en linje derfra (og tilhørende mp3) hvis du vil regenerere en episode.
- **Pinned versioner** i `requirements.txt` for at undgå overraskelser ved cron-kørsler.

## Kendte begrænsninger

- Bolius-URL'er ændrer sig af og til. Hvis en URL 404'er logges det og resten af kørslen fortsætter. Brug `--find-topic` til at finde alternativer.
- edge-tts er en uofficiel klient til Microsofts Edge Read-Aloud-tjeneste. Den er gratis, men kan i teorien rate-limites. Workflowet processerer kun nye artikler, så belastningen er lille.

## Test

```bash
pip install pytest
pytest
```

Tester scrape.py mod en lokal HTML-fixture — ingen netværk nødvendigt.

## Licens

MIT (kode). Bolius-artiklernes ophavsret tilhører Bolius — feed'et er kun til personligt brug.
