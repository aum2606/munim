from app.core.leads import lead_score


def test_score_formula_and_bounded_signal():
    assert lead_score(False, False, False, False, 0) == 0
    assert lead_score(True, True, True, True, 20) == 100
    assert lead_score(False, False, False, False, -20) == 0
    assert lead_score(True, False, False, True, 999) == 60
    assert lead_score(True, True, True, True, -999) == 80
