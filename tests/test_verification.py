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


def test_producer_containment_matches():
    # Labels wrap the address in phrases like "DISTILLED AND BOTTLED BY".
    r = v.compare_containment_field(
        "producer_name_address",
        "DISTILLED AND BOTTLED BY OLD TOM DISTILLING CO., BARDSTOWN, KY",
        "Old Tom Distilling Co., Bardstown, KY")
    assert r.verdict == v.MATCH


def test_producer_real_mismatch_fails():
    r = v.compare_containment_field(
        "producer_name_address",
        "BOTTLED BY ACME SPIRITS, DENVER, CO",
        "Old Tom Distilling Co., Bardstown, KY")
    assert r.verdict == v.MISMATCH


def test_country_of_origin_containment():
    r = v.compare_containment_field(
        "country_of_origin", "PRODUCT OF FRANCE", "France")
    assert r.verdict == v.MATCH


def test_country_of_origin_skipped_for_domestic():
    # Domestic products: application leaves the field empty.
    r = v.compare_containment_field("country_of_origin", None, "")
    assert r.verdict == v.NOT_CHECKED


def test_country_of_origin_missing_on_import():
    r = v.compare_containment_field("country_of_origin", None, "France")
    assert r.verdict == v.MISSING


def test_unbold_warning_prefix_needs_review_not_fail():
    correct = f"{v.WARNING_PREFIX} {v.WARNING_BODY}"
    report = v.build_report(
        {"government_warning_verbatim": correct, "warning_appears_bold": False},
        {})
    assert report.warning.verdict == v.PASS          # wording/caps are right
    assert report.overall == v.NEEDS_REVIEW          # but bold needs a glance
    assert any("bold" in p for p in report.warning.problems)


def test_tiny_warning_needs_review_not_fail():
    # Jenny: "people try to get creative... smaller font, burying it in tiny text."
    correct = f"{v.WARNING_PREFIX} {v.WARNING_BODY}"
    report = v.build_report(
        {"government_warning_verbatim": correct, "warning_appears_conspicuous": False},
        {})
    assert report.warning.verdict == v.PASS
    assert report.overall == v.NEEDS_REVIEW
    assert any("small" in p for p in report.warning.problems)


def test_unknown_conspicuousness_does_not_flag():
    correct = f"{v.WARNING_PREFIX} {v.WARNING_BODY}"
    report = v.build_report(
        {"government_warning_verbatim": correct, "warning_appears_conspicuous": None},
        {})
    assert report.overall == v.PASS


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
