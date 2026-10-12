"""Who may turn a proposed write into a saved one.

The CRM never saves a proposal on its own: `commit_write` asks a confirmation policy first.

ButtonConfirm (the web demo): the broker's Confirm button is the only thing that can save. When
the broker presses it, the server mints a token, an HMAC of the write id and the payload hash
the broker saw, with a secret the model never sees. A commit without that exact token is
refused, so the model cannot save anything, whatever it is told.

StatedConfirm (the MCP server): over MCP the server cannot see the person, so it cannot prove a
human said yes. It requires the person's own words, and the WHOLE reply must be a short plain
yes from a closed list ("yes", "ok, go ahead", "looks good, save it"). Anything more is refused,
because a yes with a condition is not a yes: "save it later", "yes, and also add Hana",
"correct the email first", "sure, after lunch". The words are logged with the save. The skill's
read back is what makes those words real; the server makes sure they are there and recorded.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Protocol

from .errors import CRMError

# The whole reply, and nothing but these phrases, with only spaces and . , ! between them. No
# question mark ("yes?" is a question), no emoji, and "please" on its own is not a yes.
_YES = r"yes|yep|yeah|confirm(?:ed)?|go ahead|save it|do it|correct|looks (?:good|right)|that['’]?s right|ok(?:ay)?"
PLAIN_YES = re.compile(r"^[\s.,!]*(?:(?:please|" + _YES + r")(?:[\s.,!]+|$))+$", re.I)
HAS_YES = re.compile(r"\b(?:" + _YES + r")\b", re.I)
NOT_YES = re.compile(r"\b(?:no|not|nope|don'?t|do not|wait|hold on|cancel|stop|later|first|but|change|instead)\b", re.I)
LOGGED_WORDS = 300


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
                                            "Nothing was saved. Tell the broker the read back is waiting for them.",
                           plain="Only the broker can save this, with Confirm. Nothing was saved.")
        if not hmac.compare_digest(confirmation, self.mint(write["id"], write["hash"])):
            raise CRMError("bad_confirm", "That confirmation is not valid for this write. Nothing was saved.",
                           plain="That confirm does not match this change. Nothing was saved.")
        return "confirmed with the Confirm button"


class StatedConfirm:
    name = "stated"

    def check(self, write: dict[str, Any], confirmation: Any) -> str:
        words = " ".join(str(confirmation or "").split())
        shown = words[:LOGGED_WORDS]
        if not words:
            raise CRMError("needs_confirm", "A commit needs the person's own words of confirmation (user_confirmation), "
                                            "given after they saw the read back. Nothing was saved.",
                           plain="No words of confirmation were given. Nothing was saved.")
        if NOT_YES.search(words) or not PLAIN_YES.match(words) or not HAS_YES.search(words):
            raise CRMError("not_a_yes", f'"{shown}" is not a plain yes to this read back. Nothing was saved. Read the write '
                                        "back again and ask for an explicit yes.",
                           plain=f'"{shown}" is not a plain yes. Nothing was saved.')
        return f'person said: "{shown}"'
