from __future__ import annotations

import argparse
import logging
from typing import Optional, Sequence

from .constants import YEAR_MENU_URL
from .scraper import Scraper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Baseball Almanac yearly stats.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to the first N yearly links (useful for testing). Example: --limit 5",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not prompt for a limit if --limit is not provided.",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Chrome headless (default: true).",
    )
    parser.add_argument(
        "--profile-dir",
        default="selenium_profile",
        help="Chrome user-data directory (default: selenium_profile).",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write CSV outputs (default: current directory).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO).",
    )
    parser.add_argument(
        "--league",
        choices=["AL", "NL", "BOTH"],
        default=None,
        help="Which league to scrape: AL, NL, or BOTH. If omitted and prompting is enabled, you'll be asked.",
    )
    return parser


def parse_limit_with_optional_prompt(*, limit: Optional[int], prompt: bool) -> Optional[int]:
    if limit is not None:
        return limit
    if not prompt:
        return None

    try:
        raw = input("How many years to scrape? (press Enter for all): ").strip()
        if not raw:
            return None
        return int(raw)
    except (EOFError, ValueError):
        return None


def parse_league_with_optional_prompt(*, league: Optional[str], prompt: bool) -> str:
    """
    Returns one of: 'AL', 'NL', 'BOTH'
    """
    if league is not None:
        return league

    if not prompt:
        return "BOTH"

    try:
        raw = input("Which league to scrape? [AL/NL/BOTH] (press Enter for BOTH): ").strip().upper()
    except EOFError:
        return "BOTH"

    if raw in {"", "BOTH", "B"}:
        return "BOTH"
    if raw in {"AL", "A"}:
        return "AL"
    if raw in {"NL", "N"}:
        return "NL"

    return "BOTH"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    limit = parse_limit_with_optional_prompt(limit=args.limit, prompt=not args.no_prompt)
    league = parse_league_with_optional_prompt(league=args.league, prompt=not args.no_prompt)

    scraper = Scraper(headless=args.headless, profile_dir=args.profile_dir)
    scraper.scrape(menu_url=YEAR_MENU_URL, limit_years=limit, out_dir=args.out_dir, league=league)
    return 0

