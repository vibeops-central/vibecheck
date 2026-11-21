"""Static check of an agent skill (a folder with a SKILL.md) before it is installed.

`vibecheck skill PATH` answers three questions without running anything:

- Permissions: what does the skill read, write, run and call?
- Version: is it pinned, and has it changed since it was pinned?
- Cost: how much context does it add when loaded?

A fourth question, proof (does the skill help on your own work?), needs agent runs and is
reported as skipped. Like the rest of v0.1 this is static only: no LLM calls, no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .models import CheckResult

SKILL_FILE = "SKILL.md"
LOCK_FILE = "skills.lock.json"
DEFAULT_GATE = 0.5

WEIGHTS: dict[str, float] = {"permissions": 0.5, "version": 0.3, "cost": 0.2}
DISPLAY_NAMES = {"permissions": "Permissions", "version": "Version", "cost": "Cost"}

HIGH, MEDIUM = "high", "medium"
SEVERITY_WEIGHT = {HIGH: 3.0, MEDIUM: 1.0}

TEXT_EXTS = {
    ".md", ".txt", ".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl",
    ".ps1", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", "",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
MAX_FILE_BYTES = 1_000_000
MAX_EVIDENCE = 3
CHARS_PER_TOKEN = 4  # rough estimate; good enough to compare skills

# Cost thresholds, in estimated tokens.
SKILL_MD_PASS, SKILL_MD_WARN = 5_000, 10_000
BUNDLE_PASS, BUNDLE_WARN = 25_000, 60_000
DESCRIPTION_MAX_CHARS = 1024

ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"


@dataclass(frozen=True)
class PatternCheck:
    id: str
    severity: str
    description: str
    pattern: re.Pattern[str]


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


PERMISSION_CHECKS: tuple[PatternCheck, ...] = (
    PatternCheck(
        "pipe-to-shell",
        HIGH,
        "does not pipe a download or decoded text into a shell",
        _rx(r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b|base64\s+(-d|--decode)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b"),
    ),
    PatternCheck(
        "reads-credentials",
        HIGH,
        "does not touch SSH keys, cloud credentials or other secret stores",
        _rx(
            r"~/\.ssh|\bid_(rsa|ed25519|ecdsa)\b|\.aws/credentials|\.netrc\b|\.git-credentials|"
            r"security\s+find-generic-password|(cat|source|open\(|read)[^\n]{0,40}\.env\b"
        ),
    ),
    PatternCheck(
        "hidden-characters",
        HIGH,
        "has no invisible characters that could hide text from a reviewer",
        _rx(f"[{ZERO_WIDTH}]"),
    ),
    # Phrases are a review item, not a block: a static scan cannot tell a skill that gives
    # such an instruction from one that quotes it as something to refuse.
    PatternCheck(
        "injection-phrases",
        MEDIUM,
        "has no phrases that override instructions or hide actions from the user",
        _rx(
            r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions|"
            r"do\s+not\s+(tell|inform|mention)[^\n]{0,40}\b(user|human)\b|"
            r"without\s+(telling|asking|informing)\s+the\s+user"
        ),
    ),
    PatternCheck(
        "network-calls",
        MEDIUM,
        "makes no network calls",
        _rx(r"\b(curl|wget)\s|requests\.(get|post|put)\(|urllib\.request|httpx\.|\bfetch\(|\bnc\s+-"),
    ),
    PatternCheck(
        "install-steps",
        MEDIUM,
        "asks for no installs or elevated rights",
        _rx(
            r"\b(pip3?|uv|npm|pnpm|yarn|brew|apt|apt-get|cargo)\s+(install|add)\b|\bnpx\s|\bsudo\s|chmod\s+\+x"
        ),
    ),
    PatternCheck(
        "shell-exec",
        MEDIUM,
        "runs no dynamic or destructive commands",
        _rx(r"rm\s+-rf?\s|\beval\s*[(\"$]|os\.system\(|subprocess\.|child_process|\bexec\("),
    ),
    PatternCheck(
        "agent-files",
        MEDIUM,
        "does not touch agent memory or identity files",
        _rx(r"\b(CLAUDE|AGENTS|MEMORY|SOUL|IDENTITY)\.md\b|~/\.claude\b|\.claude/|\.cursorrules|~/\.codex\b"),
    ),
)


@dataclass
class SkillResult:
    id: str
    dimension: str
    description: str
    result: CheckResult
    severity: str = MEDIUM
    evidence: list[str] = field(default_factory=list)

    @property
    def weight(self) -> float:
        return SEVERITY_WEIGHT[self.severity]

    @property
    def score(self) -> float:
        return {CheckResult.PASS: 1.0, CheckResult.WARN: 0.5}.get(self.result, 0.0)


@dataclass
class SkillReport:
    name: str
    path: str
    sha256: str
    score: float
    blocked: bool
    dimensions: dict[str, float]
    results: list[SkillResult]
    skill_md_tokens: int
    bundle_tokens: int
    files: int
    lock_path: str = ""

    def count(self, kind: CheckResult) -> int:
        return sum(1 for r in self.results if r.result == kind)

    def to_dict(self) -> dict:
        return {
            "skill": self.name,
            "path": self.path,
            "version": __version__,
            "sha256": self.sha256,
            "vibecheck_score": round(self.score, 4),
            "blocked": self.blocked,
            "lock_path": self.lock_path,
            "estimated_tokens": {"skill_md": self.skill_md_tokens, "bundle": self.bundle_tokens},
            "files": self.files,
            "dimensions": {name: round(score, 4) for name, score in self.dimensions.items()},
            "results": [
                {
                    "id": r.id,
                    "dimension": r.dimension,
                    "description": r.description,
                    "result": r.result.value,
                    "severity": r.severity,
                    "evidence": r.evidence,
                }
                for r in self.results
            ],
        }


def find_skill_dir(path: str | Path) -> Path | None:
    """Return the skill folder for PATH (a folder holding SKILL.md, or the SKILL.md itself)."""
    p = Path(path)
    if p.is_file() and p.name == SKILL_FILE:
        return p.parent
    if p.is_dir() and (p / SKILL_FILE).is_file():
        return p
    return None


def _skill_files(skill_dir: Path) -> list[Path]:
    files = []
    for root, dirs, names in os.walk(skill_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        files.extend(Path(root) / n for n in sorted(names))
    return files


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_EXTS:
        return None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def skill_hash(skill_dir: Path) -> str:
    """One hash over every file's relative path and bytes, so any change is visible."""
    digest = hashlib.sha256()
    for f in _skill_files(skill_dir):
        digest.update(f.relative_to(skill_dir).as_posix().encode())
        digest.update(b"\0")
        try:
            digest.update(f.read_bytes())
        except OSError:
            pass
        digest.update(b"\0")
    return digest.hexdigest()


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t", "-")):
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return {}  # no closing marker: not valid frontmatter


