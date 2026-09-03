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
| Dave: don't make my life harder | No login, no configuration, no new workflow, no required typing — drop an image and read the answer; the four comparison fields are optional and batch mode takes them as a CSV instead |
| Marcus: firewall blocks many outbound domains | Exactly one external dependency: the Anthropic API over HTTPS (single allowlist entry). Documented below as the key production consideration |
| Marcus: standalone proof-of-concept, no COLA integration | Standalone web app; CSV import stands in for a future COLA data feed |

## Two questions the requirements invite

**How is a proof of concept "standalone" when it uses an API key?**
"Standalone" in the brief means *no COLA integration* — Marcus: "For this
proof of concept, assume it's a standalone application." It does not mean
air-gapped. The prototype deliberately has exactly one external dependency —
the Anthropic API over HTTPS, a single entry on the firewall allowlist Marcus
worries about — and everything that constitutes a *decision* runs locally in
deterministic code. The production path keeps the architecture intact and
swaps only the endpoint: Claude on AWS GovCloud (Bedrock) or another
FedRAMP-authorized deployment. That swap touches one file
([app/extraction.py](../app/extraction.py)).

**How is it "~5 seconds" if an agent has to type four fields?**
They don't. The 5-second requirement is about processing time — Sarah: "if the
tool takes longer than that to *give a result*, people will just stop using
it." The workflow is designed so typing is never on the critical path:

- Upload alone does a full read of the label and the always-mandatory
  government warning check — zero fields required.
- The four comparison fields exist for when an agent *wants* the label checked
  against the application; each empty field simply skips that comparison.
- At real volume (Sarah's 200–300 label dumps) nobody types anything: batch
  mode takes the application data as a CSV keyed by filename.
- Every single result shows its measured elapsed time, so the 5-second claim
  is continuously verified in front of the user.

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

## Hardening for a public demo URL

Because the deployed prototype is reachable by anyone with the link, it ships
with guardrails a pure localhost demo wouldn't need:

- **Per-IP rate limiting** (40 API requests/minute) so the demo's API budget
  can't be drained by a stray crawler.
- **Bounded memory in batch mode**: images are read under the same semaphore
  that limits concurrent model calls, so at most 8 images are in RAM at once
  even for a 300-file upload on a small instance.
- **Client timeouts**: the Anthropic call is capped at 45 seconds with one
  retry — a hung upstream returns an actionable error instead of a stuck
  spinner.
- **Escaped rendering**: everything the model transcribes (which is ultimately
  attacker-controllable via the label image) is HTML-escaped before display.

## What I'd do next

1. Side-by-side view: label image with bounding-box highlights on each checked
   field (the vision API can return coordinates).
2. Beverage-type-specific rule packs (wine vintage/appellation, beer specifics,
   standards of fill).
3. Audit log + reviewer feedback loop ("agent overrode: same brand") that
   becomes regression tests for the matching rules.
4. Queue-based batch with results streaming into the table row-by-row (the UI
   already chunks uploads into groups of 24 for genuine progress reporting;
   a server-side queue is the next step).
