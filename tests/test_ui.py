"""The demo page in a real browser (an installed Chrome or Edge, through Playwright): the six step
story at desktop and phone sizes, with the thing each step asks you to tap fully visible and not
under the phone sheet, plus free chat, the read back card and a live (scripted) model. Skipped
when Playwright or a browser is not available."""
from __future__ import annotations

from typing import Any

import pytest
from conftest import ScriptedModel, free_port, serve, text, tool
from playwright.sync_api import expect

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


def settled(page, locator, timeout: float = 3.0) -> None:
    """fully_visible, polled: the page may still be scrolling a card into view or laying out a step."""
    import time
    expect(locator).to_be_in_viewport(ratio=1, timeout=timeout * 1000)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fully_visible(page, locator)
            return
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            page.wait_for_timeout(50)


def armed_confirm(page):
    """Confirm counts only once its card has been on screen for a moment (data-armed)."""
    confirm = page.locator("[data-confirm][data-armed='1']").first
    confirm.wait_for()
    return confirm


def words(locator) -> str:
    """An element's text as written, with spaces tidied. Labels are drawn in uppercase by the
    stylesheet, so inner_text() would read "SKILL USED"; the words themselves do not change."""
    return " ".join((locator.text_content() or "").split())


def no_sideways_scroll(page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth") <= page.viewport_size["width"]


def run_story(page, check) -> None:
    """The six steps, one action each. `check` sees each thing the visitor is asked to tap."""
    check(button(page, "Start the demo"))
    button(page, "Start the demo").click()
    check(button(page, "Send Priya's voice note"))
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn: check it, then confirm.").wait_for()
    confirm = armed_confirm(page)
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
    page.locator(".story-title", has_text="What you just saw").wait_for()
    check(button(page, "Try it yourself"))


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_the_story_at_every_size_with_each_action_in_view(browser, site, size):
    context, page, errors = open_page(browser, site, *size)

    def check(locator):
        settled(page, locator)
        no_sideways_scroll(page)

    run_story(page, check)
    context.close()
    assert errors == []


def test_what_each_step_shows(browser, site):
    context, page, errors = open_page(browser, site)
    assert "Nothing saves without their yes." in page.locator("#story").inner_text()
    assert page.evaluate("getComputedStyle(document.querySelector('.layout')).pointerEvents") == "none"
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    reply = page.locator(".bot").filter(has=page.locator(".skill")).last
    assert "Skill used: Voice note debrief" in words(reply.locator(".skill"))
    assert "voice-note-debrief" not in page.locator("#story").inner_text() + reply.inner_text()  # people names, not code names
    assert "Fixed rules" in words(reply.locator(".tag"))
    card = page.locator(".rb").first
    assert '"yesterday afternoon"' in card.inner_text() and "Vague, so no date set" in card.inner_text()
    assert "When you confirm" in card.inner_text() and "Due Fri, Oct" in card.inner_text()
    assert "Marcus Bell (Tessarine Biotech)" in card.inner_text() and "Tessarine Biotech at 310 Canal Street (Touring)" in card.inner_text()
    assert "Tasks (3), same contact and deal" in words(card.locator(".rb-side .rb-kind").first)
    assert "Summary" not in words(card.locator(".rows"))   # it is the card's title
    assert card.evaluate("c => !c.classList.contains('fit')")   # the whole card fits at 1440x900, nothing scrolls inside
    armed_confirm(page).click()
    page.locator(".story-title", has_text="Saved").wait_for()
    note = page.locator(".rec", has_text="Tour of 310 Canal Street").first
    assert "CRM clock" in words(note) and '"yesterday afternoon"' in note.inner_text()
    assert "Saved one note and three tasks" in note.inner_text() and words(note).count("CRM clock") == 1
    assert "The CRM's clock set the time; Priya's words sit beside it." in page.locator("#story").inner_text()
    button(page, "Next: try to skip the gate").click()
    page.locator(".story-title", has_text="Try to save without a yes.").wait_for()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="The gate held.").wait_for()
    assert "Saved without your confirm: 0" in page.locator("#story").inner_text()
    assert "still waits for Priya's confirm" in page.locator("#story").inner_text()
    gate_confirm = page.locator(".rb", has_text="Ravi").locator("[data-confirm]")
    assert "btn-secondary" in gate_confirm.get_attribute("class")  # the story is about what does not save
    assert "Refused" in words(page.locator(".event")) and page.locator(".event .stamp-refused").is_visible()
    assert "Refused" in words(page.locator("#activity"))
    button(page, "Next: two people called Dana").click()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="It asked").wait_for()
    assert "Changes prepared: 0" in page.locator("#story").inner_text()
    assert page.locator(".pipe-cell.here").count() == 0   # the newest reply has no card; Ravi's older one is not marked
    button(page, "Next: when no skill fits").click()
    button(page, "Ask about lunch").click()
    page.locator(".story-title", has_text="What you just saw").wait_for()
    assert "No skill used" in words(page.locator(".bot .skill").last)
    story = page.locator("#story").inner_text()
    assert "What you just saw." in story and "cost nothing" in story and "Cost shows when the live AI" in story  # fixed rules
    assert page.locator("#story .story-list li").count() == 3 and "Your version runs on your CRM" in story
    assert page.locator("#story .story-list .warn").count() == 0  # every claim held in this run
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
    assert page.locator(".trace[open]").count() == 0   # closed until opened
    settled(page, page.locator(".rb [data-confirm]"))   # the new card is scrolled into view
    tops = {round(c.bounding_box()["y"]) for c in page.locator(".chip").all() if c.is_visible()}
    assert len(tops) == 1   # once the chat has started, the chips are one scrolling row
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
    armed_confirm(page).click()
    page.locator(".story-title", has_text="Saved").wait_for()
    assert page.locator(".crm-pane").is_visible() and page.locator(".broker-pane").is_hidden()
    assert page.locator(".brand-sub").inner_text().strip() == "FICTIONAL DEMO"
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
        assert "Skill used: Weekly pipeline" in words(page.locator(".bot .skill").last)
        assert "AI cost of this chat: $0.0" in " ".join(page.locator("#cost-line").inner_text().split())
        context.close()
        assert errors == []
    finally:
        server.should_exit = True