def _scan(check: PatternCheck, texts: dict[str, str]) -> list[str]:
    evidence: list[str] = []
    for rel, text in texts.items():
        body = text.lstrip("\ufeff")  # a leading byte-order mark is not hidden text
        for number, line in enumerate(body.splitlines(), start=1):
            if check.pattern.search(line):
                evidence.append(f"{rel}:{number}: {line.strip()[:120]}")
                if len(evidence) >= MAX_EVIDENCE:
                    return evidence
    return evidence


def _permission_results(texts: dict[str, str], meta: dict[str, str]) -> list[SkillResult]:
    results = []
    for check in PERMISSION_CHECKS:
        evidence = _scan(check, texts)
        if not evidence:
            outcome = CheckResult.PASS
        else:
            outcome = CheckResult.FAIL if check.severity == HIGH else CheckResult.WARN
        results.append(SkillResult(check.id, "permissions", check.description, outcome, check.severity, evidence))

    declared = meta.get("allowed-tools", "")
    results.append(
        SkillResult(
            "declares-tools",
            "permissions",
            "declares the tools it needs (allowed-tools)",
            CheckResult.PASS if declared else CheckResult.WARN,
            MEDIUM,
            [f"allowed-tools: {declared}"] if declared else ["no allowed-tools in the SKILL.md frontmatter"],
        )
    )
    return results


def default_lock_path(skill_dir: Path) -> Path:
    return skill_dir.resolve().parent / LOCK_FILE


def read_lock(lock_path: Path) -> dict[str, dict]:
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    skills = data.get("skills") if isinstance(data, dict) else None
    return skills if isinstance(skills, dict) else {}


