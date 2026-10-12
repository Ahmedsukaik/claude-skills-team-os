"""Record the demo story and the README images.

    python docs/make_media.py                         starts the demo in this process (fixed rules
                                                      unless ANTHROPIC_API_KEY is set) and stops it
    python docs/make_media.py https://your-demo.vercel.app       records the tour from a deployed demo
    python docs/make_media.py --url https://your-demo.vercel.app (the same)

Needs Playwright with an installed Chrome or Edge, and ffmpeg on the PATH for the GIF.
Writes docs/img/tour.gif, docs/img/tour.mp4 and docs/img/screen-*.png.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, ViewportSize, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "img"
SIZE: ViewportSize = {"width": 1440, "height": 900}
PHONE: ViewportSize = {"width": 390, "height": 844}


def local_demo() -> tuple[str, Any]:
    """The demo app in a background thread of this process, on a free port."""
    sys.path.insert(0, str(ROOT))
    import uvicorn

    from demo import load_env
    load_env(ROOT / ".env")
    from teamos.web import create_app
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


def story(page: Page, shots: bool, pause: int = 1) -> None:
    def click(name: str) -> None:
        page.get_by_role("button", name=name, exact=True).click()

    def shot(name: str) -> None:
        if shots:
            page.screenshot(path=str(OUT / f"screen-{name}.png"))

    page.get_by_role("button", name="Start the demo").wait_for()
    page.wait_for_timeout(2200 * pause)
    shot("intro")
    click("Start the demo")
    page.wait_for_timeout(1500 * pause)
    page.get_by_role("button", name="Send Priya's voice note").click()
    page.locator(".story-title", has_text="Your turn").wait_for(timeout=120000)
    page.wait_for_timeout(3200 * pause)
    shot("readback")
    page.locator("[data-confirm][data-armed='1']").first.click()   # Confirm counts once the card has been read
    page.locator(".story-title", has_text="Saved, with").wait_for()
    page.wait_for_timeout(3500 * pause)
    shot("saved")
    click("Next: try to skip the gate")
    page.wait_for_timeout(1500 * pause)
    click("Send it")
    page.get_by_role("button", name="Next: two people called Dana").wait_for(timeout=120000)
    page.wait_for_timeout(3500 * pause)
    shot("gate")
    click("Next: two people called Dana")
    page.wait_for_timeout(1300 * pause)
    click("Send it")
    page.get_by_role("button", name="Next: when no skill fits").wait_for(timeout=120000)
    page.wait_for_timeout(3000 * pause)
    shot("ambiguity")
    click("Next: when no skill fits")
    page.wait_for_timeout(1300 * pause)
    click("Ask about lunch")
    page.get_by_role("button", name="Try it yourself").wait_for(timeout=120000)
    page.wait_for_timeout(3800 * pause)
    shot("cost")


def main(url: str | None) -> None:
    OUT.mkdir(exist_ok=True)
    server = None
    if not url:
        url, server = local_demo()
        print(f"demo running in this process on {url}")
    tmp = tempfile.mkdtemp()  # left for the system to clean: Windows can keep the video file open for a moment
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            context = browser.new_context(viewport=SIZE, device_scale_factor=1, record_video_dir=tmp, record_video_size=SIZE)
            page = context.new_page()
            page.goto(url + "/")
            story(page, shots=True)
            video = page.video.path() if page.video else None
            context.close()
            phone = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
            page = phone.new_page()
            page.goto(url + "/")
            page.get_by_role("button", name="Start the demo").click()
            page.get_by_role("button", name="Send Priya's voice note").click()
            page.locator(".story-title", has_text="Your turn").wait_for(timeout=120000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "screen-phone.png"))
            phone.close()
            browser.close()
    finally:
        if server is not None:
            server.should_exit = True
    if video:
        webm = Path(tmp) / "tour.webm"
        shutil.copy(video, webm)
        mp4 = OUT / "tour.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "23", "-movflags", "+faststart", str(mp4)], check=True)
        palette = Path(tmp) / "palette.png"
        scale = "fps=5,scale=860:-1:flags=lanczos"  # flat UI colours: a small palette, no dithering, only changed areas
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                        f"{scale},palettegen=max_colors=64:stats_mode=diff", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-i", str(palette), "-lavfi",
                        f"{scale} [x]; [x][1:v] paletteuse=dither=none:diff_mode=rectangle", str(OUT / "tour.gif")], check=True)
    print("written:", ", ".join(sorted(f.name for f in OUT.iterdir())))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Record the demo story and the README images.")
    parser.add_argument("base", nargs="?", help="a deployed demo's address; without it, a local demo with the fixed rules")
    parser.add_argument("--url", help="the same as the positional address")
    args = parser.parse_args()
    address = args.url or args.base
    main(address.rstrip("/") if address else None)