@pytest.mark.parametrize("size", [(390, 664), (360, 640)], ids=["390x664", "360x640"])
def test_on_a_short_phone_step_two_shows_the_badge_the_card_and_confirm(browser, site, size):
    context, page, errors = open_page(browser, site, *size)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    page.wait_for_timeout(200)
    reply = page.locator(".bot").filter(has=page.locator(".rb")).last
    thread = page.locator("#thread").bounding_box()
    for part in (reply.locator(".skill"), reply.locator(".rb-head"), reply.locator("[data-confirm]")):
        fully_visible(page, part)
        assert part.bounding_box()["y"] >= thread["y"] - 1  # not scrolled away above the chat
    assert page.locator(".story-short").is_visible() and not page.locator("#story .story-text").is_visible()
    context.close()
    assert errors == []


def test_free_chat_on_a_phone_does_not_open_the_keyboard(browser, site):
    context, page, errors = open_page(browser, site, 390, 844)
    page.get_by_role("button", name="Skip to free chat").click()
    page.locator(".chip").first.wait_for()
    page.wait_for_timeout(200)
    assert page.evaluate("document.activeElement.id") != "input"
    context.close()
    assert errors == []


def test_chips_wrap_on_desktop_and_loi_comes_second(browser, site):
    context, page, errors = open_page(browser, site)
    page.get_by_role("button", name="Skip to free chat").click()
    chips = page.locator(".chip")
    chips.first.wait_for()
    assert chips.nth(1).inner_text().strip() == "What does LOI mean?"
    tops = {round(chips.nth(i).bounding_box()["y"]) for i in range(chips.count())}
    assert len(tops) > 1  # more than one row: the chips wrap
    assert page.evaluate("(row => row.scrollWidth <= row.clientWidth + 1)(document.querySelector('.suggest'))")
    context.close()
    assert errors == []


def test_a_badge_with_several_skills_wraps_instead_of_overflowing(browser):
    live = ScriptedModel([tool(1, "load_skill", name="house-rules"), tool(2, "load_skill", name="voice-note-debrief"),
                          tool(3, "load_skill", name="meeting-prep"), tool(4, "load_skill", name="weekly-pipeline")],
                         [text("Done.")])
    url, server = start_server(Agent(live=live))
    try:
        context, page, errors = open_page(browser, url, 360, 640)
        page.get_by_role("button", name="Skip to free chat").click()
        page.locator("#input").fill("Prep me and sum up the week.")
        page.locator("#input").press("Enter")
        badge = page.locator(".bot .skill").last
        badge.wait_for()
        assert "Skills used: Voice note debrief, Meeting prep, Weekly pipeline" in words(badge)
        box, head = badge.bounding_box(), page.locator(".bot .bot-head").last.bounding_box()
        assert box["x"] + box["width"] <= head["x"] + head["width"] + 1 and box["x"] + box["width"] <= 360
        no_sideways_scroll(page)
        context.close()
        assert errors == []
    finally:
        server.should_exit = True


