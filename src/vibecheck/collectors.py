"""Rule x repo -> MetricResult. Static, offline checks (stdlib only)."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterator

from .models import CheckResult, MetricResult, Rule, RuleType

IGNORE_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "target", ".idea", "site-packages",
    ".eggs", ".gradle",
}  # fmt: skip
TEST_DIRS = {"tests", "test", "__tests__"}
SOURCE_EXTS = {
    ".py", ".java", ".kt", ".scala", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb",
    ".php", ".cs", ".swift", ".c", ".cpp", ".h",
}  # fmt: skip
CONFIG_EXTS = {".yml", ".yaml", ".toml", ".json", ".xml", ".properties", ".ini", ".cfg", ".gradle", ".tf"}
SKIP_FILENAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock"}
MAX_FILE_BYTES = 512 * 1024
SEARCH_PREFIXES = ("src", "app", "lib", "tests")

PACKAGE_MANAGER_FILES: dict[str, list[str]] = {
    "uv": ["uv.lock"],
    "maven": ["pom.xml"],
    "npm": ["package-lock.json"],
    "pnpm": ["pnpm-lock.yaml"],
    "yarn": ["yarn.lock"],
    "poetry": ["poetry.lock"],
    "gradle": ["build.gradle", "build.gradle.kts"],
}
DEPENDENCY_FILES = {
    "pyproject.toml", "pom.xml", "package.json", "build.gradle", "build.gradle.kts",
    "Pipfile", "setup.cfg", "setup.py",
}  # fmt: skip
CONVENTIONAL_COMMIT_RX = re.compile(
    r"^(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(?:\([^)\s]+\))?!?: \S"
)
SKIP_MARKER_RXS = [
    re.compile(r"@pytest\.mark\.skip\b"),
    re.compile(r"\bpytest\.skip\("),
    re.compile(r"@unittest\.skip"),
    re.compile(r"@Disabled\b"),
    re.compile(r"\b(?:it|test|describe)\.skip\("),
]

Collector = Callable[[Rule, Path], MetricResult]


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------


def _walk(repo: Path, max_depth: int | None = None) -> Iterator[tuple[Path, list[str], list[str]]]:
    """os.walk with ignored/hidden dirs pruned. Yields (dir, dirnames, filenames)."""
    base_depth = len(repo.parts)
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith("."))
        rootp = Path(root)
        if max_depth is not None and len(rootp.parts) - base_depth >= max_depth:
            dirs[:] = []
        yield rootp, dirs, sorted(files)


def _is_test_path(rel: str) -> bool:
    return any(part in TEST_DIRS for part in rel.split("/")[:-1])


def _scan_files(repo: Path, exts: set[str], skip_tests: bool = True) -> Iterator[tuple[Path, str]]:
    for root, _dirs, files in _walk(repo):
        for name in files:
            if name in SKIP_FILENAMES or Path(name).suffix.lower() not in exts:
                continue
            path = root / name
            rel = path.relative_to(repo).as_posix()
            if skip_tests and _is_test_path(rel):
                continue
            yield path, rel


def _read_text(path: Path) -> str | None:
    """Read a text file; None for binary, oversized or unreadable files."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
        if b"\0" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _resolve(repo: Path, rel: str) -> Path | None:
    """Find `rel` under the repo root, then under common subdirectories."""
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    root = repo.resolve()
    for prefix in ("",) + SEARCH_PREFIXES:
        candidate = repo / prefix / rel
        if candidate.exists():
            try:
                candidate.resolve().relative_to(root)
            except ValueError:
                continue
            return candidate
    return None


def _result(rule: Rule, result: CheckResult, score: float, evidence: str, **details) -> MetricResult:
    return MetricResult(rule.id, rule, result, score, evidence, details)


def _pass(rule: Rule, evidence: str, **details) -> MetricResult:
    return _result(rule, CheckResult.PASS, 1.0, evidence, **details)


def _fail(rule: Rule, evidence: str, **details) -> MetricResult:
    return _result(rule, CheckResult.FAIL, 0.0, evidence, **details)


def _skip(rule: Rule, evidence: str) -> MetricResult:
    return _result(rule, CheckResult.SKIP, 0.0, evidence)


def _candidates(params: dict) -> list[str]:
    out = []
    if params.get("path"):
        out.append(params["path"])
    out.extend(params.get("alternatives", []))
    return out


# --------------------------------------------------------------------------
# Collectors
# --------------------------------------------------------------------------


