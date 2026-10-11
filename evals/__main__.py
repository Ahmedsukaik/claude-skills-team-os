"""Run the evaluation and report what passed.

    python -m evals                 the fixed rules, locally (no AI, no cost)
    python -m evals --live          Claude, locally (needs ANTHROPIC_API_KEY in the environment or .env)
    python -m evals --url URL       through a deployed demo's HTTP API, whatever it runs, 45 seconds
                                    between chats so the demo's per visitor limits are not hit (a full
                                    run is 60 chats: about an hour)

Three kinds of cases:
- triggering.jsonl: about 40 requests, each labelled with the skill that must load, or none. A
  task skill must load with house-rules and without any other task skill; "none" means no skill
  loads and the CRM is not touched (the near misses).
- behaviour.jsonl: the gate holds (nothing saved without the Confirm button, even after "just
  write it" or a typed yes), the timestamp rule (vague times kept as words), duplicates blocked,
  ambiguity asked about, drafts never sent, read only skills write nothing.
- consistency.jsonl: the same voice note sent by three different brokers gives the same
  structured fields. The proposed write payloads are compared, not the prose.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
TASK_SKILLS = ("voice-note-debrief", "crm-update", "meeting-prep", "follow-up-email", "weekly-pipeline")


def load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]


class LocalRunner:
    def __init__(self, live: bool):
        from teamos.agent import Agent
        from teamos.models import ClaudeModel
        self.mode = "live" if live else "guided"
        self.agent = Agent(live=ClaudeModel() if live else None)

    def chat(self, messages: list[str], broker: str = "B-1") -> dict[str, Any]:
        from teamos.session import new_session
        session = new_session(broker)
        out: dict[str, Any] = {}
        for message in messages:
            out = self.agent.handle(session, {"type": "broker", "text": message}, want_live=self.mode == "live")
            session = out["session"]
            while out["more"]:
                out = self.agent.handle(session, {"type": "continue"}, want_live=self.mode == "live")
                session = out["session"]
        return out["view"]


class HttpRunner:
    def __init__(self, url: str):
        import httpx
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=90)
        self.mode = "live" if self.http.get(self.url + "/api/config").json().get("live") else "guided"

    def chat(self, messages: list[str], broker: str = "B-1") -> dict[str, Any]:
        out = self.http.post(self.url + "/api/new", json={"broker": broker}).json()
        for message in messages:
            out = self._step(out["session"], {"type": "broker", "text": message})
            while out["more"]:
                out = self._step(out["session"], {"type": "continue"})
        return out["view"]

    def _step(self, session: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        res = self.http.post(self.url + "/api/step", json={"session": session, "action": action, "live": True})
        res.raise_for_status()
        return res.json()


# ---------------------------------------------------------------------------- judging
def replies(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in view["transcript"] if t["kind"] == "assistant"]


def skills_loaded(view: dict[str, Any]) -> set[str]:
    return {s for r in replies(view) for s in r.get("skills", [])}


def common(view: dict[str, Any], mode: str) -> list[str]:
    problems = []
    if not replies(view):
        problems.append("no reply")
    if mode == "live" and any(r["mode"] != "live" for r in replies(view)):
        problems.append("a reply came from the fixed rules, not the live model")
    return problems


def judge_trigger(case: dict[str, Any], view: dict[str, Any], mode: str) -> list[str]:
    problems = common(view, mode)
    loaded = skills_loaded(view)
    want = case["skill"]
    if want is None:
        if loaded:
            problems.append(f"loaded {', '.join(sorted(loaded))} but no skill should load")
        used = [s["tool"] for r in replies(view) for s in r["steps"]]
        if used:
            problems.append(f"used the CRM ({', '.join(used)}) for a question that needs no skill")
        return problems
    if want not in loaded:
        problems.append(f"{want} did not load (loaded: {', '.join(sorted(loaded)) or 'none'})")
    if want != "house-rules" and "house-rules" not in loaded:
        problems.append("house-rules did not load with the task skill")
    others = sorted(s for s in loaded if s in TASK_SKILLS and s != want)
    if others:
        problems.append(f"also loaded {', '.join(others)}")
    return problems


def judge_behaviour(case: dict[str, Any], view: dict[str, Any], mode: str) -> list[str]:
    problems = common(view, mode)
    expect = case["expect"]
    final = replies(view)[-1]["text"].lower() if replies(view) else ""
    metrics = view["metrics"]
    if "pending_min" in expect and len(view["pending"]) < expect["pending_min"]:
        problems.append(f"expected a change waiting for a confirm (got {len(view['pending'])})")
    if "saved" in expect and metrics["writes_saved"] != expect["saved"]:
        problems.append(f"{metrics['writes_saved']} writes were saved, expected {expect['saved']}")
    if expect.get("no_write") and metrics["writes_proposed"]:
        problems.append(f"{metrics['writes_proposed']} writes were proposed, expected none")
    if "drafts" in expect:
        drafts = view["drafts"]
        if len(drafts) != expect["drafts"] or any(d["status"] != "draft" for d in drafts):
            problems.append(f"expected {expect['drafts']} unsent draft(s), got {[d['status'] for d in drafts]}")
    if expect.get("skill") and expect["skill"] not in skills_loaded(view):
        problems.append(f"{expect['skill']} did not load")
    if expect.get("reply_any") and not any(s.lower() in final for s in expect["reply_any"]):
        problems.append(f"the last reply mentions none of: {', '.join(expect['reply_any'])}")
    for s in expect.get("reply_all", []):
        if s.lower() not in final:
            problems.append(f"the last reply does not mention {s!r}")
    changes = [c for w in view["pending"] for c in w["changes"]]
    for want in expect.get("times", []):
        key = "due" if want["op"] == "create_task" else "stated_time"
        found = [c for c in changes if c["op"] == want["op"] and (c.get(f"{key}_text") or "").lower() == (want["text"] or "").lower()
                 and c.get(key) == want["value"]]
        if not found:
            got = [(c["op"], c.get(f"{key}_text"), c.get(key)) for c in changes if c["op"] == want["op"]]
            problems.append(f"no {want['op']} with time {want['text']!r} -> {want['value']!r} (got {got})")
    if expect.get("change"):
        want = expect["change"]
        if not any(all(c.get(k) == v for k, v in want.items()) for c in changes):
            problems.append(f"no pending change matching {want}")
    return problems


STRUCTURED = ("op", "contact_id", "company_id", "deal_id", "property_id", "stated_time", "due", "stage")


def structured(view: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The fields of a proposed write that must not depend on who asked or how it was worded."""
    out = []
    for w in view["pending"]:
        for c in w["changes"]:
            words = (c.get("stated_time_text") or c.get("due_text") or "").lower()
            out.append(tuple(c.get(k) for k in STRUCTURED) + (words,))
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def judge_consistency(case: dict[str, Any], views: list[dict[str, Any]], mode: str) -> list[str]:
    problems = [p for v in views for p in common(v, mode)]
    shapes = [structured(v) for v in views]
    if not shapes[0]:
        problems.append("no write was proposed for the first broker")
    for broker, shape in zip(case["brokers"][1:], shapes[1:], strict=True):
        if shape != shapes[0]:
            problems.append(f"{broker} got different fields: {shape} vs {shapes[0]}")
    return problems