def test_the_first_screen_is_a_drawing_waiting_for_a_yes(browser, site):
    context, page, errors = open_page(browser, site)
    figure = page.locator(".hero-fig")
    assert figure.is_visible() and figure.locator("svg.plan").get_attribute("aria-hidden") == "true"
    assert "yesterday afternoon" in words(figure.locator(".fig-quote"))
    stamp = figure.locator(".tb .stamp-saved")
    expect(stamp).to_have_text("Approved · Priya", timeout=4000)   # about 1.8 s in, the drawing gets its yes
    assert page.evaluate("getComputedStyle(document.querySelector('.fp-tag.fp-worried')).fill") != \
        page.evaluate("getComputedStyle(document.querySelector('.fp-tag:not(.fp-worried)')).fill")
    assert [" ".join(li.inner_text().split()) for li in page.locator(".hero-points li").all()] == [
        "01 Voice note in, CRM note and tasks out", "02 A read back before every write", "03 Times are never guessed"]
    assert page.locator(".layout").is_hidden()
    page.wait_for_timeout(2000)  # the callout leaders draw in, then stay drawn
    assert page.evaluate("getComputedStyle(document.querySelector('.fp-lead')).strokeDashoffset") in ("0", "0px")
    context.close()
    assert errors == []


def test_the_pipeline_strip_counts_the_crm_and_marks_the_card(browser, site):
    context, page, errors = open_page(browser, site)
    cells = page.locator(".pipe-cell")
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert [c.locator(".pipe-k").inner_text().strip() + " " + words(c.locator("b")) for c in cells.all()] == [
        "LEAD 1", "TOURING 2", "PROPOSAL 1", "LOI 1", "NEGOTIATION 1"]  # open deals in crm/data.py, as shown
    assert cells.nth(1).get_attribute("class").split() == ["pipe-cell", "here"]  # Tessarine at 310 Canal is touring
    assert page.locator(".pipe-cell.here").count() == 1
    context.close()
    assert errors == []


def test_a_confirm_stamps_the_card_and_the_record(browser, site):
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert page.locator("#thread .stamp").count() == 0  # nothing is stamped before the yes
    armed_confirm(page).click()
    page.locator(".story-title", has_text="Saved, with").wait_for()
    card_stamp = page.locator(".rb .stamp-saved")
    assert card_stamp.count() == 1 and words(card_stamp).startswith("Saved · ")
    assert words(page.locator(".rb .tb-approve > span").first) == "Approved by"
    assert words(page.locator(".rb .tb-approve b")) == "Priya Natarajan"
    assert words(page.locator(".rec .stamp-saved")) == words(card_stamp)  # the same CRM clock time on both
    context.close()
    assert errors == []


def test_motion_is_off_when_the_visitor_asks_for_less(browser, site):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    page.goto(site + "/")
    page.locator(".hero-fig").wait_for()
    assert page.evaluate("getComputedStyle(document.querySelector('.fp-lead')).animationName") == "none"
    assert page.evaluate("getComputedStyle(document.querySelector('.fp-lead')).strokeDashoffset") in ("0", "0px")
    page.wait_for_timeout(2400)
    assert "Waiting for Priya" in words(page.locator(".hero-fig .tb")) and page.locator(".hero-fig .stamp").count() == 0
    context.close()


def test_dark_mode_is_blueprint_at_night(browser, site):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page = context.new_page()
    page.goto(site + "/")
    page.locator(".hero-fig").wait_for()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(11, 22, 40)"
    assert page.evaluate("getComputedStyle(document.querySelector('.story-headline')).color") == "rgb(231, 238, 248)"
    context.close()



