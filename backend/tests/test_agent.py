"""Agent tests. A fake LLM follows a script, so we can test the LangGraph loop without an API key."""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select

from app.agent.graph import run_agent
from app.agent.offline import _inr
from app.database import SessionLocal
from app.models import User


class ScriptedLLM(BaseChatModel):
    """Returns the scripted messages one by one. Records what it was shown."""

    script: list
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def _db_user(email):
    db = SessionLocal()
    return db, db.scalar(select(User).where(User.email == email))


def test_agent_calls_tool_then_answers(client, user_with_portfolio):
    _, user = user_with_portfolio
    db, u = _db_user(user["email"])
    llm = ScriptedLLM(script=[
        AIMessage("", tool_calls=[{"name": "run_sector_scenario", "args": {"sector": "IT", "drop_pct": 15}, "id": "c1"}]),
        AIMessage("If IT falls 15%, you would lose some money."),
    ])
    out = run_agent(db, u, "What if IT falls 15%?", [], llm=llm)
    assert out["tool_calls"] == [{"tool": "run_sector_scenario", "args": {"sector": "IT", "drop_pct": 15}}]
    assert out["answer"] == "If IT falls 15%, you would lose some money."
    # The second LLM call must have received the tool's real result.
    tool_msgs = [m for m in llm.seen[1] if isinstance(m, ToolMessage)]
    assert tool_msgs and "estimated_change_inr" in tool_msgs[0].content
    db.close()


def test_agent_tool_error_is_passed_back_not_crashed(client, user_with_portfolio):
    _, user = user_with_portfolio
    db, u = _db_user(user["email"])
    llm = ScriptedLLM(script=[
        AIMessage("", tool_calls=[{"name": "run_sector_scenario", "args": {"sector": "Shipping", "drop_pct": 10}, "id": "c1"}]),
        AIMessage("You don't hold shipping stocks."),
    ])
    out = run_agent(db, u, "What if shipping falls 10%?", [], llm=llm)
    tool_msgs = [m for m in llm.seen[1] if isinstance(m, ToolMessage)]
    assert "don't hold any" in tool_msgs[0].content
    assert out["answer"] == "You don't hold shipping stocks."
    db.close()


def test_offline_agent_intents(client, user_with_portfolio):
    _, user = user_with_portfolio
    db, u = _db_user(user["email"])
    cases = {
        "How risky is my portfolio?": "get_risk_metrics",
        "What if the market falls 10%?": "run_market_scenario",
        "Replay the covid crash": "run_historical_scenario",
        "What if banks drop 20%?": "run_sector_scenario",
        "Which stocks move together?": "get_correlated_pairs",
        "Tell me about INFY": "get_stock_details",
        "What if INFY falls 30%": "run_custom_scenario",
    }
    for q, tool in cases.items():
        out = run_agent(db, u, q, [])
        assert tool in [c["tool"] for c in out["tool_calls"]], q
    db.close()


def test_indian_number_format():
    assert _inr(1234567) == "₹12,34,567"
    assert _inr(999) == "₹999"
    assert _inr(-100000) == "-₹1,00,000"
