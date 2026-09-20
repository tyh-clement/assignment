"""Deterministic input/output guardrails.

These run regardless of what the LLM decides, as a backstop: prompt-injection and
sensitive-data handling are flagged on input; factory-reset confirmation, warranty
overpromising, and "open the device" instructions are enforced on output even if the
model's own compliance slips.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

INJECTION_PATTERNS = [
    r"ignore (all|the|any) (previous|prior|above) instructions",
    r"disregard (the|your) (system|previous) prompt",
    r"you are now",
    r"act as (a|an)\s",
    r"reveal (your|the) (system|hidden) prompt",
    r"print (your|the) instructions",
    r"new instructions?:",
]

SENSITIVE_SHARE_PATTERNS = [
    r"\bpassword\s*(is|:)\s*\S+",
    r"\bwifi password\b.{0,20}\bis\b",
    r"\bapi[_ ]?key\s*(is|:)\s*\S+",
    r"\bsk-[a-zA-Z0-9]{10,}",
    r"\b[a-f0-9]{32,}\b",
]

SENSITIVE_REQUEST_PATTERNS = [
    r"what('s| is) your (wi-?fi )?password",
    r"(share|provide|send|enter) your (api key|password|full serial)",
    r"(can|could) you (give|tell) me your password",
]

FACTORY_RESET_PATTERN = re.compile(r"factory reset", re.IGNORECASE)
CONFIRM_YES_PATTERN = re.compile(r"^\s*(yes|y|confirm|go ahead|proceed|do it)\b", re.IGNORECASE)
CONFIRM_NO_PATTERN = re.compile(r"^\s*(no|n|cancel|stop|don't|do not)\b", re.IGNORECASE)

WARRANTY_PROMISE_PATTERN = re.compile(
    r"\b(is covered|will be covered|is approved|guarantee[d]?|covered under warranty|"
    r"we will replace|replacement is approved)\b",
    re.IGNORECASE,
)

OPEN_DEVICE_PATTERN = re.compile(
    r"(open|unscrew|disassemble|take apart|remove the (case|cover)|internal battery)"
    r".{0,40}(router|node|adapter|unit|device|r1|n1|r5 pro|n5 pro)",
    re.IGNORECASE,
)


@dataclass
class InputFlags:
    injection_detected: bool = False
    sensitive_shared: bool = False
    sanitized_message: str = ""
    notes: List[str] = field(default_factory=list)


def _redact(message: str) -> str:
    redacted = message
    for pattern in SENSITIVE_SHARE_PATTERNS:
        redacted = re.sub(pattern, "[redacted]", redacted, flags=re.IGNORECASE)
    return redacted


def screen_input(message: str) -> InputFlags:
    flags = InputFlags()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            flags.injection_detected = True
            flags.notes.append(f"possible embedded instruction: /{pattern}/")
            break
    shared = any(re.search(p, message, re.IGNORECASE) for p in SENSITIVE_SHARE_PATTERNS)
    flags.sensitive_shared = shared
    flags.sanitized_message = _redact(message) if shared else message
    return flags


def wants_confirmation_yes(message: str) -> bool:
    return bool(CONFIRM_YES_PATTERN.search(message.strip()))


def wants_confirmation_no(message: str) -> bool:
    return bool(CONFIRM_NO_PATTERN.search(message.strip()))


@dataclass
class OutputResult:
    response: str
    action: str
    warnings: List[str] = field(default_factory=list)


def screen_output(response: str, action: str, factory_reset_confirmed: bool) -> OutputResult:
    warnings: List[str] = []
    text = response

    if OPEN_DEVICE_PATTERN.search(text):
        warnings.append("blocked: response instructed opening/disassembling powered hardware")
        text = (
            "I can't have you open or take apart the device — that isn't a customer-serviceable "
            "step. Please contact OrbitMesh Support for further help."
        )
        action = "escalate"

    if action == "instruct" and FACTORY_RESET_PATTERN.search(text) and not factory_reset_confirmed:
        warnings.append("downgraded: factory reset instructed without prior confirmation")
        text = (
            "Before doing that, note a factory reset erases the network name and password, "
            "node pairings, guest networks, parental controls, and all other local configuration — "
            "every node would need to be paired again. Are you sure you want to proceed, and can you "
            "recreate the network and reconnect your devices afterward? Reply \"yes\" to confirm."
        )
        action = "ask"

    for req_pattern in SENSITIVE_REQUEST_PATTERNS:
        if re.search(req_pattern, text, re.IGNORECASE):
            warnings.append(f"blocked: response requested sensitive info matching /{req_pattern}/")
            text = re.sub(req_pattern, "the last four characters of your serial number", text, flags=re.IGNORECASE)

    if WARRANTY_PROMISE_PATTERN.search(text):
        warnings.append("appended: warranty overpromise disclaimer")
        text = (
            text
            + "\n\nNote: I can't confirm warranty coverage in chat — OrbitMesh Support determines "
            "eligibility after verifying purchase details."
        )

    return OutputResult(response=text, action=action, warnings=warnings)
