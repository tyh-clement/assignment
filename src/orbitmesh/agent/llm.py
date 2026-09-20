"""Thin OpenRouter chat client (OpenAI-compatible API), used for the two LLM calls per
turn: planning/slot-extraction and grounded answer generation. Both call sites request
strict JSON output and fall back to a best-effort parse if the model wraps it in prose.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5-mini")

_client: Optional[OpenAI] = None


class LLMError(RuntimeError):
    pass


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        # Strip whitespace and invisible characters (e.g. zero-width space from a
        # copy-paste) that would otherwise break the ASCII-only Authorization header.
        api_key = re.sub(r"[^\x21-\x7e]", "", api_key)
        _client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return _client


def _extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMError(f"Model did not return parseable JSON: {text[:300]!r}")


def call_json(
    system_prompt: str,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    """Call the chat model and parse a single JSON object from its reply."""
    if os.environ.get("ORBITMESH_CI_MODE") == "1":
        return _ci_response(system_prompt, messages)

    client = _get_client()
    model_name = model or DEFAULT_MODEL
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # openai/openrouter errors are exception subclasses of Exception
        raise LLMError(f"OpenRouter call failed: {exc}") from exc

    content = response.choices[0].message.content or ""
    print(f"[llm] model={model_name} tokens={getattr(response, 'usage', None)}", file=sys.stderr)
    return _extract_json(content)


def _customer_message(messages: List[Dict[str, str]]) -> str:
    content = messages[-1].get("content", "") if messages else ""
    match = re.search(r"<customer_message>\s*(.*?)\s*</customer_message>", content, re.DOTALL)
    return match.group(1).strip() if match else content


def _ci_response(system_prompt: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Return deterministic structured responses for offline CI checks."""
    text = _customer_message(messages)
    full_context = messages[-1].get("content", "") if messages else ""
    is_plan = "triage layer" in system_prompt

    if is_plan:
        lower = text.lower()
        product_line = None
        if re.search(r"\b(pro|r5 pro|n5 pro|pro console)\b", lower):
            product_line = "pro"
        elif re.search(r"\b(home|r1|n1)\b", lower):
            product_line = "home"
        if product_line is None:
            known = re.search(r"product_line=(home|pro)", full_context)
            product_line = known.group(1) if known else None

        device_match = re.search(r"\b(R5 Pro|N5 Pro|R1|N1)\b", text, re.IGNORECASE)
        led_match = re.search(r"\b(flashing|solid|pulsing)\s+(amber|red|white|blue)\b", text, re.IGNORECASE)
        error_match = re.search(r"\bE\d{2}\b", text, re.IGNORECASE)
        connection = None
        if re.search(r"ethernet|wired", lower):
            connection = "ethernet"
        elif re.search(r"wireless|wi-fi|wifi", lower):
            connection = "wireless"

        return {
            "slots": {
                "product_line": product_line,
                "device": device_match.group(0) if device_match else None,
                "connection": connection,
                "symptom": text[:200] or None,
                "led_state": led_match.group(0) if led_match else None,
                "error_code": error_match.group(0).upper() if error_match else None,
            },
            "attempted_step": None,
            "reports_resolved": bool(re.search(r"fixed|resolved|working now|staying connected", lower)),
            "confirms_pending_action": (
                "yes" if re.match(r"\s*(yes|y|confirm|go ahead|proceed|do it)\b", lower)
                else "no" if re.match(r"\s*(no|n|cancel|stop)\b", lower)
                else "unclear"
            ),
            "wants_archived_or_history": bool(re.search(r"archive|old firmware|history|retired", lower)),
            "safety_signal": bool(re.search(r"smoke|burnt?|burning|overheat|hot to the touch|visible damage|no light", lower)),
            "missing_info": [] if product_line else ["product_line"],
            "clarifying_question": (
                "Is this the home OrbitMesh system (R1/N1) or the Pro Series (R5 Pro/N5 Pro)?"
                if not product_line else None
            ),
        }

    evidence = re.findall(r"\[([^|]+) \| [^|]+ \| section: ([^|]+) \|", full_context)
    citations = []
    for source_id, locator in evidence:
        citation = {"source_id": source_id.strip(), "locator": locator.strip()}
        if citation not in citations:
            citations.append(citation)
    lower = text.lower()
    if re.search(r"factory reset", lower):
        response = "The documented factory reset procedure requires confirmation before proceeding."
    elif re.search(r"smoke|burnt?|burning|overheat|hot to the touch|visible damage", lower):
        response = "This safety condition requires OrbitMesh Support. Disconnect power and stop troubleshooting."
    elif citations:
        response = f"Use the next documented step for this issue. Supporting evidence: {citations[0]['source_id']} ({citations[0]['locator']})."
    else:
        response = "I need more documented information before giving a product-specific step."
    return {
        "response": response,
        "action": "instruct" if citations else "ask",
        "citations": citations,
        "next_step": "documented step" if citations else None,
        "resolved": False,
        "escalate": False,
    }
