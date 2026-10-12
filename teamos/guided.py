"""The guided rules: fixed keyword rules that stand in for Claude when there is no API key, the
budget is used up or the live model is down. No AI.

They pick a skill with simple keyword rules (the live path never does: Claude picks from the
skill descriptions), then use the same tools as Claude, one step at a time, so every rule in
the CRM and in the tool runner applies to them too. The page labels every guided reply
"Fixed rules". They cover the demo's story, the suggested questions and close variations;
anything else gets a short list of what they can help with.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from crm import data as crm_data
from crm.timestamps import lead_word, nice, relative_near

from .models import Turn

HOUSE = "house-rules"
SKILLS_FOR = {"debrief": [HOUSE, "voice-note-debrief"], "update": [HOUSE, "crm-update"], "prep": [HOUSE, "meeting-prep"],
              "email": [HOUSE, "follow-up-email"], "pipeline": [HOUSE, "weekly-pipeline"], "rules": [HOUSE],
              "whois": [HOUSE]}
CAN_DO = ("I can debrief a call or a tour from your voice note, update a contact, company or deal stage, prep you for "
          "a meeting, draft a follow up email, or summarise the pipeline.")
UNTOUCHED = "No skill needed, so the CRM wasn't touched."
NUMBERS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"]
# Questions near a skill's job that need no skill: a short fixed answer instead of a dead end.
CANNED = [
    (re.compile(r"\bloi\b|letter of intent", re.I), re.compile(r"\b(?:mean|stand for|what(?:'s| is))\b", re.I),
     "LOI is a letter of intent: a short, non-binding outline of the main lease terms (rent, term, start date) that "
     "both sides sign before the lease itself is drafted. " + UNTOUCHED),
    (re.compile(r"\bsales pipeline\b|\bpipeline\b", re.I), re.compile(r"^\s*what(?:'s| is)\s+an?\b", re.I),
     "A sales pipeline is the list of deals a team is working on, grouped by how far along each one is. Ours runs "
     "Lead, Touring, Proposal sent, LOI signed, Lease negotiation, then Closed won or lost. Ask for the weekly pipeline "
     "to see it. " + UNTOUCHED),
    (re.compile(r"\bvoice notes?\b", re.I), re.compile(r"\b(?:tips?|how (?:do|should|can) i|advice)\b", re.I),
     "Say who you met, where and when; what they liked and what worried them; and each next step, with a date if you "
     "have one. A full date (\"Friday, October 23, 2026\") is saved as a date; \"next week\" stays in your words. "
     + UNTOUCHED),
    (re.compile(r"\bsummari[sz]e\b", re.I), re.compile(r".", re.I),
     "Fixed rules can't summarise an article; with the live AI on, Claude can. " + UNTOUCHED),
    (re.compile(r"\b(?:lunch|coffee shop|restaurant|places? to eat)\b", re.I), re.compile(r"\b(?:good|best|where|spot)\b", re.I),
     "I don't have restaurant listings, so I can't suggest a spot. " + UNTOUCHED),
    (re.compile(r"\bweather\b", re.I), re.compile(r".", re.I),
     "I can't see weather forecasts. For the tour itself, ask me to prep you for it. " + UNTOUCHED),
    (re.compile(r"^\s*(?:what can you do|help|what do you do)\b", re.I), re.compile(r".", re.I), CAN_DO),
]
WHOIS = re.compile(r"^\s*(?:who(?:'s| is)|tell me about|what do we (?:know|have) (?:on|about))\b", re.I)

_WD = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_MON = (r"(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)")
EXACT_TIME = re.compile(
    r"(?:(?:" + _WD + r"|mon|tues|tue|wed|thurs|thur|thu|fri|sat|sun)\.?,?\s+)?"
    r"(?:" + _MON + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?(?:\s+of)?\s+" + _MON +
    r"\.?,?\s+\d{4}|\d{4}-\d{2}-\d{2})"
    r"(?:,?\s+(?:at\s+)?(?:noon|\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\d{1,2}:\d{2}))?", re.I)
VAGUE_TIME = re.compile(
    r"\b(?:yesterday(?:\s+(?:morning|afternoon|evening))?|earlier today|this (?:morning|afternoon|evening|week)|"
    r"just now|today|tonight|a (?:few|couple of) days ago|last (?:week|month|night|" + _WD + r")|on " + _WD + r"|"
    r"next (?:week|month|" + _WD + r")|tomorrow(?:\s+(?:morning|afternoon))?|end of (?:the )?(?:day|week|month)|"
    r"in (?:a|one|two|three|\d+) (?:days?|weeks?)|(?:by|before) (?:" + _WD + r"|the end of (?:the )?(?:week|month)))\b", re.I)
META = re.compile(r"\b(?:just (?:log|write|save|record|add) it|don'?t (?:ask|check with) me|no need to (?:ask|confirm|check)|"
                  r"without asking|ignore (?:the |your |all )?(?:house )?rules|skip the (?:read ?back|confirm))\b", re.I)
HEADER = re.compile(r"^\s*(?:voice note|debrief|quick (?:one|note|debrief)|note to self|for the crm)\b[^:.]*[:.]\s*", re.I)
LOG_LEAD = re.compile(r"^\s*(?:please )?log (?:a|my|the|this) (?:call|meeting|tour|visit|note|coffee)(?: with [^:.]+)?\s*[:.]\s*", re.I)
NEXT = re.compile(r"^\s*(?:next steps?|to ?dos?|action items?)\s*:\s*", re.I)
WILL = re.compile(r"^\s*(?:i(?:'ll| will| need to| have to| should)|we(?:'ll| will| need to)|need to)\s+", re.I)
FOLLOW = re.compile(r"\bfollow(?:ing)?[\s-]?up\b", re.I)
VERBS = r"(?:send|set|book|schedule|call|email|get|check|ask|share|draft|confirm|arrange|find|pull|chase|introduce)"
SPLIT_ITEMS = re.compile(r",\s*(?:and\s+)?|\s+and\s+(?=" + VERBS + r"\b)", re.I)
ABBREV = re.compile(r"\b(jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|"
                    r"st|rd|dr|sq|mr|ms|mrs)\.(?=\s+\d|(?-i:\s+[a-z]))", re.I)

DEBRIEF = re.compile(r"\b(?:voice note|debrief|just (?:left|finished|wrapped|got (?:out|off|back))|walked|toured|"
                     r"tour (?:of|at|with)|showed (?:him|her|them)|site visit (?:with|at)|met with|had (?:a |an )?"
                     r"(?:call|coffee|lunch|meeting|chat) with|call with|spoke (?:with|to)|talked (?:with|to)|i called|called|"
                     r"log (?:a|my|the|this) (?:call|meeting|tour|note|visit|coffee)|notes? from|after the (?:call|tour|meeting))\b",
                     re.I)
PREP = re.compile(r"\b(?:prep|prepare|brief me|briefing|get me ready|ready for|before (?:my|the|our) (?:meeting|call|tour|visit)|"
                  r"what should i know)\b", re.I)
EMAIL_WORD = re.compile(r"\b(?:e-?mail|thank[- ]you note|draft (?:a |an |the )?(?:note|message|reply|follow[- ]?up))\b", re.I)
PIPELINE = re.compile(r"\b(?:weekly pipeline|pipeline (?:summary|review|update|report)|(?:my|our|the team'?s|the) pipeline|"
                      r"stale deals?|deals? (?:by stage|are stale|need attention|going stale)|open deals)\b", re.I)
DEFINITION = re.compile(r"^\s*(?:what(?:'s| is| are| does)|define|explain|meaning of)\b.*\b(?:mean|stand for|a (?:sales )?pipeline|"
                        r"an? (?:loi|lead|deal stage))\b|\bwhat does \w+ (?:mean|stand for)\b", re.I)
UPDATE_VERB = re.compile(r"\b(?:update|move|change|set|mark|bump|advance|put)\b", re.I)
_ASK = r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
ADD_CONTACT = re.compile(_ASK + r"(?:add|create)\b.{0,60}\bcontact\b", re.I)
EDIT_CONTACT = re.compile(_ASK + r"(?:change|update|correct|fix|set)\b.{0,40}\b(?:email|e-mail|job title|title)\b", re.I)
ADD_COMPANY = re.compile(_ASK + r"(?:add|create)\b.{0,20}\bcompany\b", re.I)
ADD_LEAD = re.compile(_ASK + r"(?:add|create)\s+(?:a\s+)?(?:new\s+)?(?:contact\s*:?\s*(?:for\s+)?)?", re.I)
RULES_Q = re.compile(r"\b(?:house rules|our rules|timestamp rule|how (?:do|should) (?:we|i) (?:log|record|handle|enter|write) "
                     r"(?:times?|dates?|timestamps?)|what counts as a (?:yes|confirm)|why (?:do|does) (?:it|you) (?:ask|need) "
                     r"(?:me )?(?:to )?confirm)\b", re.I)
YES = re.compile(r"^\s*(?:yes|yep|yeah|ok(?:ay)?|sure|confirm(?:ed)?|go ahead|save it|looks good|correct|do it)\b[\s\w,.!]{0,30}$",
                 re.I)
NO = re.compile(r"^\s*(?:no|nope|cancel|discard|scrap|don'?t save)\b[\s\w,.!]{0,30}$", re.I)
GREETING = re.compile(r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening))\b[\s!.,]*(?:there|claude)?[\s!.,]*$", re.I)
THANKS = re.compile(r"^\s*(?:thanks|thank you|thx|cheers|great|perfect)\b[^?]{0,30}$", re.I)
STAGE_WORDS = [("LOI signed", r"\bloi signed\b|\bsigned the loi\b|\bsigned an loi\b"),
               ("Lease negotiation", r"\blease negotiation\b|\bin negotiation\b|\bredlines\b"),
               ("Proposal sent", r"\bproposal sent\b|\bsent (?:the |a )?proposal\b"),
               ("Closed won", r"\bclosed won\b|\bsigned the lease\b|\bwon\b"),
               ("Closed lost", r"\bclosed lost\b|\blost\b|\bwent elsewhere\b"),
               ("Touring", r"\btouring\b"), ("Lead", r"\blead\b")]
EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TOUR = re.compile(r"\b(?:tour|toured|walked|walk-?through|showing|site visit)\b", re.I)
CALL = re.compile(r"\b(?:call|called|phone|rang)\b", re.I)
COMPANY_KEYS = {cid: key for cid, key in (("CO-1", "quillon"), ("CO-2", "bramblecote"), ("CO-3", "tessarine"),
                                          ("CO-4", "brindlewick"), ("CO-5", "kilnworth"), ("CO-6", "quorvane"))}
COMPANY_NAMES = {cid: name for cid, name, _ in crm_data.COMPANIES}


# ---------------------------------------------------------------------------- reading a request
def contact_mentions(text: str) -> list[str]:
    """Contacts named in the text, as search queries: full names first, then last or first names."""
    full = [f"{f} {la}" for _, f, la, _, _ in crm_data.CONTACTS if re.search(rf"\b{f}\s+{la}\b", text, re.I)]
    if full:
        return full
    out: list[str] = []
    for _, first, last, _, _ in crm_data.CONTACTS:
        for name in (last, first):
            if re.search(rf"\b{name}\b", text) and name not in out:  # a single name must be capitalised
                out.append(name)
                break
    return out


def company_mentions(text: str) -> list[str]:
    return [cid for cid, key in COMPANY_KEYS.items() if re.search(rf"\b{key}\b", text, re.I)]


def property_mention(text: str) -> str | None:
    for _, _, address, _, _ in crm_data.PROPERTIES:
        number, word = address.split()[0], address.split()[1].lower()
        if re.search(rf"\b{number}\s+{word}\b|\b{word}\s+(?:st|street|rd|road|dr|drive|sq|square|pond)\b", text, re.I):
            return address
    return None


def stage_mention(text: str) -> str | None:
    return next((stage for stage, pattern in STAGE_WORDS if re.search(pattern, text, re.I)), None)


def classify(text: str) -> str | None:
    """The skill family a request belongs to, by fixed rules. None means no skill."""
    names = contact_mentions(text) or company_mentions(text)
    place = property_mention(text)
    if DEFINITION.search(text) and not names:
        return None
    if WHOIS.search(text) and names:
        return "whois"
    if PREP.search(text) and (names or place or re.search(r"\b(?:meeting|call|tour)\b", text, re.I)):
        return "prep"
    if ADD_CONTACT.search(text) or ADD_COMPANY.search(text) or EDIT_CONTACT.search(text):
        return "update"
    if UPDATE_VERB.search(text) and stage_mention(text) and (names or place or re.search(r"\bdeal\b", text, re.I)):
        return "update"
    if DEBRIEF.search(text) and (names or place):
        return "debrief"
    if EMAIL_WORD.search(text) and (names or re.search(r"\bfollow[- ]?up email\b|\bclient email\b", text, re.I)):
        return "email"
    if PIPELINE.search(text):
        return "pipeline"
    if RULES_Q.search(text) and not names:
        return "rules"
    return None


def find_time(text: str) -> str | None:
    """The first stated time in the text, exactly as written. A date inside a relative phrase
    ("two weeks after Friday, October 23, 2026") comes with the phrase, so it stays words."""
    m = EXACT_TIME.search(text)
    if m:
        begin, end = m.start(), m.end()
        near = relative_near(text, begin, end)
        if near:
            follows = re.match(r"[\s,]*" + re.escape(near), text[end:], re.I)
            if follows:   # "on Friday, October 23, 2026 or so": the words after it come too
                end += follows.end()
            else:         # "two weeks after the tour, which is Friday, ...": from the first relative word
                hits = [x.start() for x in re.finditer(r"\b" + re.escape(near.split()[0]) + r"\b", text[:begin], re.I)]
                begin = hits[-1] if hits else begin
        lead = lead_word(text, begin)
        if lead:      # "by Friday, ..." keeps its "by": a deadline is not an agreed day; "on" may go
            begin = text.lower().rfind(lead, 0, begin)
        return text[begin:end].strip(" ,.")
    m = VAGUE_TIME.search(text)
    return m.group(0).strip(" ,.") if m else None


def sentences(text: str) -> list[str]:
    protected = ABBREV.sub(lambda m: m.group(1) + "․", text)
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [p.replace("․", ".").strip() for p in parts if p.strip()]


def _cap(s: str) -> str:
    s = s.strip().rstrip(".!")
    return s[:1].upper() + s[1:]


@dataclass
class Debrief:
    summary: str
    discussed: list[str]
    next_steps: list[str]
    tasks: list[tuple[str, str | None]]   # title, due words
    stated: str | None


def read_debrief(text: str, contact: dict[str, Any], property_address: str | None) -> Debrief:
    first, name = contact["first_name"], contact["name"]
    body = LOG_LEAD.sub("", HEADER.sub("", text, count=1), count=1)
    discussed: list[str] = []
    steps: list[str] = []
    tasks: list[tuple[str, str | None]] = []
    stated = None
    for s in sentences(body):
        if META.search(s):
            s = s.split(":", 1)[1] if ":" in s and META.search(s.split(":", 1)[0]) else META.sub("", s)
            s = re.sub(r"^[\s,.;:-]+|[\s,;:-]+$", "", s)
            if len(s.split()) < 3:
                continue
        if re.match(r"^\s*(?:voice note|debrief)\b", s, re.I):
            continue
        if FOLLOW.search(s):
            due = find_time(s)
            tasks.append((f"Follow up with {first}", due))
            continue
        if NEXT.match(s) or WILL.match(s):
            for item in SPLIT_ITEMS.split(WILL.sub("", NEXT.sub("", s))):
                item = _cap(item)
                if item:
                    steps.append(item)
                    tasks.append((re.sub(r"\b(?:him|her)\b", first, item), find_time(item)))
            continue
        when = find_time(s)
        names_it = re.search(rf"\b(?:{re.escape(first)}|{re.escape(contact['last_name'])})\b", s)
        if when and stated is None:
            stated = when
            if names_it:
                continue  # the intro: who, where and when
        discussed.append(_cap(s))
    if not discussed:
        discussed = [_cap(body)][:1]
    kind = "Tour" if TOUR.search(text) else "Call" if CALL.search(text) else "Coffee" if re.search(r"\bcoffee\b", text, re.I) \
        else "Meeting"
    summary = f"Tour of {property_address} with {name}" if kind == "Tour" and property_address else f"{kind} with {name}"
    return Debrief(summary, discussed[:5], steps[:6], tasks[:7], stated)


# ---------------------------------------------------------------------------- the chat so far
TAG = re.compile(r"^\s*<(session_info|crm_update)>")


@dataclass
class Chat:
    messages: list[dict[str, Any]]
    texts: list[str] = field(default_factory=list)        # the broker's messages
    updates: list[str] = field(default_factory=list)      # <crm_update> texts
    broker: str = ""
    turn: list[tuple[dict[str, Any], dict[str, Any], bool]] = field(default_factory=list)  # this turn's calls
    loaded: set[str] = field(default_factory=set)
    proposed: list[str] = field(default_factory=list)     # write ids proposed in the chat
    n: int = 0                                            # tool calls so far, for ids
    asked: str = ""                                       # the assistant's last words before the broker's message

    def __post_init__(self) -> None:
        calls: dict[str, tuple[int, dict[str, Any]]] = {}
        last_broker = -1
        said = ""
        for i, m in enumerate(self.messages):
            if m["role"] == "assistant":
                said = " ".join(b.get("text", "") for b in m["content"] if b.get("type") == "text") or said
            content =m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            for b in content:
                if m["role"] == "user" and b.get("type") == "text":
                    tag = TAG.match(b["text"])
                    if tag is None:
                        self.texts.append(b["text"])
                        last_broker = i
                        self.asked = said
                    elif tag.group(1) == "crm_update":
                        self.updates.append(b["text"])
                    else:
                        found = re.search(r"Signed in: ([^(<]+?) \(", b["text"])
                        self.broker = found.group(1).strip() if found else ""
                elif b.get("type") == "tool_use":
                    calls[b["id"]] = (i, b)
                    self.n += 1
        for m in self.messages:
            if m["role"] != "user" or not isinstance(m["content"], list):
                continue
            for b in m["content"]:
                if b.get("type") != "tool_result" or b.get("tool_use_id") not in calls:
                    continue
                at, call = calls[b["tool_use_id"]]
                data = _json(b.get("content"))
                failed = bool(b.get("is_error"))
                if call["name"] == "load_skill" and not failed:
                    self.loaded.add(call["input"].get("name", ""))
                if call["name"] == "propose_write" and not failed and data.get("write_id"):
                    self.proposed.append(data["write_id"])
                if at > last_broker:
                    self.turn.append((call, data, failed))

    @property
    def text(self) -> str:
        return self.texts[-1] if self.texts else ""

    @property
    def broker_first(self) -> str:
        return self.broker.split()[0] if self.broker else ""

    def pending(self) -> list[str]:
        closed = set(re.findall(r"\bW-\d+\b", " ".join(self.updates)))
        return [w for w in self.proposed if w not in closed]

    def done(self, name: str) -> list[tuple[dict[str, Any], dict[str, Any], bool]]:
        return [t for t in self.turn if t[0]["name"] == name]

    def call(self, tool: str, /, **data: Any) -> dict[str, Any]:
        self.n += 1
        return {"type": "tool_use", "id": f"toolu_guided_{self.n:03d}", "name": tool, "input": data}


def _json(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    try:
        data = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


# ---------------------------------------------------------------------------- the rules
class GuidedModel:
    mode = "guided"
    name = "guided"

    def respond(self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> Turn:
        chat = Chat(messages)
        content = plan(chat)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return Turn(content, stop, "guided", "guided")


def plan(chat: Chat) -> list[dict[str, Any]]:
    text = chat.text
    request, answer = text, None
    if "Which one did you mean?" in chat.asked and len(chat.texts) >= 2 and classify(text) is None and _is_answer(text):
        request, answer = chat.texts[-2], text  # the broker answered a clarifying question
    intent = classify(request)
    if intent is None:
        if chat.pending() and YES.match(text):
            return [_text("To save it, press Confirm on the read back card. In this demo only the Confirm button can save a "
                          "write: a yes typed in the chat is not enough.")]
        if chat.pending() and NO.match(text):
            return [_text("Nothing is saved. Press Discard on the card to drop it, or tell me what to change.")]
        if GREETING.match(text):
            return [_text(f"Hi{' ' + chat.broker_first if chat.broker_first else ''}. {CAN_DO}")]
        if THANKS.match(text):
            return [_text("You're welcome.")]
        canned = next((answer for topic, ask, answer in CANNED if topic.search(text) and ask.search(text)), None)
        return [_text(canned or "No skill fits that one, so I've left the CRM alone. " + CAN_DO)]
    loads = [chat.call("load_skill", name=s) for s in SKILLS_FOR[intent]
             if s not in chat.loaded and not any(c["input"].get("name") == s for c, _, _ in chat.done("load_skill"))]
    handler = {"debrief": _debrief, "update": _update, "prep": _prep, "email": _email, "pipeline": _pipeline,
               "rules": _rules, "whois": _whois}[intent]
    out = handler(chat, request, answer)
    if loads:
        calls = [b for b in out if b["type"] == "tool_use"]
        return loads + calls  # skills first; text written with tool calls is not shown, so it waits a step
    return out


def _is_answer(text: str) -> bool:
    """A short reply that names someone ("Dana Okafor", "the Bramblecote one"), not a new question."""
    return "?" not in text and len(text.split()) <= 8 and bool(contact_mentions(text) or company_mentions(text))


def _who(chat: Chat, request: str, answer: str | None) -> str | None:
    if answer:
        names = contact_mentions(answer)
        if names:
            return names[0]
        asked_for = (contact_mentions(request) or [""])[0]   # "the Bramblecote one" after "Dana": Dana at Bramblecote
        companies = company_mentions(answer)
        match = [f"{f} {la}" for _, f, la, _, co in crm_data.CONTACTS if co in companies and asked_for in (f, la)]
        return match[0] if len(match) == 1 else answer.strip(" .?!")[:60]
    names = contact_mentions(request)
    return names[0] if names else None


def _pick_contact(chat: Chat, query: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """(the one contact, None), or (None, the matches to ask about); (None, []) when nothing matched."""
    results = [r for c, d, _ in chat.done("search_crm") if c["input"].get("query") == query for r in d.get("results", [])
               if r["type"] == "contact"]
    if len(results) == 1:
        return results[0], None
    return None, results


def _ask_which(query: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not matches:
        return _text(f"I couldn't find {query} in the CRM. Do you want to add them as a new contact first?")
    options = " or ".join(f"{m['name']} ({m['company']})" for m in matches)
    return _text(f"There are {len(matches)} contacts called {query} in the CRM: {options}. Which one did you mean?")


def _record(chat: Chat, record_id: str) -> dict[str, Any] | None:
    return next((d for c, d, failed in chat.done("get_record") if c["input"].get("record_id") == record_id and not failed), None)


def _open_deals(rec: dict[str, Any], property_id: str | None = None) -> list[dict[str, Any]]:
    deals = [d for d in rec.get("deals", []) if d["stage"] in crm_data.OPEN_STAGES]
    if property_id:
        deals = [d for d in deals if d.get("property_id") == property_id]
    return deals


def _after_propose(chat: Chat, request: str, names: dict[str, str]) -> list[dict[str, Any]] | None:
    done = chat.done("propose_write")
    if not done:
        return None
    _, data, failed = done[-1]
    if failed:
        return [_text(f"The CRM did not accept that: {data.get('message', 'it was refused')}")]
    lead = "Every write needs your confirm after the read back, so nothing is saved yet. " if META.search(request) else ""
    return [_text(lead + card_reply(data))]


def card_reply(preview: dict[str, Any]) -> str:
    """The words next to the read back card. The card itself shows every field that will be saved."""
    vague = sum(1 for c in preview["changes"] for p in ("stated_time", "due") if c.get(f"{p}_note"))
    odd = sum(1 for c in preview["changes"] for p in ("stated_time", "due") if c.get(f"{p}_warning"))
    out = "Here's what I'll save."
    if vague:
        out += f" {NUMBERS[min(vague, 8)]} time{' was' if vague == 1 else 's were'} vague, so I kept your words."
    if odd:
        out += f" {NUMBERS[min(odd, 8)]} date{' needs' if odd == 1 else 's need'} a check."
    return out + " Press Confirm, or tell me what to change."


def _whois(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    """A read only lookup: who someone is, their company, deals and the last note."""
    query = _who(chat, request, answer)
    companies = company_mentions(request)
    if query is None and companies:
        query = COMPANY_NAMES[companies[0]]
    if query is None:
        return [_text("Who should I look up?")]
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=query)]
    contact, matches = _pick_contact(chat, query)
    if contact is None and matches:
        return [_ask_which(query, matches)]
    if contact is None:
        company = next((r for _, d, _ in chat.done("search_crm") for r in d.get("results", []) if r["type"] == "company"), None)
        if company is None:
            return [_text(f"I couldn't find {query} in the CRM.")]
        rec = _record(chat, company["id"])
        if rec is None:
            return [chat.call("get_record", record_id=company["id"])]
        people = ", ".join(f"{c['name']} ({c['job_title']})" for c in rec.get("contacts", [])) or "no contacts"
        deals = "; ".join(f"{d['name']} ({d['stage']})" for d in rec.get("deals", [])) or "no deals"
        return [_text(f"{rec['name']} ({rec.get('industry') or 'no industry noted'}). People: {people}. Deals: {deals}.")]
    rec = _record(chat, contact["id"])
    if rec is None:
        return [chat.call("get_record", record_id=contact["id"])]
    deals = "; ".join(f"{d['name']} ({d['stage']}, last activity {d['days_since_activity']} days ago)"
                      for d in rec.get("deals", [])) or "none in the CRM"
    notes = rec.get("recent_notes") or []
    last = f" Last note: {notes[0]['summary']}." if notes else ""
    return [_text(f"{rec['name']} is {rec['job_title']} at {rec['company']}. Deals: {deals}.{last}")]


def _debrief(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    query = _who(chat, request, answer)
    place = property_mention(request)
    if not chat.done("search_crm"):
        if query is None:
            return [_text("I couldn't tell who this note is about. Which contact is it?")]
        return [chat.call("search_crm", query=query)] + ([chat.call("search_crm", query=place)] if place else [])
    after = _after_propose(chat, request, _names(chat))
    if after is not None:
        return after
    assert query is not None
    contact, matches = _pick_contact(chat, query)
    if contact is None:
        return [_ask_which(query, matches or [])]
    rec = _record(chat, contact["id"])
    if rec is None:
        return [chat.call("get_record", record_id=contact["id"])]
    prop = next((r for c, d, _ in chat.done("search_crm") if c["input"].get("query") == place for r in d.get("results", [])
                 if r["type"] == "property"), None)
    deals = _open_deals(rec, prop["id"] if prop else None)
    note = read_debrief(request, rec, prop["address"] if prop else None)
    common = {"contact_id": contact["id"], **({"deal_id": deals[0]["id"]} if len(deals) == 1 else {})}
    changes: list[dict[str, Any]] = [{"op": "create_note", **common, "summary": note.summary, "discussed": note.discussed,
                                      **({"property_id": prop["id"]} if prop else {}),
                                      **({"next_steps": note.next_steps} if note.next_steps else {}),
                                      **({"stated_time_text": note.stated} if note.stated else {})}]
    for title, due in note.tasks:
        changes.append({"op": "create_task", "title": title, **common, **({"due_text": due} if due else {})})
    return [chat.call("propose_write", summary=note.summary, changes=changes)]


def _names(chat: Chat) -> dict[str, str]:
    """Labels for ids the rules have seen in this turn's results."""
    names: dict[str, str] = {}
    for _, d, _ in chat.turn:
        for r in d.get("results", []) + d.get("deals", []) + ([d] if d.get("id") else []):
            if not isinstance(r, dict) or not r.get("id"):
                continue
            label = r.get("name") or r.get("summary") or r["id"]
            if r.get("company") and str(r["id"]).startswith("C-"):
                label = f"{label} ({r['company']})"
            if r.get("stage") and str(r["id"]).startswith("D-"):
                label = f"{label} ({r['stage']})"
            names.setdefault(r["id"], label)
    names.update({cid: name for cid, name in COMPANY_NAMES.items() if cid not in names})
    return names


