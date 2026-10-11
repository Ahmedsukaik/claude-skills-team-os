"""Run the demo on this computer:  python demo.py   (then open http://127.0.0.1:8310)

Without ANTHROPIC_API_KEY the fixed rules answer (no AI, no cost). With a key in the
environment or in a .env file, replies come from Claude; set TEAMOS_LIVE_AI=off to compare.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from .env. Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude skills team OS demo")
    parser.add_argument("--port", type=int, default=8310)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    load_env()
    import uvicorn

    from teamos.web import create_app
    app = create_app()
    live = app.state.agent.live
    mode = f"live AI ({live.name})" if live else "fixed rules (no API key)"
    print(f"Team assistant demo on http://{args.host}:{args.port}  -  replies from {mode}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