def pin(skill_dir: Path, lock_path: Path | None = None) -> Path:
    """Record the skill's current hash in the lock file. Returns the lock file's path."""
    lock_path = lock_path or default_lock_path(skill_dir)
    meta = parse_frontmatter(_read_text(skill_dir / SKILL_FILE) or "")
    name = meta.get("name") or skill_dir.resolve().name
    skills = read_lock(lock_path)
    skills[name] = {"sha256": skill_hash(skill_dir)}
    lock_path.write_text(
        json.dumps({"version": 1, "skills": dict(sorted(skills.items()))}, indent=2) + "\n",
        encoding="utf-8",
    )
    return lock_path


def _version_results(name: str, digest: str, meta: dict[str, str], lock_path: Path) -> list[SkillResult]:
    missing = [key for key in ("name", "description") if not meta.get(key)]
    results = [
        SkillResult(
            "frontmatter",
            "version",
            "has a name and a description in its frontmatter",
            CheckResult.FAIL if missing else CheckResult.PASS,
            MEDIUM,
            [f"missing: {', '.join(missing)}"] if missing else [],
        )
    ]
    entry = read_lock(lock_path).get(name)
    pinned = entry.get("sha256") if isinstance(entry, dict) else None
    if pinned is None:
        outcome, evidence = CheckResult.FAIL, [f"not pinned in {lock_path} (run with --pin after review)"]
    elif pinned != digest:
        outcome, evidence = CheckResult.FAIL, [f"changed since it was pinned: {pinned[:12]} -> {digest[:12]}"]
    else:
        outcome, evidence = CheckResult.PASS, [f"pinned at {digest[:12]}"]
    results.append(SkillResult("pinned", "version", "is pinned and unchanged since review", outcome, HIGH, evidence))
    return results


def _size_result(id_: str, description: str, tokens: int, ok: int, warn: int, severity: str) -> SkillResult:
    outcome = CheckResult.PASS if tokens <= ok else CheckResult.WARN if tokens <= warn else CheckResult.FAIL
    return SkillResult(id_, "cost", description, outcome, severity, [f"about {tokens:,} tokens (limit {ok:,})"])


def _cost_results(skill_md_tokens: int, bundle_tokens: int, meta: dict[str, str]) -> list[SkillResult]:
    description = meta.get("description", "")
    return [
        _size_result("skill-md-size", "SKILL.md is small enough to load cheaply", skill_md_tokens, SKILL_MD_PASS, SKILL_MD_WARN, HIGH),
        _size_result("bundle-size", "the whole skill is a reasonable size", bundle_tokens, BUNDLE_PASS, BUNDLE_WARN, MEDIUM),
        SkillResult(
            "description-size",
            "cost",
            "its always-loaded description is short",
            CheckResult.PASS if len(description) <= DESCRIPTION_MAX_CHARS else CheckResult.WARN,
            MEDIUM,
            [f"{len(description)} characters (limit {DESCRIPTION_MAX_CHARS})"],
        ),
    ]


def _dimension_score(results: list[SkillResult]) -> float:
    total = sum(r.weight for r in results)
    return sum(r.score * r.weight for r in results) / total if total else 0.0


def evaluate_skill(path: str | Path, lock_path: str | Path | None = None) -> SkillReport | None:
    """Check one skill. Returns None when PATH holds no SKILL.md."""
    skill_dir = find_skill_dir(path)
    if skill_dir is None:
        return None

    files = _skill_files(skill_dir)
    texts = {}
    for f in files:
        text = _read_text(f)
        if text is not None:
            texts[f.relative_to(skill_dir).as_posix()] = text

    skill_md = texts.get(SKILL_FILE, "")
    meta = parse_frontmatter(skill_md)
    name = meta.get("name") or skill_dir.resolve().name
    digest = skill_hash(skill_dir)
    lock = Path(lock_path) if lock_path else default_lock_path(skill_dir)
    skill_md_tokens = len(skill_md) // CHARS_PER_TOKEN
    bundle_tokens = sum(len(t) for t in texts.values()) // CHARS_PER_TOKEN

    results = (
        _permission_results(texts, meta)
        + _version_results(name, digest, meta, lock)
        + _cost_results(skill_md_tokens, bundle_tokens, meta)
    )
    dimensions = {name_: _dimension_score([r for r in results if r.dimension == name_]) for name_ in WEIGHTS}
    score = sum(dimensions[d] * w for d, w in WEIGHTS.items())

    # "One bad answer and it stays out": a high-severity permission finding, or a change
    # since the skill was pinned, blocks the skill whatever the overall score.
    blocked = any(
        r.result == CheckResult.FAIL and r.severity == HIGH and r.dimension == "permissions" for r in results
    ) or any(r.id == "pinned" and r.evidence and r.evidence[0].startswith("changed") for r in results)

    return SkillReport(
        name=name,
        path=str(skill_dir),
        sha256=digest,
        score=score,
        blocked=blocked,
        dimensions=dimensions,
        results=results,
        skill_md_tokens=skill_md_tokens,
        bundle_tokens=bundle_tokens,
        files=len(files),
        lock_path=str(lock),
    )


