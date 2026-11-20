"""Command line entry point. Subcommands arrive in later commits."""

from __future__ import annotations

import argparse

from terkini import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terkini",
        description="Check AI answers about local rules against official sources.",
    )
    parser.add_argument("--version", action="version", version=f"terkini {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
