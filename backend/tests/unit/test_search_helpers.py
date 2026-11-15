from app.tools.search import build_tsquery, rrf


def test_rrf_rewards_items_that_rank_well_in_both_lists() -> None:
    merged = rrf([["a", "b", "c"], ["c", "b", "d"]], key=lambda x: x)
    assert merged[:2] == ["c", "b"]  # both appear in each list; a and d only once
    assert set(merged) == {"a", "b", "c", "d"}


def test_rrf_handles_empty_lists() -> None:
    assert rrf([[], []], key=lambda x: x) == []
    assert rrf([["x"], []], key=lambda x: x) == ["x"]


def test_tsquery_keeps_meaningful_words_only() -> None:
    assert build_tsquery("laptop ka price kitna hai") == "'laptop' | 'price'"
    assert build_tsquery("the of a") is None
    assert build_tsquery("") is None


def test_tsquery_cannot_be_injected_into() -> None:
    query = build_tsquery("card' | !secret & (x) <-> y:*")
    assert query == "'card' | 'secret'"  # operators and quotes are stripped; 1-letter words dropped


def test_tsquery_keeps_hindi_and_gujarati_words_whole() -> None:
    assert build_tsquery("विज़िटिंग कार्ड की कीमत") == "'विज़िटिंग' | 'कार्ड' | 'कीमत'"
    assert build_tsquery("વિઝિટિંગ કાર્ડ") == "'વિઝિટિંગ' | 'કાર્ડ'"
