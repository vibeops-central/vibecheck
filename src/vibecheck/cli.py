"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .extractor import find_agents_md
from .models import CheckResult, VibecheckReport
from .scorer import evaluate

RULE = "  " + "─" * 46
BAR_WIDTH = 20
DEFAULT_GATE = 0.5
LEARN_MORE = "https://github.com/nlauchande/vibeops"

DISPLAY_NAMES = {
    "architecture": "Architecture",
    "security": "Security",
    "testing": "Testing",
    "code_quality": "Code Quality",
    "spec_adherence": "Spec Adherence",
    "build": "Build",
}
SYMBOLS = {
    CheckResult.PASS: ("✓", "32"),
    CheckResult.FAIL: ("✗", "31"),
    CheckResult.WARN: ("!", "33"),
    CheckResult.SKIP: ("○", "90"),
}


def _paint(text: str, code: str, color: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if color else text


def _bar(score: float) -> str:
    filled = max(0, min(BAR_WIDTH, round(score * BAR_WIDTH)))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _score_color(score: float) -> str:
    return "32" if score >= 0.8 else "33" if score >= 0.5 else "31"


def render_report(report: VibecheckReport, verbosity: int = 0, color: bool = False) -> str:
    lines = [
        f"  ⚡ Vibecheck {__version__}",
        RULE,
        f"  Score: {_paint(f'{report.composite_score:.3f}', _score_color(report.composite_score), color)}",
        RULE,
    ]
    for name, dim in report.dimensions.items():
        if dim.weight <= 0:
            continue
        label = DISPLAY_NAMES.get(name, name)
        bar = _paint(_bar(dim.score), _score_color(dim.score), color)
        lines.append(f"  {label:<16} {bar}  {dim.score:.2f}  {round(dim.weight * 100)}%")
    lines.append(RULE)

    summary = f"  {report.rules_extracted} rules · {report.rules_passed} passed · {report.rules_failed} failed"
    if report.rules_warned:
        summary += f" · {report.rules_warned} warned"
    summary += f" · {report.rules_skipped} skipped"
    lines.append(summary)

    if verbosity >= 1:
        show_all = verbosity >= 2
        shown = []
        for name, dim in report.dimensions.items():
            for r in dim.results:
                if show_all or r.result in (CheckResult.FAIL, CheckResult.WARN):
                    shown.append((name, r))
        if shown:
            lines.append("")
            lines.append("  All rules:" if show_all else "  Failed rules:")
            for name, r in shown:
                sym, code = SYMBOLS[r.result]
                lines.append(f"  {_paint(sym, code, color)} [{name}] {r.rule.description}")
                if r.evidence:
                    lines.append(f"      {r.evidence}")
    return "\n".join(lines)


def _no_agents_md() -> str:
    return "\n".join(
        [
            f"  ⚡ Vibecheck {__version__}",
            RULE,
            "  No AGENTS.md found.",
            RULE,
            "  This repository has no VibeOps policy to evaluate against.",
            "  Create an AGENTS.md to define your engineering standards.",
            "",
            f"  Learn more: {LEARN_MORE}",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vibecheck",
        description="Evaluate a codebase against its AGENTS.md policy.",
    )
    p.add_argument("path", nargs="?", default=".", help="repo to evaluate (default: .)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v failed rules, -vv all rules")
    p.add_argument("--json", action="store_true", help="print JSON to stdout")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--agents-md", metavar="PATH", help="explicit AGENTS.md location")
    p.add_argument("--gate", type=float, metavar="SCORE", help="exit 1 if composite score < SCORE")
    p.add_argument("--version", action="version", version=f"vibecheck {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "skill":
        # `vibecheck skill PATH` checks an agent skill. To evaluate a repo in a folder
        # that is itself named "skill", pass it as `./skill`.
        from .skill import main as skill_main

        return skill_main(argv[1:])

    args = build_parser().parse_args(argv)
    repo = Path(args.path)

    agents = Path(args.agents_md) if args.agents_md else find_agents_md(repo)
    if agents is None or not agents.is_file():
        if args.json:
            print(json.dumps({"error": "No AGENTS.md found", "repo_path": str(repo)}, indent=2))
        else:
            print(_no_agents_md())
        return 2

    report = evaluate(repo, agents)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        color = not args.no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
        print(render_report(report, args.verbose, color))

    gate = DEFAULT_GATE if args.gate is None else args.gate
    return 1 if report.composite_score < gate else 0


if __name__ == "__main__":
    sys.exit(main())
