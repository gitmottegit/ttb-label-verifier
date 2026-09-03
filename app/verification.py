"""Deterministic compliance checks.

Design principle: the AI model only *reads* the label (OCR + layout). Every
compliance decision below is made by plain, auditable Python so a reviewing
agent can always answer "why was this flagged?" with an exact rule.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

# 27 CFR Part 16 — mandatory health warning, verbatim.
WARNING_PREFIX = "GOVERNMENT WARNING:"
WARNING_BODY = (
    "(1) According to the Surgeon General, women should not drink alcoholic "
    "beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a "
    "car or operate machinery, and may cause health problems."
)

# Verdicts for a single field check.
MATCH = "match"                      # exact or case-only difference
MATCH_FORMATTING = "match_formatting"  # same content, formatting differs — agent should glance
MISMATCH = "mismatch"
MISSING = "missing"                  # expected but not found on label
NOT_CHECKED = "not_checked"          # no application value supplied

# Overall verdicts.
PASS = "pass"
NEEDS_REVIEW = "needs_review"
FAIL = "fail"


@dataclass
class FieldResult:
    name: str
    label_value: str | None
    application_value: str | None
    verdict: str
    note: str = ""


@dataclass
class WarningResult:
    present: bool
    prefix_all_caps: bool
    wording_exact: bool
    verdict: str
    label_text: str | None = None
    problems: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    overall: str
    summary: str
    fields: list[FieldResult] = field(default_factory=list)
    warning: WarningResult | None = None
    readability_issues: list[str] = field(default_factory=list)


# --- text normalization -----------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s%.]", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Smart quotes/dashes appear constantly in label artwork; treat them as their
# ASCII equivalents before any comparison.
_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    return _WS_RE.sub(" ", text).strip()


def _fold(text: str) -> str:
    return clean(text).casefold()


def _fold_loose(text: str) -> str:
    # Squash punctuation and spacing entirely so "Stone's Throw" and
    # "Stones Throw" compare equal — flagged for a glance, not auto-failed.
    return _WS_RE.sub("", _PUNCT_RE.sub("", _fold(text)))


# --- field comparisons ------------------------------------------------------

def compare_text_field(name: str, label_value: str | None, app_value: str | None) -> FieldResult:
    """Compare a free-text field (brand name, class/type)."""
    if not app_value or not app_value.strip():
        return FieldResult(name, label_value, app_value, NOT_CHECKED)
    if not label_value or not label_value.strip():
        return FieldResult(name, label_value, app_value, MISSING,
                           "Not found on the label.")
    lv, av = clean(label_value), clean(app_value)
    if lv == av:
        return FieldResult(name, lv, av, MATCH)
    if lv.casefold() == av.casefold():
        # e.g. STONE'S THROW vs Stone's Throw — same name, different case.
        return FieldResult(name, lv, av, MATCH,
                           "Same text; capitalization differs.")
    if _fold_loose(lv) == _fold_loose(av):
        return FieldResult(name, lv, av, MATCH_FORMATTING,
                           "Same words; punctuation or spacing differs.")
    return FieldResult(name, lv, av, MISMATCH,
                       "Label does not match the application.")


_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.IGNORECASE)


def parse_abv(text: str | None) -> float | None:
    if not text:
        return None
    m = _ABV_RE.search(text)
    return float(m.group(1)) if m else None


def parse_proof(text: str | None) -> float | None:
    if not text:
        return None
    m = _PROOF_RE.search(text)
    return float(m.group(1)) if m else None


def compare_alcohol_content(label_value: str | None, app_value: str | None) -> FieldResult:
    """Compare ABV numerically; '45% Alc./Vol.' == '45.0 % alc/vol'."""
    name = "alcohol_content"
    if not app_value or not app_value.strip():
        return FieldResult(name, label_value, app_value, NOT_CHECKED)
    if not label_value or not label_value.strip():
        return FieldResult(name, label_value, app_value, MISSING,
                           "No alcohol content found on the label.")
    label_abv, app_abv = parse_abv(label_value), parse_abv(app_value)
    if label_abv is None or app_abv is None:
        # Can't parse a number out of one side — fall back to text comparison.
        result = compare_text_field(name, label_value, app_value)
        if result.verdict == MATCH:
            return result
        return FieldResult(name, label_value, app_value, MATCH_FORMATTING,
                           "Could not read a % value; compare by eye.")
    if abs(label_abv - app_abv) > 0.05:
        return FieldResult(name, label_value, app_value, MISMATCH,
                           f"Label says {label_abv}% but application says {app_abv}%.")
    note = ""
    proof = parse_proof(label_value)
    if proof is not None and abs(proof - 2 * label_abv) > 0.1:
        return FieldResult(name, label_value, app_value, MISMATCH,
                           f"Label's proof ({proof}) does not equal twice its ABV ({label_abv}%).")
    if proof is not None:
        note = f"Proof cross-check OK ({proof} proof = {label_abv}% ABV)."
    return FieldResult(name, label_value, app_value, MATCH, note)


_NET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|l|L|cl|cL|fl\.?\s*oz\.?|oz)", re.IGNORECASE)
_TO_ML = {"ml": 1.0, "l": 1000.0, "cl": 10.0, "fl oz": 29.5735, "oz": 29.5735}


def parse_net_contents_ml(text: str | None) -> float | None:
    if not text:
        return None
    m = _NET_RE.search(text)
    if not m:
        return None
    qty = float(m.group(1))
    unit = re.sub(r"[.\s]+", " ", m.group(2).lower()).strip()
    if "oz" in unit:
        unit = "fl oz"  # bare "oz" on a beverage label means fluid ounces
    factor = _TO_ML.get(unit)
    return qty * factor if factor is not None else None


def compare_net_contents(label_value: str | None, app_value: str | None) -> FieldResult:
    """Compare net contents by volume; '750 mL' == '750ml' == '0.75 L'."""
    name = "net_contents"
    if not app_value or not app_value.strip():
        return FieldResult(name, label_value, app_value, NOT_CHECKED)
    if not label_value or not label_value.strip():
        return FieldResult(name, label_value, app_value, MISSING,
                           "No net contents found on the label.")
    label_ml, app_ml = parse_net_contents_ml(label_value), parse_net_contents_ml(app_value)
    if label_ml is None or app_ml is None:
        result = compare_text_field(name, label_value, app_value)
        if result.verdict in (MATCH, MATCH_FORMATTING):
            return result
        return FieldResult(name, label_value, app_value, MATCH_FORMATTING,
                           "Could not read a volume; compare by eye.")
    if abs(label_ml - app_ml) > 0.5:
        return FieldResult(name, label_value, app_value, MISMATCH,
                           f"Label volume ({label_ml:g} mL) differs from application ({app_ml:g} mL).")
    return FieldResult(name, label_value, app_value, MATCH)


# --- government warning -----------------------------------------------------

def check_government_warning(verbatim: str | None) -> WarningResult:
    """Exact, case-aware check of the mandatory health warning.

    The statement must be word-for-word, and 'GOVERNMENT WARNING:' must be in
    capital letters (27 CFR 16.21). Wording is compared case-insensitively for
    the body but the prefix must be exactly all-caps.
    """
    if not verbatim or not verbatim.strip():
        return WarningResult(
            present=False, prefix_all_caps=False, wording_exact=False,
            verdict=FAIL, problems=["No government warning found on the label."])

    text = clean(verbatim)
    problems: list[str] = []

    prefix_match = re.match(r"(government\s+warning\s*:)", text, re.IGNORECASE)
    prefix_all_caps = False
    if prefix_match:
        found_prefix = _WS_RE.sub(" ", prefix_match.group(1))
        prefix_all_caps = found_prefix.replace(" :", ":") == WARNING_PREFIX
        if not prefix_all_caps:
            problems.append(
                f'"{found_prefix}" must be in capital letters: "{WARNING_PREFIX}".')
        body = text[prefix_match.end():].strip()
    else:
        problems.append('Statement does not begin with "GOVERNMENT WARNING:".')
        body = text

    wording_exact = _fold(body) == _fold(WARNING_BODY)
    if not wording_exact:
        diff = _word_diff(WARNING_BODY, body)
        problems.append("Wording is not exact. " + diff if diff
                        else "Wording is not exact.")

    verdict = PASS if (prefix_all_caps and wording_exact) else FAIL
    return WarningResult(
        present=True, prefix_all_caps=prefix_all_caps,
        wording_exact=wording_exact, verdict=verdict,
        label_text=text, problems=problems)


def _word_diff(expected: str, actual: str, limit: int = 4) -> str:
    """Human-readable summary of the first few word-level differences."""
    exp, act = _fold(expected).split(), _fold(actual).split()
    changes = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, exp, act).get_opcodes():
        if op == "equal":
            continue
        was, now = " ".join(exp[i1:i2]), " ".join(act[j1:j2])
        if op == "delete":
            changes.append(f'missing "{was}"')
        elif op == "insert":
            changes.append(f'added "{now}"')
        else:
            changes.append(f'"{was}" changed to "{now}"')
        if len(changes) >= limit:
            changes.append("…")
            break
    return "; ".join(changes)


# --- report assembly --------------------------------------------------------

def build_report(extracted: dict, application: dict) -> VerificationReport:
    """Combine model-extracted label fields with the application data."""
    fields = [
        compare_text_field("brand_name", extracted.get("brand_name"),
                           application.get("brand_name")),
        compare_text_field("class_type", extracted.get("class_type"),
                           application.get("class_type")),
        compare_alcohol_content(extracted.get("alcohol_content"),
                                application.get("alcohol_content")),
        compare_net_contents(extracted.get("net_contents"),
                             application.get("net_contents")),
    ]
    warning = check_government_warning(extracted.get("government_warning_verbatim"))

    readability = [str(i) for i in (extracted.get("readability_issues") or [])]

    if warning.verdict == FAIL or any(f.verdict in (MISMATCH, MISSING) for f in fields):
        overall = FAIL
    elif readability or any(f.verdict == MATCH_FORMATTING for f in fields):
        overall = NEEDS_REVIEW
    else:
        overall = PASS

    return VerificationReport(
        overall=overall,
        summary=_summarize(overall, fields, warning, readability),
        fields=fields, warning=warning, readability_issues=readability)


def _summarize(overall: str, fields: list[FieldResult],
               warning: WarningResult, readability: list[str]) -> str:
    if overall == PASS:
        return "All checks passed. Label matches the application and the government warning is exact."
    issues = [f.name.replace("_", " ") for f in fields if f.verdict in (MISMATCH, MISSING)]
    if warning.verdict == FAIL:
        issues.append("government warning")
    if overall == FAIL:
        return "Problems found with: " + ", ".join(issues) + "."
    soft = [f.name.replace("_", " ") for f in fields if f.verdict == MATCH_FORMATTING]
    parts = []
    if soft:
        parts.append("formatting differs on " + ", ".join(soft))
    if readability:
        parts.append("image quality issues noted")
    return "Please double-check: " + "; ".join(parts) + "."
