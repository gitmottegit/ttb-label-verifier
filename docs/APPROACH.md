# Approach, tools, and assumptions

## The core design decision: AI reads, code decides

The single most important property of a compliance tool is that an agent can
answer *"why was this flagged?"*. So the system is split in two:

1. **Extraction** ([app/extraction.py](../app/extraction.py)) — Claude
   (`claude-sonnet-5`) is used as a resilient OCR/layout reader. It transcribes
   the label verbatim — capitalization preserved — into a JSON record via a
   forced tool call (guaranteed structure, no free-text parsing). It is
   explicitly instructed never to correct or normalize what it reads, and to
   report image-quality problems rather than guess. This is what buys
   robustness to glare, angles, and decorative fonts that broke the previous
   scanning-vendor pilot.

2. **Verification** ([app/verification.py](../app/verification.py)) — every
   verdict is a deterministic, unit-tested Python rule. The government warning
   check is an exact string comparison against the 27 CFR 16.21 text with a
   case-sensitive check on `GOVERNMENT WARNING:`; a failure shows a word-level
   diff. No LLM judgment anywhere in the decision path — which also means the
   decision layer is trivially auditable and cheap to extend.

This split directly addresses two interview concerns at once: Jenny's
"the warning has to be *exact*" (models are bad at exact; code is perfect at
it) and Dave's "you need judgment" (encoded as explicit, reviewable rules —
case-only brand differences match with a note instead of failing).

## Requirements traceability

| Interview signal | Where it landed |
|---|---|
| Sarah: results in ~5 seconds or nobody uses it | Single Sonnet vision call with small output budget; images downscaled to the vision sweet spot before upload; elapsed time shown on every result so slowness is visible, not suspected |
| Sarah: 200–300 label dumps from big importers | `/api/batch`: up to 300 images, 8 concurrent model calls, optional CSV mapping `filename → application fields`, roll-up summary (n passed / n to check / n failed) |
| Sarah: "something my mother could figure out" | One page, two big steps, one button, three verdict colors with plain-language sentences; no jargon (verdicts are "Looks good / Please double-check / Problems found") |
| Jenny: exact warning, all-caps prefix, people get creative | Deterministic exact-text check + case check + word-level diff of any tampering; title-case prefix is an automatic fail (her real example is a unit test and test label #03) |
| Jenny: imperfect photos | Model reports readability issues; these force a "double-check" verdict rather than a silent false pass; unreadable images return a clear "request a better image" style error |
| Dave: STONE'S THROW vs Stone's Throw needs judgment | Case-only difference = match with a note; punctuation/spacing difference = "check formatting" (never silently passed, never hard-failed); his example is a unit test and test label #06 |
| Dave: don't make my life harder | No login, no configuration, no new workflow — drop image, type four fields you already have open in COLA, read the answer |
| Marcus: firewall blocks many outbound domains | Exactly one external dependency: the Anthropic API over HTTPS (single allowlist entry). Documented below as the key production consideration |
| Marcus: standalone proof-of-concept, no COLA integration | Standalone web app; CSV import stands in for a future COLA data feed |

## Tools used

- **FastAPI + Uvicorn** — async Python web framework; async matters because
  batch throughput is I/O-bound on model calls.
- **Anthropic Python SDK** (`claude-sonnet-5`, forced tool use) — vision
  extraction with guaranteed-structure output. Model is swappable via the
  `CLAUDE_MODEL` env var (e.g. Haiku for cheaper/faster triage).
- **Pillow** — upload validation, EXIF auto-orientation, downscaling to the
  vision API's optimal resolution (latency + cost win).
- **Vanilla HTML/CSS/JS** front end — no build step, nothing to break, easy
  for any reviewer to run; appropriate for a two-screen prototype.
- **pytest** — 21 unit tests over the compliance rules.
- **Claude Code** was used as the development environment for this project —
  putting my best AI foot forward includes how I build, not just what I build.

## Assumptions

- **Scope of fields**: verification compares the four fields agents check most
  (brand, class/type, alcohol content, net contents) plus the always-mandatory
  government warning. Bottler address and country of origin are extracted and
  displayed but not auto-compared — the same comparison machinery extends to
  them trivially once the matching rules are agreed with the compliance team.
- **Warning bold requirement**: bold detection from a photo is inherently
  fuzzy, so the model reports an `appears bold` opinion that is surfaced but
  not used to fail a label. Wording and caps — which are checkable exactly —
  are enforced exactly.
- **One label image per application**: multi-image applications (front + back
  label) would need a small extension to group uploads.
- **English-language labels**, consistent with COLA applications.
- **No persistence**: nothing is stored server-side; images are processed in
  memory and discarded (per Marcus: "we're not storing anything sensitive for
  this exercise"). Adding an audit log would be the first production feature.

## Trade-offs and known limitations

- **Cloud API dependency**: the prototype calls the Anthropic API, which the
  TTB firewall would need to allowlist (one domain). For production, the same
  architecture runs against Claude in **AWS GovCloud (Bedrock)** or a
  FedRAMP-authorized deployment — only `extraction.py` changes; the entire
  decision layer is local and offline.
- **Free-tier hosting cold starts**: the demo deployment may take ~30s to wake
  after idling — that's the host's spin-up, not processing time. Per-label
  timing is displayed in-app to keep the two separate.
- **OCR is probabilistic**: a sufficiently distorted label could be
  mis-transcribed. Mitigations: the model must report low confidence and
  readability issues (forcing human review), and the raw transcription is
  always shown so the agent can spot-check what the machine read.
- **Batch CSV matches on filename** — simplest possible contract for a
  prototype; a real integration would key on COLA application ID.

## What I'd do next

1. Side-by-side view: label image with bounding-box highlights on each checked
   field (the vision API can return coordinates).
2. Beverage-type-specific rule packs (wine vintage/appellation, beer specifics,
   standards of fill).
3. Audit log + reviewer feedback loop ("agent overrode: same brand") that
   becomes regression tests for the matching rules.
4. Queue-based batch for the 300-label case with progressive results streaming
   into the table instead of one final response.