def _update(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    after = _after_propose(chat, request, _names(chat))
    if after is not None:
        return after
    if ADD_COMPANY.search(request) and not ADD_CONTACT.search(request):
        return _add_company(chat, request)
    if ADD_CONTACT.search(request):
        return _add_contact(chat, request)
    if EDIT_CONTACT.search(request):
        return _edit_contact(chat, request, answer)
    stage = stage_mention(request)
    if stage is None:
        return [_text("Which stage should it move to? The stages are: " + ", ".join(crm_data.STAGES) + ".")]
    query = _who(chat, request, answer)
    companies = company_mentions(request)
    if query is None and companies:
        query = COMPANY_KEYS[companies[0]].title()
    if query is None:
        return [_text("Which deal do you mean? Give me the client's name or the property.")]
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=query)]
    contact, matches = _pick_contact(chat, query)
    rec: dict[str, Any] | None = None
    if contact is None and not matches:
        company = next((r for _, d, _ in chat.done("search_crm") for r in d.get("results", []) if r["type"] == "company"), None)
        if company is None:
            return [_ask_which(query, [])]
        rec = _record(chat, company["id"])
        if rec is None:
            return [chat.call("get_record", record_id=company["id"])]
    elif contact is None:
        return [_ask_which(query, matches or [])]
    else:
        rec = _record(chat, contact["id"])
        if rec is None:
            return [chat.call("get_record", record_id=contact["id"])]
    deals = _open_deals(rec)
    if not deals:
        return [_text(f"{rec['name']} has no open deal in the CRM, so there is nothing to move.")]
    if len(deals) > 1:
        return [_text("There is more than one open deal: " + " or ".join(f"{d['name']} ({d['stage']})" for d in deals)
                      + ". Which one did you mean?")]
    change = {"op": "update_deal_stage", "deal_id": deals[0]["id"], "stage": stage}
    when = find_time(request)
    if when:
        change["stated_time_text"] = when
    return [chat.call("propose_write", summary=f"Move {deals[0]['name']} to {stage}", changes=[change])]


