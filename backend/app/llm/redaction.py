"""Data minimisation for LLM prompts (spec §15.2): mask SSNs, DOBs, contact data and (optionally) names."""
from __future__ import annotations

import re

from app.config import settings
from app.core.logging import redact_text

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_DOB = re.compile(r"(?i)\b(DOB|Date of Birth)(\s*[:#]?\s*)\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")
_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SSN_LAST4 = re.compile(r"(?i)\b(SSN|Social Security)[^\n]{0,20}?(\d{4})\b")


def minimize(text: str, claimant_names: list[str] | None = None) -> str:
    """Always mask SSN/DOB/phone/email.  Mask claimant names unless ALLOW_PHI_TO_LLM is true."""
    text = _SSN.sub("[SSN]", text)
    text = _SSN_LAST4.sub(lambda m: f"{m.group(1)} [SSN]", text)
    text = _DOB.sub(lambda m: f"{m.group(1)}{m.group(2)}[DOB]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    if not settings.ALLOW_PHI_TO_LLM:
        for name in claimant_names or []:
            for part in {name, *[p for p in name.replace(".", " ").split() if len(p) > 2]}:
                text = re.sub(rf"\b{re.escape(part)}\b", "[CLAIMANT]", text)
    return text


def for_logs(text: str) -> str:
    return redact_text(text)
