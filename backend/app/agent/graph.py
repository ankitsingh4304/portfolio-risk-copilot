r"""The AI agent, built as a LangGraph graph.

    START -> agent --(wants a tool?)--> tools -> agent -> ... -> END
                   \--(no tool needed)---------------------> END

The "agent" node asks the LLM what to do next. If the LLM asks for a tool, the
"tools" node runs it and sends the result back. This loop repeats until the LLM
has enough information to answer. MAX_STEPS stops it from looping forever.
"""
import logging
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User
from . import offline
from .tools import ToolContext, build_tools

log = logging.getLogger(__name__)
settings = get_settings()
MAX_STEPS = 12  # graph steps; each tool round-trip uses 2

SYSTEM_PROMPT = """You are Portfolio Risk Copilot, a helpful assistant for an Indian retail investor.
Today is {today}.

Rules:
1. Get every number from a tool. Never calculate, estimate or invent numbers yourself.
   If no tool gives the number, say you don't have it.
2. Use simple words and short sentences. The user may be new to investing.
   The first time you use a finance term (volatility, drawdown, beta, VaR...), explain it in a few words.
3. Write money as rupees with Indian commas, like ₹1,25,000. Round percentages to one decimal.
4. Scenario results are estimates based on past prices, not predictions. Say so briefly.
5. Don't tell the user to buy or sell a specific stock. You can explain risks and general
   ideas such as diversification.
6. Keep answers short (under about 150 words) unless the user asks for detail.
"""


def build_graph(llm, tools):
    llm_with_tools = llm.bind_tools(tools)
    system = SystemMessage(SYSTEM_PROMPT.format(today=date.today().isoformat()))

    def agent(state: MessagesState):
        return {"messages": [llm_with_tools.invoke([system, *state["messages"]])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)  # goes to "tools" or ends
    graph.add_edge("tools", "agent")
    return graph.compile()


def _make_llm(provider: str):
    """Build one AI model, or None if its key isn't set."""
    if provider == "gemini" and settings.google_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI

        # Gemini 3 and newer use Google's fixed sampling settings and can reject a custom
        # temperature, so only older models get one.
        extra = {} if settings.gemini_model.startswith("gemini-3") else {"temperature": 0.2}
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model, google_api_key=settings.google_api_key, max_retries=2, **extra
        )
    if provider == "groq" and settings.groq_api_key:
        from langchain_groq import ChatGroq

        return ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key, temperature=0.2, max_retries=2)
    return None


def ai_order() -> list[str]:
    """Names of the AI models to try, in order: the main one (LLM_PROVIDER), then the other as backup.

    Example: LLM_PROVIDER=gemini with both keys set -> ["gemini", "groq"].
    LLM_PROVIDER=offline -> [] (no AI at all, even if keys are set).
    """
    order = {"gemini": ["gemini", "groq"], "groq": ["groq", "gemini"]}.get(settings.llm_provider, [])
    keys = {"gemini": settings.google_api_key, "groq": settings.groq_api_key}
    return [name for name in order if keys[name]]


def get_llms() -> list[tuple[str, object]]:
    """The AI models to try, in order, as (name, model) pairs."""
    return [(name, _make_llm(name)) for name in ai_order()]


def get_llm():
    """The first available model (used by the PDF reader)."""
    llms = get_llms()
    return llms[0][1] if llms else None


def _text(msg) -> str:
    """Get plain text from a message. Gemini can return content as a list of parts."""
    c = msg.content
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)


def run_agent(db: Session, user: User, message: str, history: list[dict], llm=None, models=None) -> dict:
    """Answer one chat message.

    Tries each AI model in order (main, then backup). If all of them fail, falls back to
    the rule-based answer. Tests pass a fake `llm`, or a list of (name, model) as `models`.
    """
    ctx = ToolContext(db, user)
    tools = build_tools(ctx)
    if models is None:
        models = [("llm", llm)] if llm is not None else get_llms()
    if not models:
        return offline.answer(message, tools)

    msgs = []
    for m in history[-10:]:
        msgs.append(HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]))
    msgs.append(HumanMessage(message))

    result = None
    for name, model in models:
        try:
            result = build_graph(model, tools).invoke({"messages": msgs}, config={"recursion_limit": MAX_STEPS})
            break
        except Exception as exc:  # noqa: BLE001  API down, quota hit, model retired, too many steps...
            log.warning("AI model '%s' failed: %s", name, exc)
    if result is None:
        log.warning("All AI models failed, using offline mode.")
        out = offline.answer(message, tools)
        out["answer"] = "(The AI model is unavailable right now, so here's a basic answer.)\n\n" + out["answer"]
        return out

    new_msgs = result["messages"][len(msgs):]
    tool_calls = [
        {"tool": tc["name"], "args": tc.get("args", {})}
        for m in new_msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])
    ]
    final = next((m for m in reversed(new_msgs) if isinstance(m, AIMessage)), None)
    answer = _text(final).strip() if final else ""
    # Token use across every LLM call in this answer (for cost tracking in the evaluation).
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in new_msgs:
        meta = getattr(m, "usage_metadata", None) or {}
        usage["input_tokens"] += meta.get("input_tokens", 0) or 0
        usage["output_tokens"] += meta.get("output_tokens", 0) or 0
    return {
        "answer": answer or "Sorry, I couldn't put together an answer.",
        "tool_calls": tool_calls,
        "tool_results": [_text(m) for m in new_msgs if isinstance(m, ToolMessage)],
        "usage": usage,
        "mode": name,  # which model answered: "gemini", "groq" (or "llm" in tests)
    }