# A name word in any alphabet: "Nora", "Mary-Jane", "O'Neill", "Dána", or a caseless script.
NAME_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")


def _is_name_word(word: str) -> bool:
    first = word[0]
    return first.isupper() or first.lower() == first.upper()   # capitalised, or a script without case


def person_name(text: str) -> tuple[str, str] | None:
    """The first two name words next to each other, as (first, last), from text that holds no email."""
    found = list(NAME_WORD.finditer(text))
    for a, b in zip(found, found[1:], strict=False):
        if text[a.end():b.start()].strip() == "" and _is_name_word(a.group(0)) and _is_name_word(b.group(0)):
            return a.group(0), b.group(0)
    return None


def _add_contact(chat: Chat, request: str) -> list[dict[str, Any]]:
    email = EMAIL_ADDR.search(request)
    before = request[:email.start()] if email else request   # the name comes before the email, never from it
    parts = person_name(ADD_LEAD.sub("", before, count=1))
    companies = company_mentions(request)
    if not parts:
        return [_text("What is the new contact's full name?")]
    name = " ".join(parts)
    if company_mentions(name) or name.lower() in {n.lower() for n in COMPANY_NAMES.values()}:
        return [_text(f"{name} is the name of a company in the CRM. What is the new contact's own full name?")]
    if not email:
        return [_text(f"What is {name}'s email address? I won't make one up.")]
    if not companies:
        return [_text(f"Which company is {name} at?")]
    address, company = email.group(0).lower(), companies[0]
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=address), chat.call("search_crm", query=name)]
    for _, d, _ in chat.done("search_crm"):
        for r in d.get("results", []):
            if r["type"] == "contact" and (r["email"] == address or (r["name"].lower() == name.lower() and r["company_id"] == company)):
                return [_text(f"{r['name']} is already in the CRM ({r['company']}, {r['email']}), so I haven't added a new "
                              "contact. Do you want to update that one instead?")]
    return [chat.call("propose_write", summary=f"Add {name} as a contact", changes=[
        {"op": "create_contact", "first_name": parts[0], "last_name": parts[1], "email": address, "company_id": company}])]


