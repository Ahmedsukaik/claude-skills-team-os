from __future__ import annotations

from typing import Any


class CRMError(Exception):
    """A read or write the CRM refuses. `message` is for the model (it may say what to do next);
    `plain` is for people: the activity log and the page show it. `outcome` is what the log
    records: "refused" for a rule that was not met, "blocked" for a duplicate that would have
    been created."""

    def __init__(self, code: str, message: str, outcome: str = "refused", plain: str | None = None, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.outcome, self.extra = code, message, outcome, extra
        self.plain = plain or message

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}