def test_a_card_is_read_before_it_can_be_saved(browser, site):
    """S1: keyboard focus lands on the card's heading, a press on Confirm in the first moment does
    nothing, and a held Enter does not repeat into a save."""
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    send = button(page, "Send Priya's voice note")
    send.focus()
    page.keyboard.press("Enter")
    page.locator(".story-title", has_text="Your turn").wait_for()
    confirm = page.locator("[data-confirm]").first
    assert confirm.get_attribute("data-armed") == "0"
    confirm.evaluate("b => b.click()")                         # too soon: ignored
    expect(page.locator(".rb-sum").first).to_be_focused(timeout=2000)   # focus is on the heading, not on Confirm
    page.keyboard.press("Enter")                              # a second Enter saves nothing
    page.wait_for_timeout(300)
    assert page.evaluate("document.querySelectorAll('#panel .rec.is-saved').length") == 0
    held = page.evaluate("""() => { const b = document.querySelector('[data-confirm]'); b.focus();
        const e = new KeyboardEvent('keydown', {key: 'Enter', repeat: true, bubbles: true, cancelable: true});
        b.dispatchEvent(e); return e.defaultPrevented; }""")
    assert held is True
    armed_confirm(page).click()                               # a real press, after a moment, saves
    page.locator(".story-title", has_text="Saved, with").wait_for()
    context.close()
    assert errors == []


def test_the_story_band_keeps_its_button_in_one_place(browser, site):
    context, page, errors = open_page(browser, site, 1280, 720)
    spots = []
    button(page, "Start the demo").click()
    spots.append(button(page, "Send Priya's voice note").bounding_box())
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert page.locator(".rb.ring-card").evaluate("c => !c.classList.contains('fit')")   # the whole card fits at 1280x720
    settled(page, page.locator(".rb.ring-card .rb-sum"))
    armed_confirm(page).click()
    spots.append(button(page, "Next: try to skip the gate").bounding_box())
    button(page, "Next: try to skip the gate").click()
    button(page, "Send it").click()
    page.locator(".story-title", has_text="The gate held.").wait_for()
    spots.append(button(page, "Next: two people called Dana").bounding_box())
    assert len({round(s["x"]) for s in spots}) == 1 and len({round(s["y"]) for s in spots}) == 1
    context.close()
    assert errors == []


@pytest.mark.parametrize("size", [(1440, 900), (1280, 720)], ids=["1440x900", "1280x720"])
def test_a_long_live_reply_does_not_push_the_card_away(browser, size):
    """A model that writes the whole read back out again in prose: the page shows two lines of it
    with a toggle, and the whole card, Confirm included, stays in view at step 2."""
    prose = "\n".join(["Here is the debrief I prepared for Marcus Bell at Tessarine Biotech."] +
                      [f"- Discussed point {i}: the lab benches, the loading dock and the HVAC" for i in range(1, 9)] +
                      ["Press Confirm on the card to save, or tell me what to change."])
    changes = [{"op": "create_note", "contact_id": "C-5", "deal_id": "D-3", "property_id": "P-5",
                "summary": "Tour of 310 Canal Street with Marcus Bell", "discussed": ["Liked the loading dock"],
                "stated_time_text": "yesterday afternoon"},
               {"op": "create_task", "title": "Send Marcus the HVAC specs", "contact_id": "C-5", "deal_id": "D-3"}]
    live = ScriptedModel([tool(1, "load_skill", name="house-rules"), tool(2, "load_skill", name="voice-note-debrief")],
                         [tool(3, "propose_write", summary="Tour of 310 Canal Street with Marcus Bell", changes=changes)],
                         [text(prose)])
    url, server = start_server(Agent(live=live))
    try:
        context, page, errors = open_page(browser, url, *size)
        button(page, "Start the demo").click()
        button(page, "Send Priya's voice note").click()
        page.locator(".story-title", has_text="Your turn").wait_for(timeout=15000)
        card = page.locator(".rb.ring-card")
        settled(page, card.locator(".rb-head"))
        settled(page, armed_confirm(page))
        assert card.evaluate("c => !c.classList.contains('fit')")   # nothing scrolls inside the card either
        toggle = page.get_by_role("button", name="Show Claude's full message")
        assert toggle.is_visible() and toggle.get_attribute("aria-expanded") == "false"
        answer = page.locator(".answer.clamp")
        assert answer.evaluate("a => a.scrollHeight > a.clientHeight + 4")   # clamped to two lines
        toggle.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_role("button", name="Show less")).to_have_attribute("aria-expanded", "true")
        assert answer.evaluate("a => a.scrollHeight <= a.clientHeight + 1") and "Discussed point 8" in answer.inner_text()
        context.close()
        assert errors == []
    finally:
        server.should_exit = True


def test_a_short_reply_with_a_card_has_no_toggle(browser, site):
    context, page, errors = open_page(browser, site)
    button(page, "Start the demo").click()
    button(page, "Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for()
    assert page.locator(".more-toggle").first.is_hidden()   # the fixed rules' two lines need no toggle
    context.close()
    assert errors == []