def render_skill_report(report: SkillReport, verbosity: int = 0, color: bool = False) -> str:
    from .cli import RULE, SYMBOLS, _bar, _paint, _score_color

    verdict = _paint("BLOCKED", "31", color) if report.blocked else _paint(f"{report.score:.3f}", _score_color(report.score), color)
    lines = [
        f"  ⚡ Vibecheck {__version__} · skill: {report.name}",
        RULE,
        f"  Score: {verdict}" + (f"  ({report.score:.3f})" if report.blocked else ""),
        RULE,
    ]
    for name, weight in WEIGHTS.items():
        score = report.dimensions[name]
        bar = _paint(_bar(score), _score_color(score), color)
        lines.append(f"  {DISPLAY_NAMES[name]:<16} {bar}  {score:.2f}  {round(weight * 100)}%")
    lines.append("  Proof            needs agent runs; not part of the static check")
    lines.append(RULE)
    lines.append(
        f"  {len(report.results)} checks · {report.count(CheckResult.PASS)} passed · "
        f"{report.count(CheckResult.FAIL)} failed · {report.count(CheckResult.WARN)} to review"
    )
    lines.append(
        f"  {report.files} files · SKILL.md about {report.skill_md_tokens:,} tokens · "
        f"whole skill about {report.bundle_tokens:,} · sha256 {report.sha256[:12]}"
    )

    show_all = verbosity >= 2
    shown = [r for r in report.results if show_all or r.result != CheckResult.PASS]
    if shown and (verbosity >= 1 or report.blocked):
        lines.append("")
        lines.append("  All checks:" if show_all else "  To look at:")
        for r in shown:
            sym, code = SYMBOLS[r.result]
            lines.append(f"  {_paint(sym, code, color)} [{r.dimension}] {r.description}")
            lines.extend(f"      {e}" for e in r.evidence)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vibecheck skill",
        description="Check an agent skill (a folder with a SKILL.md) before you install it.",
    )
    p.add_argument("path", nargs="?", default=".", help="skill folder or SKILL.md (default: .)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v findings, -vv all checks")
    p.add_argument("--json", action="store_true", help="print JSON to stdout")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--lock", metavar="PATH", help=f"lock file (default: {LOCK_FILE} next to the skill folder)")
    p.add_argument("--pin", action="store_true", help="record the skill's current hash in the lock file, then check")
    p.add_argument("--gate", type=float, metavar="SCORE", help=f"exit 1 if the score is below SCORE (default {DEFAULT_GATE})")
    return p


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 passes, 1 blocked or below the gate, 2 no SKILL.md found."""
    args = build_parser().parse_args(argv)
    skill_dir = find_skill_dir(args.path)
    if skill_dir is None:
        message = f"No {SKILL_FILE} found at {args.path}"
        print(json.dumps({"error": message}, indent=2) if args.json else f"  ⚡ Vibecheck {__version__}\n  {message}")
        return 2

    lock = Path(args.lock) if args.lock else None
    if args.pin:
        pin(skill_dir, lock)
    report = evaluate_skill(skill_dir, lock)
    assert report is not None

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        color = not args.no_color and "NO_COLOR" not in os.environ and sys.stdout.isatty()
        print(render_skill_report(report, args.verbose, color))

    gate = DEFAULT_GATE if args.gate is None else args.gate
    return 1 if report.blocked or report.score < gate else 0