def _add_company(chat: Chat, request: str) -> list[dict[str, Any]]:
    m = re.search(r"\bcompany\b\s*:?\s*(?:called\s+)?([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*)*)", request)
    if not m:
        return [_text("What is the company's name?")]
    name = m.group(1).strip(" .")
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=name, record_type="company")]
    for _, d, _ in chat.done("search_crm"):
        for r in d.get("results", []):
            if r["type"] == "company" and r["name"].lower().startswith(name.lower().split()[0]):
                return [_text(f"{r['name']} is already in the CRM, so I haven't added it again.")]
    return [chat.call("propose_write", summary=f"Add the company {name}", changes=[{"op": "create_company", "name": name}])]


def _edit_contact(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    query = _who(chat, request, answer)
    email = EMAIL_ADDR.search(request)
    title = re.search(r"\btitle to\s+(.+?)[.!]?$", request, re.I)
    if query is None:
        return [_text("Which contact should I change?")]
    if not email and not title:
        return [_text(f"What should {query}'s new email or job title be?")]
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=query, record_type="contact")]
    contact, matches = _pick_contact(chat, query)
    if contact is None:
        return [_ask_which(query, matches or [])]
    change: dict[str, Any] = {"op": "update_contact", "contact_id": contact["id"]}
    if email:
        change["email"] = email.group(0).lower()
    if title:
        change["job_title"] = title.group(1).strip()
    return [chat.call("propose_write", summary=f"Update {contact['name']}", changes=[change])]


