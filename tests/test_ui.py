"""The demo page in a real browser (an installed Chrome or Edge, through Playwright): the six step
story at desktop and phone sizes, with the thing each step asks you to tap fully visible and not
under the phone sheet, plus free chat, the read back card and a live (scripted) model. Skipped
when Playwright or a browser is not available."""
from __future__ import annotations

from typing import Any

import pytest
from conftest import ScriptedModel, free_port, serve, text, tool

from teamos.agent import Agent
from teamos.web import create_app

SIZES = [(1440, 900), (1280, 720), (390, 844), (390, 664), (360, 640)]


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        for channel in ("chrome", "msedge"):
            try:
                launched = p.chromium.launch(channel=channel)
                break
            except Exception:
                continue
        else:
            pytest.skip("no installed Chrome or Edge for Playwright")
        yield launched
        launched.close()


def start_server(agent: Agent) -> tuple[str, Any]:
    port = free_port()
    return f"http://127.0.0.1:{port}", serve(create_app(agent), port)


@pytest.fixture(scope="module")
def site():
    url, server = start_server(Agent())
    yield url
    server.should_exit = True


def open_page(browser, url, width=1440, height=900):
    mobile = width < 900
    context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=mobile, has_touch=mobile)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(url + "/")
    page.get_by_role("button", name="Start the demo").wait_for()
    return context, page, errors


def button(page, name):
    return page.get_by_role("button", name=name, exact=True)


def fully_visible(page, locator) -> None:
    """Inside the window, and above the phone's story sheet when there is one."""
    box = locator.bounding_box()
    assert box, "not on screen"
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    bottom = height
    sheet = page.locator("#story")
    if width < 900 and sheet.evaluate("el => getComputedStyle(el).position") == "fixed" and \
            not sheet.evaluate("(el, target) => el.contains(target)", locator.element_handle()):
        bottom = sheet.bounding_box()["y"]
    assert box["y"] >= 0 and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, box
    assert box["y"] + box["height"] <= bottom + 1, (box, bottom)


def no_sideways_scroll(page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth") <= page.viewport_size["width"]


def run_story(page, check) -> None:
    """The six steps, one action each. `check` sees each thing the visitor is asked to tap."""
    check(button(page, "Start the demo"))
    button(page, "Start the demo").click()
    check(button(page, "Send Priya's voice note"))
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn: check it, then confirm.").wait_for()
    confirm = page.locator("[data-confirm]").first
    page.wait_for_timeout(150)
    check(confirm)
    confirm.click()
    page.locator(".story-title", has_text="Saved, with the CRM's own time.").wait_for()
    check(button(page, "Next: try to skip the gate"))
    button(page, "Next: try to skip the gate").click()
    check(button(page, "Send it"))
    button(page, "Send it").click()
    page.locator(".story-title", has_text="The gate held.").wait_for()
    check(button(page, "Next: two people called Dana"))
    button(page, "Next: two people called Dana").click()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="It asked instead of guessing.").wait_for()
    check(button(page, "Next: when no skill fits"))
    button(page, "Next: when no skill fits").click()
    check(button(page, "Ask about lunch"))
    button(page, "Ask about lunch").click()
    page.locator(".story-title", has_text="No skill used.").wait_for()
    check(button(page, "Try it yourself"))


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_the_story_at_every_size_with_each_action_in_view(browser, site, size):
    context, page, errors = open_page(browser, site, *size)

    def check(locator):
        page.wait_for_timeout(120)
        fully_visible(page, locator)
        no_sideways_scroll(page)

    run_story(page, check)
    context.close()
    assert errors == []


