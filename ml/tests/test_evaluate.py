import pytest

from triage_ml.evaluate import LOSE, TINY_HOLDOUT, WIN, decide

CHAMP = {"golden_macro_f1": 0.70, "feedback_macro_f1": 0.40}


@pytest.mark.parametrize(
    ("challenger", "rows", "code"),
    [
        ({"golden_macro_f1": 0.69, "feedback_macro_f1": 0.60}, 30, WIN),
        ({"golden_macro_f1": 0.67, "feedback_macro_f1": 0.60}, 30, LOSE),  # golden regression
        ({"golden_macro_f1": 0.75, "feedback_macro_f1": 0.40}, 30, LOSE),  # no feedback gain
        ({"golden_macro_f1": 0.75, "feedback_macro_f1": 0.90}, 19, TINY_HOLDOUT),
    ],
)
def test_decide(challenger, rows, code):
    assert decide(CHAMP, challenger, rows)[0] == code
