from triage_ml.text import build_text


def test_no_subject_collapses_spaces():
    assert build_text(None, " a  b ") == "a b"


def test_subject_joined_with_blank_line():
    assert build_text("Hi", "body") == "Hi\n\nbody"


def test_nan_subject_like_none():
    assert build_text(float("nan"), "body") == "body"


def test_tabs_collapsed():
    assert build_text("a\t\tb", "c \t d") == "a b\n\nc d"
