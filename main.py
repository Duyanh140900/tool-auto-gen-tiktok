#!/usr/bin/env python3
"""
main.py - Entry point.

Usage:
  # GUI (desktop app)
  python main.py

  # CLI: process URLs from file (one URL per line)
  python main.py --from-file inputs/urls.txt

  # CLI: inline URLs
  python main.py "https://tiktok.com/..." "https://tiktok.com/..."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from config import settings
from src.pipeline import ItemState, process_batch


def parse_args():
    p = argparse.ArgumentParser(description="TikTok Review Tool")
    p.add_argument("urls", nargs="*", help="TikTok URLs to process")
    p.add_argument("--from-file", type=Path, help="Read URLs from a text file (one per line)")
    p.add_argument("--hints", type=Path, help="Read product name hints (one per line, parallel to URLs)")
    p.add_argument("--scripts", type=Path, help="Read per-product scripts (one per line, parallel to URLs)")
    p.add_argument("--gui", action="store_true", help="Launch desktop GUI")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument(
        "--concurrent", "-c", type=int, default=1,
        help="Max items to process in parallel (1=sequential, safer for rate-limited TTS APIs)",
    )
    return p.parse_args()


def load_urls(args) -> tuple[list[str], list[str | None], list[str | None]]:
    urls: list[str] = []
    hints: list[str | None] = []
    scripts: list[str | None] = []

    if args.from_file:
        urls += [u.strip() for u in args.from_file.read_text(encoding="utf-8").splitlines() if u.strip()]
    if args.urls:
        urls += args.urls
    if args.hints:
        hints = [h.strip() if h.strip() else None for h in args.hints.read_text(encoding="utf-8").splitlines()]
    if args.scripts:
        scripts = [s.strip() if s.strip() else None for s in args.scripts.read_text(encoding="utf-8").splitlines()]

    # Pad to match urls length
    while len(hints) < len(urls):
        hints.append(None)
    while len(scripts) < len(urls):
        scripts.append(None)

    return urls, hints[:len(urls)], scripts[:len(urls)]


def run_cli(args):
    urls, hints, scripts = load_urls(args)
    if not urls:
        print("No URLs provided. Use --help for usage.")
        sys.exit(1)

    items = [
        ItemState(index=i + 1, url=u, product_name_hint=h, custom_script=s)
        for i, (u, h, s) in enumerate(zip(urls, hints, scripts))
    ]

    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if args.verbose else "INFO", colorize=True)

    async def _run():
        return await process_batch(items, max_concurrent=args.concurrent)

    results = asyncio.run(_run())

    # Summary
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    for r in results:
        status = "OK " if r.status == "done" else "ERR"
        out = r.final_video_path or r.error or "(no output)"
        print(f"  [{status}] #{r.index:02d} {r.product_name_hint or '?'}")
        print(f"        {out}")
    print()


def run_gui():
    from src.gui import main as gui_main
    gui_main()


def main():
    args = parse_args()
    if args.gui or (not args.urls and not args.from_file):
        run_gui()
    else:
        run_cli(args)


if __name__ == "__main__":
    main()