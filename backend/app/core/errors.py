"""Error taxonomy (spec §14.1) and RFC 7807 problem-details helpers."""
from __future__ import annotations


class AppError(Exception):
    status_code = 500
    title = "Internal Server Error"
    type_ = "about:blank"

    def __init__(self, detail: str = "", *, status_code: int | None = None, extra: dict | None = None):
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if status_code:
            self.status_code = status_code
        self.extra = extra or {}


class NotFound(AppError):
    status_code, title, type_ = 404, "Not Found", "/problems/not-found"


class Forbidden(AppError):
    status_code, title, type_ = 403, "Forbidden", "/problems/forbidden"


class Unauthorized(AppError):
    status_code, title, type_ = 401, "Unauthorized", "/problems/unauthorized"


class Conflict(AppError):
    status_code, title, type_ = 409, "Conflict", "/problems/conflict"


class BadRequest(AppError):
    status_code, title, type_ = 400, "Bad Request", "/problems/bad-request"


class PayloadTooLarge(AppError):
    status_code, title, type_ = 413, "Payload Too Large", "/problems/payload-too-large"


# ---- workflow / agent errors (not HTTP) ------------------------------------------------------
class WorkflowError(Exception):
    retryable = False


class TransientExternalError(WorkflowError):
    """Gemini 429/5xx, timeouts, network errors."""
    retryable = True

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class QuotaExhaustedError(TransientExternalError):
    """Daily quota reached; the run pauses until the quota resets."""


class CircuitOpenError(TransientExternalError):
    pass


class LLMOutputError(WorkflowError):
    """Invalid JSON / schema violation / missing citations after the repair retry."""


class SafetyBlockError(WorkflowError):
    pass


class DocumentProcessingError(WorkflowError):
    """Corrupt / password-protected / unreadable document; the run continues without it."""


class ToolExecutionError(WorkflowError):
    pass


class LLMUnavailableError(WorkflowError):
    """No LLM configured (rules mode) - agents fall back to deterministic logic."""


class RunCancelled(WorkflowError):
    pass


class FatalError(WorkflowError):
    pass
