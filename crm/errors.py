from __future__ import annotations

from typing import Any


class CRMError(Exception):
    """A read or write the CRM refuses. `outcome` is what the activity log records: "refused"
    for a rule that was not met, "blocked" for a duplicate that would have been created."""

    def __init__(self, code: str, message: str, outcome: str = "refused", **extra: Any):
        super().__init__(message)
        self.code, self.message, self.outcome, self.extra = code, message, outcome, extra

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}
