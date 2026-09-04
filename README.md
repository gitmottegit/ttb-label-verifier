# TTB Label Verifier

AI-assisted verification of alcohol beverage label applications — a prototype
built for the TTB take-home project.

Upload a label image and get a plain-language **Pass / Double-check / Fail**
answer in a few seconds — no typing required. The label is read in full and its
government warning always checked; the four application fields (brand, class,
alcohol, net contents) are optional extras for when you want the label compared
against what the COLA application says. A batch mode accepts up to 300 labels
at once, with an optional CSV of application data. The home page includes
one-click example labels so you can try it without any files of your own.

**How it works in one sentence:** Claude vision *reads* the label (it tolerates
glare, angles, and odd fonts); deterministic Python *decides* — every
compliance verdict comes from an auditable rule, never from model judgment.

See [docs/APPROACH.md](docs/APPROACH.md) for design decisions, trade-offs, and
assumptions.

## Two fair questions

**"Standalone" — but it calls a cloud API?** Standalone here means what the
project brief means: no COLA system integration and no infrastructure to stand
up — one process, one page, zero databases. The prototype has exactly one
external dependency, the Anthropic API over HTTPS (a single firewall-allowlist
entry). For production inside Treasury's network boundary, the identical
architecture runs against Claude on AWS GovCloud (Bedrock) or another
FedRAMP-authorized endpoint — only `extraction.py` changes; every compliance
decision is already made locally in code.

**"~5 seconds" — including typing?** The 5-second target is machine time per
label, and the workflow is built so typing is optional: upload alone reads the
full label and always checks the government warning. Agents only fill fields
when they want a comparison against the application — and in batch mode even
that is a CSV attachment, not typing. Every result displays its actual elapsed
seconds so speed is verified, not claimed.

## What it checks

| Check | Rule |
|---|---|
| Brand name | Case-only differences match with a note (`STONE'S THROW` = `Stone's Throw`); punctuation/spacing differences are flagged "check formatting"; real differences fail |
| Class / type | Same text rules as brand name |
| Alcohol content | Compared numerically (`45% Alc./Vol.` = `45.0 % alc/vol`); proof is cross-checked against ABV (90 proof must equal 45%) |
| Net contents | Compared by volume with unit conversion (`750 mL` = `0.75 L`) |
| Government warning | Always checked: must be present, word-for-word exact per 27 CFR 16.21, and `GOVERNMENT WARNING:` must be all-caps. Failures include a word-level diff of what changed |
| Image quality | Glare / angle / blur issues are reported and force a "double-check" verdict instead of a false pass |

## Run it locally

> **Reviewing from a restricted network?** If your firewall blocks the hosted
> demo URL, the local setup below takes about 3 minutes and needs outbound
> HTTPS to `api.anthropic.com` only.

Requires Python 3.11+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/gitmottegit/ttb-label-verifier.git
cd ttb-label-verifier
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env    # then put your ANTHROPIC_API_KEY in .env  (cp on macOS/Linux)
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and try the images in [`test_labels/`](test_labels/)
— one compliant label and five with realistic violations, plus
[`applications.csv`](test_labels/applications.csv) for batch mode.

### Docker

```bash
docker build -t label-verifier .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your-key label-verifier
```

## Tests

The compliance rules are pure functions with unit tests (including the
title-case warning and case-variant brand scenarios from the discovery
interviews):

```bash
pip install -r requirements-dev.txt
pytest
```

Regenerate the synthetic test labels with
`python scripts/generate_test_labels.py`.

## Deploy

The repo includes a [`render.yaml`](render.yaml) blueprint (Render) and a
`Dockerfile` (any container host). Set one environment variable:
`ANTHROPIC_API_KEY`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/verify` | One image + form fields → verification report |
| `POST /api/batch` | Up to 300 images + optional `applications.csv` → per-file reports, processed 8 at a time in parallel |
| `GET /api/health` | Liveness + configuration probe |

## Project layout

```
app/
  main.py          FastAPI endpoints, batch orchestration
  extraction.py    Claude vision call — transcription only, forced JSON via tool use
  verification.py  All compliance rules (pure, unit-tested)
static/            Vanilla HTML/CSS/JS single-page UI — no build step
scripts/           Synthetic test-label generator (Pillow)
test_labels/       Generated fixtures: 1 compliant + 5 violation labels + CSV
tests/             Unit tests for every compliance rule
```