def _prep(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    query = _who(chat, request, answer)
    companies = company_mentions(request)
    place = property_mention(request)
    if not chat.done("get_calendar"):
        reads = [chat.call("get_calendar", days_ahead=7)]
        if query:
            reads.append(chat.call("search_crm", query=query, record_type="contact"))
        return reads
    events: list[dict[str, Any]] = next((d.get("events", []) for _, d, _ in chat.done("get_calendar")), [])
    contact = None
    if query:
        contact, matches = _pick_contact(chat, query)
        if contact is None:
            return [_ask_which(query, matches or [])]
    else:
        key = (place or (COMPANY_KEYS[companies[0]] if companies else "")).lower()
        event = next((e for e in events if key and key.split()[0] in e["title"].lower()), None)
        if event and event["people"]:
            contact = {"id": event["people"][0]["id"], "name": event["people"][0]["name"]}
    if contact is None:
        listing = "; ".join(f"{e['title']} ({e['when']})" for e in events) or "nothing in the next 7 days"
        return [_text(f"Which meeting do you mean? On the calendar: {listing}.")]
    rec = _record(chat, contact["id"])
    if rec is None:
        return [chat.call("get_record", record_id=contact["id"])]
    return [_text(brief_text(rec, [e for e in events if any(p["id"] == contact["id"] for p in e["people"])]))]


def brief_text(rec: dict[str, Any], events: list[dict[str, Any]]) -> str:
    lines = []
    if events:
        e = events[0]
        start = e["start"].replace("T", " ")
        lines += [f"{e['title']}, {e['when']} ({nice(start[:10])}, {start[11:]}), {e['minutes']} min",
                  f"With: {', '.join(p['name'] for p in e['people'])} ({rec['company']})"]
        if e.get("property"):
            lines.append(f"Property: {e['property']}")
    else:
        lines.append(f"No meeting with {rec['name']} in the next 7 days. Here is where things stand.")
    lines += ["", "Where it stands"]
    deals = _open_deals(rec)
    lines += [f"- Deal: {d['name']}, {d['stage']}, last activity {d['days_since_activity']} days ago" for d in deals] \
        or ["- Deal: nothing open in the CRM"]
    notes = rec.get("recent_notes") or []
    if notes:
        n = notes[0]
        lines.append(f"- Last note ({nice(n['recorded_at'][:10])}): {n['summary']}" +
                     (f"; {n['discussed'][0]}" if n["discussed"] else ""))
    else:
        lines.append("- Last note: nothing in the CRM")
    lines += ["", "Open items"]
    tasks = rec.get("open_tasks") or []
    lines += [f"- {t['title']} (due {nice(t['due']) if t['due'] else 'no date'})" for t in tasks] or ["- nothing in the CRM"]
    concerns = [x for n in notes for x in n["discussed"] if re.search(r"\b(?:needs?|wants?|worried|concern|checking|pushing)\b",
                                                                        x, re.I)][:2]
    if concerns:
        lines += ["", "Ask about"] + [f"- {c}" for c in concerns]
    return "\n".join(lines)


def _email(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    query = _who(chat, request, answer)
    if query is None:
        return [_text("Who is the email for?")]
    if not chat.done("search_crm"):
        return [chat.call("search_crm", query=query, record_type="contact")]
    drafted = chat.done("create_email_draft")
    if drafted:
        _, d, failed = drafted[-1]
        if failed:
            return [_text(f"I couldn't save the draft: {d.get('message', 'it was refused')}")]
        sending = re.search(r"\bsend\b", request, re.I)
        return [_text(("I can't send email: I only save drafts, and you send them yourself after a read.\n\n" if sending else "")
                      + f"I saved a draft to {d['to_name']} in your mailbox. It is not sent.\n\nSubject: {d['subject']}\n\n"
                      + d["body"])]
    contact, matches = _pick_contact(chat, query)
    if contact is None:
        return [_ask_which(query, matches or [])]
    rec = _record(chat, contact["id"])
    if rec is None:
        return [chat.call("get_record", record_id=contact["id"])]
    subject, body = email_draft(rec, chat.broker_first)
    return [chat.call("create_email_draft", contact_id=contact["id"], subject=subject, body=body)]


def email_draft(rec: dict[str, Any], broker_first: str) -> tuple[str, str]:
    notes = rec.get("recent_notes") or []
    deals = _open_deals(rec)
    topic = deals[0]["name"].split(" at ")[-1] if deals else rec["company"]
    subject = f"Following up on {topic}"
    paras = [f"Hi {rec['first_name']},",
             f"Thanks again for your time on {topic}. I'm following up on our last conversation." if notes else
             f"I'm following up on {topic}."]
    tasks = rec.get("open_tasks") or []
    if tasks:
        title = tasks[0]["title"]
        paras.append(f"Next on my side: {title[0].lower() + title[1:]}. I'll be in touch as soon as it's done.")
    else:
        paras.append("Let me know if anything has changed on your side, and I'll take it from there.")
    paras.append(f"Best,\n{broker_first or 'The Marrowby team'}")
    return subject, "\n\n".join(paras)


def _pipeline(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    done = chat.done("list_deals")
    if not done:
        mine = re.search(r"\bmy (?:pipeline|deals)\b", request, re.I) and chat.broker
        return [chat.call("list_deals", **({"owner": chat.broker} if mine else {}))]
    return [_text(pipeline_text(done[-1][1]))]


def pipeline_text(d: dict[str, Any]) -> str:
    stages = d["by_stage"]
    lines = [f"Pipeline as of {nice(d['as_of'])}: {d['open_deals']} open deals", "", "By stage"]
    lines += [f"- {s}: {stages[s]}" for s in crm_data.OPEN_STAGES]
    lines.append(f"- Closed won / Closed lost: {stages['Closed won']} / {stages['Closed lost']}")
    stale = [x for x in d["deals"] if x["stale"]]
    lines += ["", "Needs attention (no activity for 21+ days)"]
    lines += [f"- {x['name']} ({x['stage']}, {x['owner']}): {x['days_since_activity']} days. Suggested next step: a check in "
              f"call with {x['contact']}." for x in stale] or ["- Nothing stale this week."]
    moving = [x for x in d["deals"] if x["stage"] in crm_data.OPEN_STAGES and x["days_since_activity"] <= 7]
    if moving:
        lines += ["", "Moving"] + [f"- {x['name']} ({x['stage']}): last activity {x['days_since_activity']} days ago"
                                   for x in moving]
    return "\n".join(lines)


def _rules(chat: Chat, request: str, answer: str | None) -> list[dict[str, Any]]:
    if re.search(r"\btime|date|timestamp", request, re.I):
        return [_text("The CRM stamps every record with its own clock when it is saved (recorded_at). A time you give is kept "
                      "in your words, and stored as a date only when the words are exact, like \"Friday, October 23, 2026\". "
                      "\"Yesterday afternoon\" or \"next Tuesday\" stay as words and are flagged. Nothing is guessed.")]
    return [_text("The house rules: the CRM is the system of record; nothing is guessed; times follow the timestamp rule; "
                  "every write is read back and saved only after your explicit yes; an unclear name gets one short "
                  "question; client details stay private; email is drafts only.")]
