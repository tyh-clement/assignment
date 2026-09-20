"""LangGraph conversation graph: one run per customer turn.

Flow:
  guard_input -> plan -> [ask | retrieve -> answer] -> guard_output -> persist -> END

`plan` decides whether enough information is known to retrieve product-specific evidence;
if not, the turn ends with a single focused clarifying question and no retrieval/LLM
answer call is spent. Otherwise evidence is retrieved with product-line/status filters and
a grounded, cited answer is generated. Deterministic guardrails run last, after the model,
as a backstop that cannot be prompted away.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from . import guardrails, prompts
from .llm import LLMError, call_json
from ..ingestion.retrieval import Evidence, retrieve
from .session import Session, Slots, load_session, save_session


def log(*args: object) -> None:
    print(*args, file=sys.stderr)


class TurnState(TypedDict, total=False):
    session: Session
    user_message: str
    input_flags: guardrails.InputFlags
    plan: Dict[str, Any]
    evidence: List[Evidence]
    result: Dict[str, Any]


def node_guard_input(state: TurnState) -> TurnState:
    flags = guardrails.screen_input(state["user_message"])
    if flags.injection_detected:
        log("[guardrail] possible prompt injection detected in customer message")
    if flags.sensitive_shared:
        log("[guardrail] customer message appears to contain a shared secret; redacting from history")
    return {"input_flags": flags}


def _merge_slots(session: Session, plan_slots: Dict[str, Optional[str]]) -> None:
    for field_name, value in (plan_slots or {}).items():
        if value and hasattr(session.slots, field_name):
            setattr(session.slots, field_name, value)


def node_plan(state: TurnState) -> TurnState:
    session = state["session"]
    flags = state["input_flags"]
    history = [{"role": t["role"], "content": t["content"]} for t in session.turns[-8:]]
    user_content = (
        f"Known case state so far:\n{prompts.format_session_context(session)}\n\n"
        f"<customer_message>\n{flags.sanitized_message}\n</customer_message>"
    )
    try:
        plan = call_json(
            prompts.PLAN_SYSTEM_PROMPT,
            [*history, {"role": "user", "content": user_content}],
        )
    except LLMError as exc:
        log(f"[plan] LLM error: {exc}")
        plan = {
            "slots": {},
            "attempted_step": None,
            "reports_resolved": False,
            "confirms_pending_action": "unclear",
            "wants_archived_or_history": False,
            "safety_signal": False,
            "missing_info": ["product_line"],
            "clarifying_question": (
                "I'm having trouble reaching the assistant backend. Could you tell me whether "
                "this is a home OrbitMesh system (R1/N1) or a Pro Series system (R5 Pro/N5 Pro)?"
            ),
        }

    _merge_slots(session, plan.get("slots", {}))
    if plan.get("attempted_step"):
        session.attempted_steps.append(plan["attempted_step"])
    if plan.get("reports_resolved"):
        session.resolved = True
    return {"plan": plan}


def route_after_plan(state: TurnState) -> str:
    session = state["session"]
    plan = state["plan"]

    if session.pending_confirmation:
        return "confirmation"
    if plan.get("safety_signal"):
        return "retrieve"
    if session.resolved:
        return "resolved"
    if plan.get("missing_info"):
        return "ask"
    return "retrieve"


def node_ask(state: TurnState) -> TurnState:
    plan = state["plan"]
    question = plan.get("clarifying_question") or "Could you tell me more about what's happening?"
    return {"result": {"response": question, "action": "ask", "citations": []}}


def node_resolved(state: TurnState) -> TurnState:
    return {
        "result": {
            "response": "Glad that's resolved! Let me know if anything else comes up with your OrbitMesh system.",
            "action": "resolved",
            "citations": [],
        }
    }


def node_confirmation(state: TurnState) -> TurnState:
    session = state["session"]
    message = state["user_message"]
    plan = state["plan"]
    confirmed = plan.get("confirms_pending_action", "unclear")
    if confirmed == "unclear":
        confirmed = "yes" if guardrails.wants_confirmation_yes(message) else (
            "no" if guardrails.wants_confirmation_no(message) else "unclear"
        )

    if confirmed == "no":
        pending = session.pending_confirmation
        session.pending_confirmation = None
        return {
            "result": {
                "response": (
                    f"Understood, I won't proceed with {pending}. Let me know if you'd like to "
                    "try something else, or if you'd like help with an alternative step."
                ),
                "action": "ask",
                "citations": [],
            }
        }
    if confirmed == "yes":
        # Fall through to retrieval/answer. Normalize the resolved value back into the plan
        # dict (it may have come from the heuristic fallback above, not the LLM) so
        # guard_output's confirmation check sees the same "yes" this node just acted on.
        return {"plan": {**plan, "confirms_pending_action": "yes"}}
    return {
        "result": {
            "response": (
                f"Just to confirm: do you want to proceed with {session.pending_confirmation}? "
                "Please reply \"yes\" or \"no\"."
            ),
            "action": "ask",
            "citations": [],
        }
    }


def route_after_confirmation(state: TurnState) -> str:
    if "result" in state:
        return "end"
    return "retrieve"


def node_retrieve(state: TurnState) -> TurnState:
    session = state["session"]
    plan = state["plan"]
    slots = session.slots
    query_parts = [
        slots.symptom or "",
        slots.device or "",
        slots.led_state or "",
        slots.error_code or "",
        slots.connection or "",
        state["user_message"],
    ]
    query = " ".join(p for p in query_parts if p).strip() or state["user_message"]
    evidence = retrieve(
        query,
        product_line=slots.product_line,
        include_archived=bool(plan.get("wants_archived_or_history")),
        k=5,
    )
    return {"evidence": evidence}


def node_answer(state: TurnState) -> TurnState:
    session = state["session"]
    flags = state["input_flags"]
    evidence = state.get("evidence", [])
    history = [{"role": t["role"], "content": t["content"]} for t in session.turns[-8:]]
    user_content = (
        f"Known case state:\n{prompts.format_session_context(session)}\n\n"
        f"<evidence>\n{prompts.format_evidence(evidence)}\n</evidence>\n\n"
        f"<customer_message>\n{flags.sanitized_message}\n</customer_message>"
    )
    try:
        answer = call_json(
            prompts.ANSWER_SYSTEM_PROMPT,
            [*history, {"role": "user", "content": user_content}],
        )
    except LLMError as exc:
        log(f"[answer] LLM error: {exc}")
        answer = {
            "response": (
                "I'm having trouble reaching the assistant backend right now. Please try again "
                "shortly, or use the support channel in the OrbitMesh app."
            ),
            "action": "escalate",
            "citations": [],
            "resolved": False,
            "escalate": True,
        }

    if answer.get("resolved"):
        session.resolved = True
    if answer.get("escalate"):
        session.escalated = True

    return {
        "result": {
            "response": answer.get("response", ""),
            "action": answer.get("action", "instruct"),
            "citations": answer.get("citations", []),
        }
    }


def node_guard_output(state: TurnState) -> TurnState:
    session = state["session"]
    result = state["result"]
    plan = state.get("plan", {})
    confirmed = session.pending_confirmation is not None and (
        plan.get("confirms_pending_action") == "yes"
    )

    if plan.get("safety_signal") and result["action"] != "escalate":
        # Backstop: a reported safety condition (heat/smoke/damage) must escalate
        # regardless of what the model decided, per the documented stop conditions.
        log("[guardrail:output] safety_signal set but model did not escalate; forcing escalate")
        result["action"] = "escalate"
        result["response"] = (
            result["response"].rstrip()
            + "\n\nBecause this may be a safety issue (heat, smoke, or damage), please disconnect "
            "the unit from power now and contact OrbitMesh Support instead of continuing "
            "troubleshooting steps."
        )

    screened = guardrails.screen_output(result["response"], result["action"], confirmed)
    for warning in screened.warnings:
        log(f"[guardrail:output] {warning}")

    if screened.action == "ask" and "factory reset" in screened.response.lower() and not confirmed:
        session.pending_confirmation = "the factory reset"
    elif confirmed:
        session.pending_confirmation = None

    result["response"] = screened.response
    result["action"] = screened.action
    return {"result": result}


def node_persist(state: TurnState) -> TurnState:
    session = state["session"]
    flags = state["input_flags"]
    session.turns.append({"role": "user", "content": flags.sanitized_message})
    session.turns.append({"role": "assistant", "content": state["result"]["response"]})
    save_session(session)
    return {}


def build_graph():
    graph = StateGraph(TurnState)
    graph.add_node("guard_input", node_guard_input)
    graph.add_node("plan", node_plan)
    graph.add_node("ask", node_ask)
    graph.add_node("resolved", node_resolved)
    graph.add_node("confirmation", node_confirmation)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("answer", node_answer)
    graph.add_node("guard_output", node_guard_output)
    graph.add_node("persist", node_persist)

    graph.set_entry_point("guard_input")
    graph.add_edge("guard_input", "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"ask": "ask", "resolved": "resolved", "retrieve": "retrieve", "confirmation": "confirmation"},
    )
    graph.add_conditional_edges(
        "confirmation", route_after_confirmation, {"end": "guard_output", "retrieve": "retrieve"}
    )
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "guard_output")
    graph.add_edge("ask", "guard_output")
    graph.add_edge("resolved", "guard_output")
    graph.add_edge("guard_output", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


_compiled = None


def run_turn(session_id: str, user_message: str) -> Dict[str, Any]:
    """Run one conversation turn end-to-end and return the contract-shaped result dict."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()

    session = load_session(session_id)
    final_state = _compiled.invoke({"session": session, "user_message": user_message})
    result = final_state["result"]
    return {
        "response": result["response"],
        "citations": result.get("citations", []),
        "action": result.get("action", "instruct"),
    }