def collect_file_exists(rule: Rule, repo: Path) -> MetricResult:
    params = rule.check_params
    glob = params.get("glob")
    candidates = _candidates(params)

    for cand in candidates:
        found = _resolve(repo, cand)
        if found is None:
            continue
        if glob:
            if found.is_dir() and any(f.is_file() for f in found.rglob(glob)):
                return _pass(rule, f"Found {cand} containing {glob}", path=cand)
            continue
        return _pass(rule, f"Found {cand}", path=cand)

    patterns = params.get("find", [])
    if patterns:
        for root, _dirs, files in _walk(repo):
            for name in files:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    rel = (root / name).relative_to(repo).as_posix()
                    return _pass(rule, f"Found {rel}", path=rel)

    wanted = candidates + patterns
    if glob and candidates:
        return _fail(rule, f"No files matching {glob} in {', '.join(candidates)}")
    return _fail(rule, f"Not found: {', '.join(wanted) or '(no path given)'}")


def collect_file_not_exists(rule: Rule, repo: Path) -> MetricResult:
    for cand in _candidates(rule.check_params):
        if cand and not cand.startswith("/") and ".." not in cand.split("/") and (repo / cand).exists():
            return _fail(rule, f"Found {cand} (should not exist)", path=cand)
    return _pass(rule, "Not present, as required")


def collect_file_contains(rule: Rule, repo: Path) -> MetricResult:
    fname = rule.check_params["file"]
    path = _resolve(repo, fname)
    if path is None or not path.is_file():
        return _fail(rule, f"{fname} not found")
    text = _read_text(path)
    if text is None:
        return _skip(rule, f"{fname} is not readable text")
    if re.search(rule.check_params["pattern"], text, re.MULTILINE):
        return _pass(rule, f"{fname} matches /{rule.check_params['pattern']}/")
    return _fail(rule, f"{fname} does not match /{rule.check_params['pattern']}/")


def _name_variants(name: str) -> set[str]:
    variants = {name}
    if name.endswith("ies"):
        variants.add(name[:-3] + "y")
    elif name.endswith("s"):
        variants.add(name[:-1])
    return variants


def collect_dir_structure(rule: Rule, repo: Path) -> MetricResult:
    required = rule.check_params.get("required_dirs", [])
    if not required:
        return _skip(rule, "No required directories specified")
    wanted = {name: _name_variants(name) for name in required}
    found: dict[str, str] = {}
    for root, dirs, _files in _walk(repo, max_depth=3):
        for d in dirs:
            for name, variants in wanted.items():
                if name not in found and d in variants:
                    found[name] = (root / d).relative_to(repo).as_posix()
    ratio = len(found) / len(required)
    missing = [n for n in required if n not in found]
    details = {"found": found, "missing": missing}
    if ratio >= 0.5:
        detail = f"Found {', '.join(found.values())}" + (f"; missing {', '.join(missing)}" if missing else "")
        return _result(rule, CheckResult.PASS, ratio, detail, **details)
    return _result(
        rule,
        CheckResult.FAIL,
        ratio,
        f"Missing directories: {', '.join(missing)}",
        **details,
    )


def _pattern_matches(text: str, patterns: list[str]) -> str | None:
    lowered = text.lower()
    for p in patterns:
        if p.lower() in lowered:
            return p
    return None


def collect_pattern_usage(rule: Rule, repo: Path) -> MetricResult:
    patterns = rule.check_params.get("patterns", [])
    for path, rel in _scan_files(repo, SOURCE_EXTS | CONFIG_EXTS):
        text = _read_text(path)
        if text is None:
            continue
        hit = _pattern_matches(text, patterns)
        if hit:
            return _pass(rule, f"Found `{hit}` in {rel}", file=rel, pattern=hit)
    return _fail(rule, f"None of {patterns} found in source files")


def collect_pattern_absence(rule: Rule, repo: Path) -> MetricResult:
    forbidden = [re.compile(p) for p in rule.check_params.get("forbidden_patterns", [])]
    excludes = rule.check_params.get("exclude_files", [])
    for path, rel in _scan_files(repo, SOURCE_EXTS | CONFIG_EXTS):
        if any(fnmatch.fnmatch(rel, e) or fnmatch.fnmatch(path.name, e) for e in excludes):
            continue
        text = _read_text(path)
        if text is None:
            continue
        for rx in forbidden:
            m = rx.search(text)
            if m:
                line = text.count("\n", 0, m.start()) + 1
                return _fail(rule, f"Forbidden pattern in {rel}:{line}", file=rel, line=line)
    return _pass(rule, "No forbidden patterns found")