# ---------------------------------------------------------------------------- running
def run(runner: LocalRunner | HttpRunner, pause: float, only: set[str] | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    first = True

    def wait() -> None:
        nonlocal first
        if not first and pause:
            time.sleep(pause)
        first = False

    def record(kind: str, case: dict[str, Any], fn: Any) -> None:
        if only and case["id"] not in only:
            return
        wait()
        try:
            problems, cost = fn()
        except Exception as e:  # a failed request is a failed case, not a crash
            problems, cost = [f"error: {type(e).__name__}: {e}"], 0.0
        status = "pass" if not problems else "FAIL"
        results.append({"kind": kind, "id": case["id"], "status": status, "problems": problems, "cost_usd": cost})
        print(f"  {status}  {kind:<12} {case['id']}" + "".join(f"\n          - {p}" for p in problems))

    for case in load("triggering.jsonl"):
        def trig(case: dict[str, Any] = case) -> tuple[list[str], float]:
            view = runner.chat([case["say"]])
            return judge_trigger(case, view, runner.mode), view["metrics"]["cost_usd"]
        record("triggering", case, trig)
    for case in load("behaviour.jsonl"):
        def behave(case: dict[str, Any] = case) -> tuple[list[str], float]:
            view = runner.chat(case["say"])
            return judge_behaviour(case, view, runner.mode), view["metrics"]["cost_usd"]
        record("behaviour", case, behave)
    for case in load("consistency.jsonl"):
        def consist(case: dict[str, Any] = case) -> tuple[list[str], float]:
            views = []
            for i, broker in enumerate(case["brokers"]):
                if i and pause:
                    time.sleep(pause)  # each broker's chat is its own chat for the limits too
                views.append(runner.chat([case["say"]], broker))
            return judge_consistency(case, views, runner.mode), sum(v["metrics"]["cost_usd"] for v in views)
        record("consistency", case, consist)
    summary = {kind: {"passed": sum(r["status"] == "pass" for r in results if r["kind"] == kind),
                      "ran": sum(r["kind"] == kind for r in results)} for kind in ("triggering", "behaviour", "consistency")}
    return {"mode": runner.mode, "date": date.today().isoformat(), "summary": summary,
            "cost_usd": round(sum(r["cost_usd"] for r in results), 5), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the skills evaluation")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--live", action="store_true", help="use Claude locally (needs ANTHROPIC_API_KEY)")
    target.add_argument("--url", help="run through a deployed demo, e.g. https://example.vercel.app")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--pause", type=float, default=None, help="seconds between chats (default 0, or 45 with --url)")
    parser.add_argument("--save", action="store_true", help="write the results to evals/results/")
    args = parser.parse_args()
    if args.live:
        from demo import load_env
        load_env(ROOT / ".env")
    runner: LocalRunner | HttpRunner = HttpRunner(args.url) if args.url else LocalRunner(args.live)
    pause = args.pause if args.pause is not None else (45.0 if args.url else 0.0)
    print(f"Running the evaluation ({'fixed rules' if runner.mode == 'guided' else 'live AI'})\n")
    out = run(runner, pause, set(args.only.split(",")) if args.only else None)
    print()
    for kind, s in out["summary"].items():
        print(f"{kind:<12} {s['passed']}/{s['ran']} passed")
    if out["cost_usd"]:
        print(f"cost ${out['cost_usd']:.4f}")
    if args.save:
        path = HERE / "results" / f"{out['date']}-{runner.mode}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"saved {path.relative_to(ROOT)}")
    return 0 if all(s["passed"] == s["ran"] for s in out["summary"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
