"""
Siliv – Command-line Interface
Run with:
    python -m siliv.cli status
    python -m siliv.cli set 8192        # 8 GB in MB
    python -m siliv.cli set 8G          # 8 GB shorthand
    python -m siliv.cli default
"""
from __future__ import annotations

import argparse
import sys
import re
from typing import Tuple

from siliv import utils


def _parse_size(text: str) -> int:
    """
    Parse a size string to MB.
        8192      -> 8192 MB
        8G / 8g   -> 8192 MB
        8GB / 8gb -> 8192 MB
    """
    txt = text.strip()
    m = re.fullmatch(r"(\d+)([gG][bB]?|)", txt)
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid size value '{text}'")
    value = int(m.group(1))
    if m.group(2):  # has G suffix
        return value * 1024
    return value


# --------------------------------------------------------------------------- #
# helper printers
# --------------------------------------------------------------------------- #
def _format_mb(mb: int) -> str:
    return f"{mb / 1024:.1f} GB ({mb} MB)"


def status_cmd(_: argparse.Namespace) -> None:
    """Display total RAM, current VRAM, default VRAM and reserved RAM."""
    total_mb = utils.get_total_ram_mb() or 0
    current_mb = utils.get_current_vram_mb(total_mb)
    default_mb = utils.calculate_default_vram_mb(total_mb)
    reserved_mb = max(0, total_mb - current_mb)

    print("Siliv – VRAM status")
    print("-------------------")
    print(f"Total    : {_format_mb(total_mb)}")
    print(f"Current  : {_format_mb(current_mb)}")
    print(f"Default  : {_format_mb(default_mb)}")
    print(f"Reserved : {_format_mb(reserved_mb)}")


def set_cmd(args: argparse.Namespace) -> None:
    """Set VRAM to the requested value (in MB)."""
    target_mb = args.value_mb
    ok, msg = utils.set_vram_mb(target_mb)
    if ok:
        print(f"✔ Set VRAM to {_format_mb(target_mb)}")
    else:
        print(f"✖ Failed to set VRAM – {msg}", file=sys.stderr)
        sys.exit(1)


def default_cmd(_: argparse.Namespace) -> None:
    """Reset VRAM to macOS default (0)."""
    ok, msg = utils.set_vram_mb(0)
    if ok:
        print("✔ VRAM reset to macOS default (0)")
    else:
        print(f"✖ Failed to reset VRAM – {msg}", file=sys.stderr)
        sys.exit(1)


# --------------------------------------------------------------------------- #
# main / argparse boilerplate
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="siliv-cli", description="Siliv command-line interface")
    sub = p.add_subparsers(dest="command", required=True)

    # status
    sp = sub.add_parser("status", help="Show current VRAM / RAM information")
    sp.set_defaults(func=status_cmd)

    # set
    sp = sub.add_parser("set", help="Set VRAM to the specified amount (MB / GB)")
    sp.add_argument("value_mb", type=_parse_size, help="Value to set (e.g. 8192 or 8G)")
    sp.set_defaults(func=set_cmd)

    # default
    sp = sub.add_parser("default", help="Reset VRAM to macOS default")
    sp.set_defaults(func=default_cmd)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    ns.func(ns)


if __name__ == "__main__":
    main()