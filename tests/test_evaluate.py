import pytest

from orbit.agent.eval_cases import EVAL_CASES
from orbit.agent.evaluate import extract_numbers, gold_values, score_answer

NUMBER_CASE = {"kind": "number", "tolerance": 0}
ALTITUDE_CASE = {"kind": "number", "tolerance": 1}
TEXT_CASE = {"kind": "text"}
DECLINE_CASE = {"kind": "decline"}


def test_extract_numbers_handles_commas_and_decimals():
    assert extract_numbers("There are 11,133 satellites at 626.78 km.") == [11133, 626.78]


@pytest.mark.parametrize("case, answer, gold, expected", [
    (NUMBER_CASE, "There are 11,133 Starlink satellites.", [11133], True),
    (NUMBER_CASE, "There are 11,000 Starlink satellites.", [11133], False),
    (NUMBER_CASE, "I couldn't find that.", [11133], False),
    (ALTITUDE_CASE, "The average is about 627 km.", [626.78], True),     # rounded, within tolerance
    (ALTITUDE_CASE, "The average is about 630 km.", [626.78], False),
    (TEXT_CASE, "Launch 2025-088 has the most.", ["2025-088"], True),
    (TEXT_CASE, "It's kuiper-00028.", ["KUIPER-00028"], True),           # case-insensitive
    (TEXT_CASE, "Launch 2025-099 has the most.", ["2025-088", "2026-001"], False),
    (TEXT_CASE, "Launch 2026-001 has the most.", ["2025-088", "2026-001"], True),   # ties all count
    (DECLINE_CASE, "The database has no OneWeb data.", [], True),
    (DECLINE_CASE, "OneWeb has 648 satellites.", [], False),
])
def test_score_answer(case, answer, gold, expected):
    assert score_answer(case, answer, gold) is expected


@pytest.mark.parametrize("case", [NUMBER_CASE, TEXT_CASE, DECLINE_CASE])
def test_giving_up_never_scores_as_correct(case):
    answer = "Stopped: too many tool calls without an answer."
    assert score_answer(case, answer, [1]) is False


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        score_answer({"kind": "typo"}, "anything", [])


def test_case_ids_are_unique():
    ids = [case["id"] for case in EVAL_CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["id"])
def test_every_gold_query_runs(sandbox, case):
    # a broken gold query would make the agent look wrong, so catch it here
    gold = gold_values(sandbox, case)
    if case["kind"] == "decline":
        assert gold == []
    else:
        assert isinstance(gold, list)