def test_what_each_step_shows(browser, site):
    context, page, errors = open_page(browser, site)
    assert "Nothing reaches the CRM without a yes." in page.locator("#story").inner_text()
    assert page.evaluate("getComputedStyle(document.querySelector('.layout')).pointerEvents") == "none"
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    reply = page.locator(".bot").filter(has=page.locator(".skill")).last
    assert "Skill used: voice-note-debrief" in " ".join(reply.locator(".skill").inner_text().split())
    assert "Fixed rules" in reply.locator(".tag").inner_text()
    card = page.locator(".rb").first
    assert '"yesterday afternoon"' in card.inner_text() and "Vague, so no date set" in card.inner_text()
    assert "When you confirm" in card.inner_text() and "Due Fri, Oct" in card.inner_text()
    page.locator("[data-confirm]").first.click()
    page.locator(".story-title", has_text="Saved").wait_for()
    note = page.locator(".rec", has_text="Tour of 310 Canal Street").first
    assert "Recorded at (CRM clock)" in note.inner_text() and '"yesterday afternoon"' in note.inner_text()
    button(page, "Next: try to skip the gate").click()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="The gate held.").wait_for()
    assert "Saved without your confirm: 0" in page.locator("#story").inner_text()
    assert "Refused" in page.locator(".event").inner_text()
    assert "Refused" in page.locator("#activity").inner_text()
    button(page, "Next: two people called Dana").click()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="It asked").wait_for()
    assert "Changes prepared: 0" in page.locator("#story").inner_text()
    button(page, "Next: when no skill fits").click()
    button(page, "Ask about lunch").click()
    page.locator(".story-title", has_text="No skill used").wait_for()
    assert "No skill used" in page.locator(".bot .skill").last.inner_text()
    assert "cost nothing" in page.locator("#story").inner_text()
    assert page.locator(".story-skills li.used").count() == 3
    button(page, "Try it yourself").click()
    page.locator(".story-title", has_text="Ask what a broker would ask").wait_for()
    assert page.locator(".chip").count() >= 8 and page.locator(".chip-near").count() >= 3
    assert page.locator("#input").input_value() == ""
    context.close()
    assert errors == []


def test_no_jargon_outside_under_the_hood(browser, site):
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    visible = page.evaluate("document.body.innerText").lower()
    for word in ("token", "tool call", "guided", "payload", "hash", "write_id", "w-1", "n-6", "c-5", "json"):
        assert word not in visible, word
    context.close()


def test_discarding_the_read_back_saves_nothing_and_the_story_offers_it_again(browser, site):
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    page.locator("[data-discard]").first.click()
    page.locator(".story-title", has_text="You discarded it").wait_for()
    assert "Discarded" in page.locator(".rb").inner_text() and page.locator(".rec").count() == 0
    button(page, "Send it again").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    context.close()
    assert errors == []


def test_the_page_keeps_its_place_after_a_reload(browser, site):
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    page.reload()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert page.locator("[data-confirm]").count() == 1
    context.close()


def test_free_chat_near_miss_and_discard(browser, site):
    context, page, errors = open_page(browser, site)
    page.get_by_role("button", name="Skip to free chat").click()
    page.get_by_role("button", name="What does LOI mean?").click()
    page.locator(".bot .skill", has_text="No skill used").wait_for()
    page.get_by_role("button", name="Debrief a coffee with Hana").click()
    page.locator(".rb").wait_for()
    assert '"next Tuesday": kept as words' in page.locator(".rb").inner_text()
    page.locator("[data-discard]").click()
    page.locator(".rb .pill", has_text="Discarded").wait_for()
    page.select_option("#broker-pick", "B-3")
    page.locator("#chat-status", has_text="Jordan Avery").wait_for()
    context.close()
    assert errors == []


def test_on_a_phone_the_story_switches_panes(browser, site):
    context, page, errors = open_page(browser, site, 390, 844)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert page.locator(".broker-pane").is_visible() and page.locator(".crm-pane").is_hidden()
    page.locator("[data-confirm]").first.click()
    page.locator(".story-title", has_text="Saved").wait_for()
    assert page.locator(".crm-pane").is_visible() and page.locator(".broker-pane").is_hidden()
    fully_visible(page, page.locator(".rec").first.locator(".time-box").first)
    page.locator(".switch-row button", has_text="Broker").click()
    assert page.locator(".broker-pane").is_visible()
    targets = page.evaluate("[...document.querySelectorAll('.switch-row button, #story-actions button')]"
                            ".map(b => b.getBoundingClientRect().height)")
    assert min(targets) >= 44  # touch targets
    context.close()
    assert errors == []


def test_with_a_live_model_the_reply_is_marked_ai_and_the_crm_shows_the_cost(browser):
    live = ScriptedModel([tool(1, "load_skill", name="house-rules"), tool(2, "load_skill", name="weekly-pipeline")],
                         [tool(3, "list_deals")], [text("6 open deals. Two are stale.")])
    url, server = start_server(Agent(live=live))
    try:
        context, page, errors = open_page(browser, url)
        page.get_by_role("button", name="Skip to free chat").click()
        page.locator("#input").fill("Give me the weekly pipeline summary.")
        page.locator("#input").press("Enter")
        page.locator(".bot .tag", has_text="AI").wait_for()
        assert "Skill used: weekly-pipeline" in " ".join(page.locator(".bot .skill").last.inner_text().split())
        assert "AI cost of this chat: $0.0" in " ".join(page.locator("#cost-line").inner_text().split())
        context.close()
        assert errors == []
    finally:
        server.should_exit = True
