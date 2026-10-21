"""The evaluation's number checks (they decide the scores, so they need tests too)."""
from eval.agent_eval import amounts_in, answer_has, percents_in, ungrounded_numbers


def test_amounts_in_understands_indian_formats():
    assert amounts_in("lose ₹1,23,456 or Rs 1.2 lakh, maybe ₹3 crore") == [123456, 120000, 30000000]
    assert percents_in("down -7.2% vs 15 %") == [7.2, 15]


def test_answer_has_with_rounding():
    assert answer_has("about ₹1.3 lakh", 129_921, "inr")
    assert answer_has("roughly 7%", 7.2, "pct")
    assert not answer_has("roughly 9%", 7.2, "pct")
    assert answer_has("9 breaches", 9, "count")


def test_ungrounded_numbers_flags_invented_values():
    tools = ['{"estimated_change_inr": -48219, "estimated_change_pct": -7.4}']
    assert ungrounded_numbers("You'd lose ₹48,219 (7.4%).", tools, "What if IT falls 15%?") == []
    # 15% comes from the question, so it's allowed; ₹99,999 and 3.3% are not in any tool result.
    assert ungrounded_numbers("If IT falls 15% you lose ₹99,999, about 3.3%.", tools, "What if IT falls 15%?") == ["₹99,999", "3.3%"]