def collect_dependency_check(rule: Rule, repo: Path) -> MetricResult:
    package = rule.check_params["package"]
    rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(package)}(?![A-Za-z0-9])", re.IGNORECASE)
    for root, _dirs, files in _walk(repo, max_depth=4):
        for name in files:
            is_req = name.startswith("requirements") and name.endswith(".txt")
            if name not in DEPENDENCY_FILES and not is_req:
                continue
            text = _read_text(root / name)
            if text and rx.search(text):
                rel = (root / name).relative_to(repo).as_posix()
                return _pass(rule, f"{package} found in {rel}", file=rel)
    return _fail(rule, f"{package} not found in dependency files")


def collect_command_check(rule: Rule, repo: Path) -> MetricResult:
    pm = rule.check_params["package_manager"]
    files = PACKAGE_MANAGER_FILES.get(pm)
    if files is None:
        return _skip(rule, f"Unknown package manager: {pm}")
    for f in files:
        if _resolve(repo, f):
            return _pass(rule, f"Found {f}")
    return _fail(rule, f"Missing {' / '.join(files)}")


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (
        _is_test_path(rel + "x")  # any dir component (incl. last dir) named tests/test
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts", "Test.java", "Tests.java"))
    )


def _check_no_skip_markers(rule: Rule, repo: Path) -> MetricResult:
    seen = 0
    for path, rel in _scan_files(repo, SOURCE_EXTS, skip_tests=False):
        if not _is_test_file(rel):
            continue
        seen += 1
        text = _read_text(path)
        if text is None:
            continue
        for rx in SKIP_MARKER_RXS:
            m = rx.search(text)
            if m:
                line = text.count("\n", 0, m.start()) + 1
                return _fail(rule, f"Skip marker in {rel}:{line}", file=rel, line=line)
    return _pass(rule, f"No skip markers in {seen} test file(s)")


def _check_conventional_commits(rule: Rule, repo: Path) -> MetricResult:
    if not (repo / ".git").exists():
        return _skip(rule, "Not a git repository root")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", "-n", "20", "--no-merges", "--pretty=%s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _skip(rule, "git not available")
    subjects = [s for s in proc.stdout.splitlines() if s.strip()]
    if proc.returncode != 0 or not subjects:
        return _skip(rule, "No commits to inspect")
    ok = sum(1 for s in subjects if CONVENTIONAL_COMMIT_RX.match(s))
    ratio = ok / len(subjects)
    evidence = f"{ok}/{len(subjects)} recent commits follow conventional commits"
    if ratio >= 0.8:
        return _result(rule, CheckResult.PASS, ratio, evidence)
    if ratio >= 0.5:
        return _result(rule, CheckResult.WARN, ratio, evidence)
    return _result(rule, CheckResult.FAIL, ratio, evidence)


def collect_convention(rule: Rule, repo: Path) -> MetricResult:
    check = rule.check_params.get("check")
    if check == "no_skip_markers":
        return _check_no_skip_markers(rule, repo)
    if check == "conventional_commits":
        return _check_conventional_commits(rule, repo)
    return _skip(rule, f"Unknown convention check: {check}")


def collect_llm_judge(rule: Rule, repo: Path) -> MetricResult:
    return _skip(rule, "Requires --full mode (not available in v0.1)")


COLLECTORS: dict[RuleType, Collector] = {
    RuleType.FILE_EXISTS: collect_file_exists,
    RuleType.FILE_NOT_EXISTS: collect_file_not_exists,
    RuleType.FILE_CONTAINS: collect_file_contains,
    RuleType.DIR_STRUCTURE: collect_dir_structure,
    RuleType.PATTERN_USAGE: collect_pattern_usage,
    RuleType.PATTERN_ABSENCE: collect_pattern_absence,
    RuleType.DEPENDENCY_CHECK: collect_dependency_check,
    RuleType.COMMAND_CHECK: collect_command_check,
    RuleType.CONVENTION: collect_convention,
    RuleType.LLM_JUDGE: collect_llm_judge,
}


def collect(rule: Rule, repo_path: str | Path) -> MetricResult:
    """Dispatch to the right collector; any error becomes a SKIP."""
    repo = Path(repo_path)
    collector = COLLECTORS.get(rule.rule_type)
    if collector is None:
        return _skip(rule, f"No collector for {rule.rule_type}")
    try:
        return collector(rule, repo)
    except Exception as exc:  # noqa: BLE001 - a broken check must not abort the run
        return _skip(rule, f"Check error: {type(exc).__name__}: {exc}")


def collect_all(rules: list[Rule], repo_path: str | Path) -> list[MetricResult]:
    return [collect(rule, repo_path) for rule in rules]
