"""Unit tests for the deterministic compliance rules."""

from app import verification as v


# --- text fields ------------------------------------------------------------

def test_exact_brand_match():
    r = v.compare_text_field("brand_name", "OLD TOM DISTILLERY", "OLD TOM DISTILLERY")
    assert r.verdict == v.MATCH and not r.note


def test_case_only_difference_is_match_with_note():
    # Dave's example: obviously the same brand.
    r = v.compare_text_field("brand_name", "STONE'S THROW", "Stone's Throw")
    assert r.verdict == v.MATCH
    assert "capitalization" in r.note.lower()


def test_punctuation_difference_needs_a_glance():
    r = v.compare_text_field("brand_name", "Stones Throw", "Stone's Throw")
    assert r.verdict == v.MATCH_FORMATTING


def test_real_mismatch_fails():
    r = v.compare_text_field("brand_name", "OLD TOM", "OLD THOMAS")
    assert r.verdict == v.MISMATCH


def test_empty_application_value_skips_check():
    r = v.compare_text_field("brand_name", "OLD TOM", "")
    assert r.verdict == v.NOT_CHECKED


def test_missing_label_value():
    r = v.compare_text_field("brand_name", None, "OLD TOM")
    assert r.verdict == v.MISSING


def test_smart_quotes_normalized():
    r = v.compare_text_field("brand_name", "Stone’s Throw", "Stone's Throw")
    assert r.verdict == v.MATCH


# --- alcohol content --------------------------------------------------------

def test_abv_numeric_equivalence():
    r = v.compare_alcohol_content("45% Alc./Vol. (90 Proof)", "45.0 % alc/vol")
    assert r.verdict == v.MATCH


def test_abv_mismatch():
    r = v.compare_alcohol_content("40% Alc./Vol.", "45% Alc./Vol.")
    assert r.verdict == v.MISMATCH


def test_proof_cross_check_catches_internal_inconsistency():
    r = v.compare_alcohol_content("45% Alc./Vol. (80 Proof)", "45%")
    assert r.verdict == v.MISMATCH
    assert "proof" in r.note.lower()


# --- net contents -----------------------------------------------------------

def test_net_contents_unit_normalization():
    assert v.compare_net_contents("750 mL", "750ml").verdict == v.MATCH
    assert v.compare_net_contents("0.75 L", "750 mL").verdict == v.MATCH


def test_net_contents_mismatch():
    assert v.compare_net_contents("700 mL", "750 mL").verdict == v.MISMATCH


# --- government warning -----------------------------------------------------

CORRECT_WARNING = v.WARNING_PREFIX + " " + v.WARNING_BODY


def test_exact_warning_passes():
    w = v.check_government_warning(CORRECT_WARNING)
    assert w.verdict == v.PASS and w.prefix_all_caps and w.wording_exact


def test_title_case_prefix_fails():
    # Jenny's real rejection: correct words, wrong capitalization.
    w = v.check_government_warning("Government Warning: " + v.WARNING_BODY)
    assert w.verdict == v.FAIL
    assert w.wording_exact and not w.prefix_all_caps


def test_reworded_warning_fails_with_diff():
    tampered = CORRECT_WARNING.replace("birth defects", "health issues")
    w = v.check_government_warning(tampered)
    assert w.verdict == v.FAIL
    assert any("birth defects" in p for p in w.problems)


def test_missing_warning_fails():
    w = v.check_government_warning(None)
    assert w.verdict == v.FAIL and not w.present


def test_whitespace_and_linebreaks_tolerated():
    wrapped = CORRECT_WARNING.replace(". (2)", ".\n(2)").replace("drink", " drink ")
    w = v.check_government_warning(wrapped)
    assert w.verdict == v.PASS


# --- report assembly --------------------------------------------------------

EXTRACTED_OK = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "government_warning_verbatim": CORRECT_WARNING,
    "readability_issues": [],
    "confidence": "high",
}

APPLICATION_OK = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol.",
    "net_contents": "750 mL",
}


def test_clean_label_passes_overall():
    report = v.build_report(EXTRACTED_OK, APPLICATION_OK)
    assert report.overall == v.PASS


def test_bad_warning_fails_overall():
    extracted = dict(EXTRACTED_OK, government_warning_verbatim="Government Warning: be careful")
    report = v.build_report(extracted, APPLICATION_OK)
    assert report.overall == v.FAIL


def test_readability_issues_force_review():
    extracted = dict(EXTRACTED_OK, readability_issues=["glare across warning text"])
    report = v.build_report(extracted, APPLICATION_OK)
    assert report.overall == v.NEEDS_REVIEW


def test_extraction_only_checks_warning():
    report = v.build_report(EXTRACTED_OK, {})
    assert report.overall == v.PASS
    assert all(f.verdict == v.NOT_CHECKED for f in report.fields)
