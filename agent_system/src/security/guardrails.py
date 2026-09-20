"""Security guardrails: PII sanitization and prompt injection prevention.

Executes before Step 2 (Intent Classification) to prevent sensitive patient PII
leakage to LLM providers and block direct/indirect prompt injection attempts.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

# Compiled regex patterns for patient identifiers
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MRN_PATTERN = re.compile(r"\bMRN[A-Z0-9]{4,10}\b", re.IGNORECASE)

INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts?|rules|directives)", re.IGNORECASE), "Instruction override attempt"),
    (re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:prompts?|instructions|rules|directives)", re.IGNORECASE), "Instruction override attempt"),
    (re.compile(r"(?:system\s+override|override\s+system(?:\s+(?:prompt|directive|policy|rules))?)", re.IGNORECASE), "System override attempt"),
    (re.compile(r"you\s+are\s+now\s+(?:in\s+)?(?:developer\s+mode|dan\s+mode|unrestricted)", re.IGNORECASE), "Jailbreak persona hijack"),
    (re.compile(r"(?:---|<\|im_start\|>|<\|system\|>|```(?:system|assistant))", re.IGNORECASE), "Delimiter injection attack"),
    (re.compile(r"bypass\s+.*(?:24-?hour|cancellation|reschedule|clinic)\s+policy", re.IGNORECASE), "Policy bypass manipulation"),
    (re.compile(r"(?:eval\(|exec\(|__import__|os\.system|subprocess\.)", re.IGNORECASE), "Code execution injection"),
    (re.compile(r"(?:output|print|reveal|show|give|leak)\s+(?:the\s+)?(?:system|admin|database)?\s*(?:password|secret|key|prompt|creds)", re.IGNORECASE), "Credential exfiltration attempt"),
]


class InjectionCheckResult(BaseModel):
    """Result of prompt injection evaluation."""
    is_safe: bool = Field(..., description="True if input is free of dangerous injection patterns")
    risk_score: float = Field(default=0.0, description="Heuristic threat risk score between 0.0 and 1.0")
    flagged_patterns: List[str] = Field(default_factory=list, description="List of matched threat patterns")
    reason: Optional[str] = Field(default=None, description="Human-readable explanation if rejected")


class SecurityResult(BaseModel):
    """Comprehensive output of security guardrails pipeline."""
    is_safe: bool
    sanitized_text: str
    original_text: str
    pii_token_map: Dict[str, str] = Field(default_factory=dict)
    injection_result: InjectionCheckResult


def sanitize_pii(text: str) -> Tuple[str, Dict[str, str]]:
    """Replaces sensitive PII with synthetic tokens, returning sanitized text and mapping."""
    token_map: Dict[str, str] = {}
    sanitized = text

    for idx, match in enumerate(SSN_PATTERN.findall(sanitized), start=1):
        placeholder = f"<PII_SSN_{idx}>"
        token_map[placeholder] = match
        sanitized = sanitized.replace(match, placeholder)

    for idx, match in enumerate(EMAIL_PATTERN.findall(sanitized), start=1):
        placeholder = f"<PII_EMAIL_{idx}>"
        token_map[placeholder] = match
        sanitized = sanitized.replace(match, placeholder)

    for idx, match in enumerate(PHONE_PATTERN.findall(sanitized), start=1):
        if "<PII_" not in match:
            placeholder = f"<PII_PHONE_{idx}>"
            token_map[placeholder] = match
            sanitized = sanitized.replace(match, placeholder)

    for idx, match in enumerate(MRN_PATTERN.findall(sanitized), start=1):
        placeholder = f"<PII_MRN_{idx}>"
        token_map[placeholder] = match
        sanitized = sanitized.replace(match, placeholder)

    return sanitized, token_map


def deanonymize_pii(text: str, token_map: Dict[str, str]) -> str:
    """Restores synthetic tokens back to original values."""
    restored = text
    for placeholder, original in token_map.items():
        restored = restored.replace(placeholder, original)
    return restored


def check_prompt_injection(text: str) -> InjectionCheckResult:
    """Evaluates input text for jailbreak and system override signals."""
    matched = [desc for pat, desc in INJECTION_PATTERNS if pat.search(text)]
    if matched:
        risk = min(1.0, 0.4 + 0.3 * len(matched))
        return InjectionCheckResult(
            is_safe=False,
            risk_score=risk,
            flagged_patterns=matched,
            reason=f"Input blocked due to potential prompt injection / policy circumvention: {', '.join(set(matched))}",
        )
    return InjectionCheckResult(is_safe=True, risk_score=0.0, flagged_patterns=[], reason=None)


def process_security_guardrails(raw_input: str) -> SecurityResult:
    """Unified entrypoint running injection check then scrubbing PII."""
    inj = check_prompt_injection(raw_input)
    sanitized, pii_map = sanitize_pii(raw_input)
    return SecurityResult(
        is_safe=inj.is_safe,
        sanitized_text=sanitized,
        original_text=raw_input,
        pii_token_map=pii_map,
        injection_result=inj,
    )


# Backward-compatible facades for tests and existing callers
class PIISanitizer:
    @classmethod
    def sanitize(cls, text: str) -> Tuple[str, Dict[str, str]]:
        return sanitize_pii(text)

    @classmethod
    def deanonymize(cls, text: str, token_map: Dict[str, str]) -> str:
        return deanonymize_pii(text, token_map)


class InjectionGuard:
    @classmethod
    def check(cls, text: str) -> InjectionCheckResult:
        return check_prompt_injection(text)


class SecurityGuardrails:
    @classmethod
    def process_input(cls, raw_input: str) -> SecurityResult:
        return process_security_guardrails(raw_input)
