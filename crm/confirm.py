"""Who may turn a proposed write into a saved one.

The CRM never saves a proposal on its own: `commit_write` asks a confirmation policy first.

ButtonConfirm (the web demo): the broker's Confirm button is the only thing that can save. When
the broker presses it, the server mints a token, an HMAC of the write id and the payload hash
with a secret the model never sees. A commit without that exact token is refused, so the model
cannot save anything, whatever it is told.

StatedConfirm (the MCP server): over MCP the server cannot see the person, so it cannot prove a
human said yes. It requires the person's own words of confirmation, refuses words that are not a
plain yes ("just log it, don't ask me", "yes but change the date"), and logs them. The skill's
read back is what makes those words real; the server makes sure they are there and recorded.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Protocol

from .errors import CRMError

# The person's own yes, at the start of their words: "yes", "ok, save it", "go ahead". Reported speech
# ("the user said yes") is not their words.
YES = re.compile(r"^\W*(?:please\s+)?(?:yes|yep|yeah|yup|confirm(?:ed)?|correct|go ahead|save it|looks (?:good|right)|"
                 r"ok(?:ay)?|sure|do it|that'?s right|sounds good)\b", re.I)
NOT_YES = re.compile(r"\b(?:no|not|nope|don'?t|do not|doesn'?t|wait|hold on|cancel|stop|never ?mind|but|change|wrong|instead|"
                     r"except|without asking|actually)\b|\?", re.I)
MAX_WORDS = 300


class ConfirmPolicy(Protocol):
    name: str

    def check(self, write: dict[str, Any], confirmation: Any) -> str:
        """Return how the write was confirmed, for the activity log, or raise CRMError."""
        ...


class ButtonConfirm:
    name = "button"

    def __init__(self, secret: bytes):
        if len(secret) < 16:
            raise ValueError("the confirm secret is too short")
        self._secret = secret

    def mint(self, write_id: str, payload_hash: str) -> str:
        return hmac.new(self._secret, f"confirm:{write_id}:{payload_hash}".encode(), hashlib.sha256).hexdigest()

    def check(self, write: dict[str, Any], confirmation: Any) -> str:
        if not isinstance(confirmation, str) or not confirmation:
            raise CRMError("needs_confirm", "Only the broker can save this: they press Confirm on the read back card. "
                                            "Nothing was saved. Tell the broker the read back is waiting for them.")
        if not hmac.compare_digest(confirmation, self.mint(write["id"], write["hash"])):
            raise CRMError("bad_confirm", "That confirmation is not valid for this write. Nothing was saved.")
        return "confirmed with the Confirm button"


class StatedConfirm:
    name = "stated"

    def check(self, write: dict[str, Any], confirmation: Any) -> str:
        words = " ".join(str(confirmation or "").split())[:MAX_WORDS]
        if not words:
            raise CRMError("needs_confirm", "A commit needs the person's own words of confirmation (user_confirmation), "
                                            "given after they saw the read back. Nothing was saved.")
        if NOT_YES.search(words) or not YES.match(words):
            raise CRMError("not_a_yes", f'"{words}" is not a plain yes to this read back. Nothing was saved. Read the write '
                                        "back again and ask for an explicit yes.")
        return f'person said: "{words}"'
