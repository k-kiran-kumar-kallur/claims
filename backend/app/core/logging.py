"""Structured JSON logging (structlog) with a PHI redaction filter (spec §15.2, §16.1)."""
from __future__ import annotations

import logging
import re
import sys

import structlog

from app.core.correlation import claim_id_var, correlation_id_var, node_var, run_id_var, user_id_var

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_DOB = re.compile(r"(?i)\b(dob|date of birth)\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")

# names registered at runtime (e.g. claimant names) are also scrubbed from log lines
_name_dictionary: set[str] = set()


def register_phi_terms(*terms: str | None) -> None:
    for t in terms:
        if t and len(t) >= 3:
            _name_dictionary.add(t)


def redact_text(text: str) -> str:
    text = _SSN.sub("[SSN]", text)
    text = _DOB.sub(lambda m: m.group(1) + ": [DOB]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    for term in _name_dictionary:
        text = re.sub(re.escape(term), "[NAME]", text, flags=re.IGNORECASE)
    return text


def _redact_processor(_, __, event_dict):
    for k, v in list(event_dict.items()):
        if isinstance(v, str) and k not in {"timestamp", "level", "correlation_id", "run_id", "claim_id"}:
            event_dict[k] = redact_text(v)
    return event_dict


def _context_processor(_, __, event_dict):
    for key, var in (("correlation_id", correlation_id_var), ("run_id", run_id_var),
                     ("claim_id", claim_id_var), ("user_id", user_id_var), ("node", node_var)):
        val = var.get()
        if val and key not in event_dict:
            event_dict[key] = val
    return event_dict


def configure_logging(level: str = "INFO", service: str = "api") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    for noisy in ("httpx", "httpcore", "uvicorn.access", "pdfminer", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            _context_processor,
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
