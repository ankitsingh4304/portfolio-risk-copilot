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


class BrokenLLM(ScriptedLLM):
    """Always fails, like a retired model or an exhausted free quota."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("404 model not found")


def test_backup_model_answers_when_main_fails(client, user_with_portfolio):
    _, user = user_with_portfolio
    db, u = _db_user(user["email"])
    backup = ScriptedLLM(script=[
        AIMessage("", tool_calls=[{"name": "get_risk_metrics", "args": {}, "id": "c1"}]),
        AIMessage("Your portfolio is moderately risky."),
    ])
    out = run_agent(db, u, "How risky am I?", [], models=[("gemini", BrokenLLM(script=[])), ("groq", backup)])
    assert out["mode"] == "groq"
    assert out["answer"] == "Your portfolio is moderately risky."
    assert [c["tool"] for c in out["tool_calls"]] == ["get_risk_metrics"]
    db.close()


def test_basic_mode_only_when_every_model_fails(client, user_with_portfolio):
    _, user = user_with_portfolio
    db, u = _db_user(user["email"])
    out = run_agent(db, u, "How risky is my portfolio?", [],
                    models=[("gemini", BrokenLLM(script=[])), ("groq", BrokenLLM(script=[]))])
    assert out["mode"] == "offline"
    assert out["answer"].startswith("(The AI model is unavailable right now")
    db.close()


def test_model_order_follows_llm_provider(monkeypatch):
    from app.agent import graph
    from app.config import Settings

    both = {"google_api_key": "g", "groq_api_key": "q"}
    for provider, expected in [("gemini", ["gemini", "groq"]), ("groq", ["groq", "gemini"]), ("offline", [])]:
        monkeypatch.setattr(graph, "settings", Settings(llm_provider=provider, **both))
        assert graph.ai_order() == expected
    # A model without a key is skipped. (Set the empty key explicitly, or Settings would
    # read the real GOOGLE_API_KEY from your .env file.)
    monkeypatch.setattr(graph, "settings", Settings(llm_provider="gemini", google_api_key="", groq_api_key="q"))
    assert graph.ai_order() == ["groq"]
