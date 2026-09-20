"""AGENTS.md -> list[Rule]. Pattern-based, no LLM."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Callable

from .models import Rule, RuleCategory as C, RuleType as T

AGENTS_FILENAMES = ("AGENTS.md", "CLAUDE.md")

Extractor = Callable[[str], list[Rule]]


def find_agents_md(repo_path: str | Path) -> Path | None:
    """Locate AGENTS.md (or a CLAUDE.md symlink/file) in the repo root."""
    repo = Path(repo_path)
    for name in AGENTS_FILENAMES:
        candidate = repo / name
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# Line-level extractors
# --------------------------------------------------------------------------


def _static(
    rule_id: str,
    pattern: str,
    category: C,
    rule_type: T,
    description: str,
    params: dict,
    weight: float = 1.0,
    flags: int = re.IGNORECASE,
) -> Extractor:
    rx = re.compile(pattern, flags)

    def extract(line: str) -> list[Rule]:
        if rx.search(line):
            return [Rule(rule_id, category, rule_type, description, copy.deepcopy(params), weight)]
        return []

    return extract


_PACKAGE_MANAGERS = "uv|maven|npm|pnpm|yarn|poetry|gradle"
_PM_RX = re.compile(
    r"\b(?:uses?|using|via|with|managed\s+(?:by|with)|package\s+manager(?:\s+is)?[:\s])\s*[*`_]*"
    rf"({_PACKAGE_MANAGERS})\b",
    re.IGNORECASE,
)


def _package_managers(line: str) -> list[Rule]:
    rules = []
    for m in _PM_RX.finditer(line):
        pm = m.group(1).lower()
        rules.append(
            Rule(
                f"build_{pm}",
                C.BUILD,
                T.COMMAND_CHECK,
                f"Uses {pm} as package manager",
                {"package_manager": pm},
            )
        )
    return rules


_NO_PIP_RX = re.compile(r"\b(?:not|never\s+use|do\s+not\s+use|don't\s+use)\s+[*`_]*pip\b", re.IGNORECASE)


def _no_pip(line: str) -> list[Rule]:
    if _NO_PIP_RX.search(line):
        return [
            Rule(
                "build_no_pip",
                C.BUILD,
                T.FILE_NOT_EXISTS,
                "pip is not used (no requirements.txt)",
                {"path": "requirements.txt"},
            )
        ]
    return []


_LINTERS = "ruff|eslint|flake8|pylint|black|prettier|checkstyle|spotbugs|isort|biome"
_CHECKERS = "mypy|pyright|typescript"
_QUAL_RX = re.compile(rf"\b({_LINTERS}|{_CHECKERS})\b", re.IGNORECASE)


def _quality_tools(line: str) -> list[Rule]:
    rules = []
    for m in _QUAL_RX.finditer(line):
        tool = m.group(1).lower()
        rules.append(
            Rule(
                f"qual_{tool}",
                C.CODE_QUALITY,
                T.DEPENDENCY_CHECK,
                f"{tool} is configured",
                {"package": tool},
            )
        )
    return rules


_SECRET_PATTERNS = [
    r"""(?i)\b(?:password|passwd|secret|api_?key)\s*=\s*["'][^"'\s]{3,}["']""",
    r"sk-ant-[A-Za-z0-9_-]{8,}",
    r"AKIA[0-9A-Z]{16}",
]

_LINE_EXTRACTORS: list[Extractor] = [
    # Build / environment
    _package_managers,
    _no_pip,
    # Architecture
    _static(
        "arch_layered",
        r"router\s*(?:→|->|>|to)\s*service\s*(?:→|->|>|to)\s*repositor|layered\s+architecture",
        C.ARCHITECTURE,
        T.DIR_STRUCTURE,
        "Layered architecture enforced",
        {"required_dirs": ["services", "repositories"]},
    ),
    _static(
        "arch_di",
        r"dependency\s+injection|\bDI\b|\bguice\b",
        C.ARCHITECTURE,
        T.PATTERN_USAGE,
        "Dependency injection used",
        {"patterns": ["Depends(", "@Inject", "@inject"]},
    ),
    _static(
        "arch_api_versioning",
        r"/api/v\d|versioned\s+api",
        C.ARCHITECTURE,
        T.PATTERN_USAGE,
        "API is versioned",
        {"patterns": ["/api/v1", "/api/v2"]},
    ),
    _static(
        "arch_async",
        r"\basync(?:-first)?\b",
        C.ARCHITECTURE,
        T.PATTERN_USAGE,
        "Async code used",
        {"patterns": ["async def", "async function"]},
    ),
    _static(
        "arch_pydantic_settings",
        r"pydantic\s+settings|basesettings",
        C.ARCHITECTURE,
        T.PATTERN_USAGE,
        "Pydantic Settings used for configuration",
        {"patterns": ["BaseSettings"]},
    ),
    _static(
        "arch_alembic",
        r"alembic|migrations?\b",
        C.ARCHITECTURE,
        T.FILE_EXISTS,
        "Database migrations directory exists",
        {"path": "alembic", "alternatives": ["migrations"]},
    ),
    _static(
        "arch_makefile",
        r"\bmakefile\b",
        C.ARCHITECTURE,
        T.FILE_EXISTS,
        "Makefile exists",
        {"path": "Makefile"},
    ),
    _static(
        "arch_docker",
        r"\bdocker",
        C.ARCHITECTURE,
        T.FILE_EXISTS,
        "Docker configuration exists",
        {
            "path": "Dockerfile",
            "alternatives": [
                "docker-compose.yml",
                "docker-compose.yaml",
                "docker/Dockerfile",
                "docker/docker-compose.yml",
            ],
        },
    ),
    _static(
        "arch_openapi",
        r"\bopenapi\b",
        C.ARCHITECTURE,
        T.FILE_EXISTS,
        "OpenAPI spec exists",
        {"find": ["openapi.yaml", "openapi.yml", "openapi.json"]},
    ),
    _static(
        "arch_hexagonal",
        r"hexagonal|\bonion\b|ports\s+and\s+adapters",
        C.ARCHITECTURE,
        T.DIR_STRUCTURE,
        "Hexagonal architecture layout",
        {"required_dirs": ["domain", "application", "infrastructure"]},
    ),
    _static(
        "arch_jpms",
        r"\bjpms\b|module-info\.java",
        C.ARCHITECTURE,
        T.FILE_EXISTS,
        "JPMS module descriptor exists",
        {"find": ["module-info.java"]},
    ),
    # Security
    _static(
        "sec_auth",
        r"authenticated\s+by\s+default|\bjwt\b|all\s+endpoints\s+(?:are\s+)?authenticated"
        r"|every\s+endpoint\s+(?:is\s+)?authenticated|\boauth\b",
        C.SECURITY,
        T.PATTERN_USAGE,
        "Authentication implemented",
        {"patterns": ["jwt", "JWT", "verify_token", "get_current_user", "Bearer", "OAuth"]},
    ),
    _static(
        "sec_no_secrets",
        r"(?:no|never)\s+(?:commit\s+|hard-?coded\s+|store\s+)?(?:secrets?|credentials?)\b|secrets?\s+in\s+source",
        C.SECURITY,
        T.PATTERN_ABSENCE,
        "No secrets in source",
        {
            "forbidden_patterns": _SECRET_PATTERNS,
            "exclude_files": ["*.md", "*.example", "tests/*"],
        },
    ),
    _static(
        "sec_env_gitignore",
        r"\.env\b[^\n]{0,40}gitignore|gitignore[^\n]{0,40}\.env\b",
        C.SECURITY,
        T.FILE_CONTAINS,
        ".env is in .gitignore",
        {"file": ".gitignore", "pattern": r"^\.env\b"},
    ),
    _static(
        "sec_password_hashing",
        r"bcrypt|argon2|password\s+hashing",
        C.SECURITY,
        T.PATTERN_USAGE,
        "Password hashing implemented",
        {"patterns": ["bcrypt", "argon2", "hashpw", "hash_password"]},
    ),
    _static(
        "sec_rbac",
        r"role-based|\brbac\b|authorization",
        C.SECURITY,
        T.PATTERN_USAGE,
        "Authorization / RBAC implemented",
        {"patterns": ["role", "permission", "is_admin", "authorize"]},
    ),
    # Testing
    _static(
        "test_unit_dir",
        r"unit\s+tests?|tests?/unit",
        C.TESTING,
        T.FILE_EXISTS,
        "Unit test directory exists",
        {"path": "tests/unit", "alternatives": ["test/unit"]},
    ),
    _static(
        "test_integration_dir",
        r"integration\s+tests?|tests?/integration",
        C.TESTING,
        T.FILE_EXISTS,
        "Integration test directory exists",
        {"path": "tests/integration", "alternatives": ["test/integration"]},
    ),
    _static(
        "test_bdd",
        r"\bbdd\b|gherkin|\.feature\b|pytest-bdd|cucumber",
        C.TESTING,
        T.FILE_EXISTS,
        "BDD feature files exist",
        {"find": ["*.feature"]},
    ),
    _static(
        "test_conftest",
        r"conftest|fixtures",
        C.TESTING,
        T.FILE_EXISTS,
        "conftest.py exists",
        {"path": "tests/conftest.py"},
    ),
    _static(
        "test_no_skip",
        r"never\s+(?:delete|skip)\s+tests?",
        C.TESTING,
        T.CONVENTION,
        "Tests are never skipped",
        {"check": "no_skip_markers"},
    ),
    _static(
        "test_component",
        r"component\s+tests?|contract\s+tests?|\bpact\b",
        C.TESTING,
        T.FILE_EXISTS,
        "Component / contract test directory exists",
        {
            "path": "tests/component",
            "alternatives": [
                "tests/contract",
                "tests/pact",
                "test/component",
                "test/contract",
            ],
        },
    ),
    # Code quality
    _quality_tools,
    _static(
        "qual_sqlalchemy_mapped",
        r"Mapped\[",
        C.CODE_QUALITY,
        T.PATTERN_USAGE,
        "SQLAlchemy 2.0 Mapped[] used",
        {"patterns": ["Mapped["]},
        flags=0,
    ),
    _static(
        "qual_pydantic_v2",
        r"model_validate|model_dump",
        C.CODE_QUALITY,
        T.PATTERN_USAGE,
        "Pydantic v2 API used",
        {"patterns": ["model_validate", "model_dump"]},
    ),
    # Spec adherence
    _static(
        "spec_dir",
        r"\bspecs/|spec-first|technical\s+design",
        C.SPEC_ADHERENCE,
        T.FILE_EXISTS,
        "specs/ directory exists",
        {"path": "specs"},
    ),
    _static(
        "spec_adr",
        r"\badrs?\b|architecture\s+decisions?",
        C.SPEC_ADHERENCE,
        T.FILE_EXISTS,
        "ADR directory exists",
        {"path": "specs/adr", "alternatives": ["adr", "docs/adr"]},
    ),
    _static(
        "spec_gherkin_first",
        r"gherkin\s+before\s+code|spec\s+gate",
        C.SPEC_ADHERENCE,
        T.FILE_EXISTS,
        "Gherkin feature files exist",
        {"find": ["*.feature"]},
    ),
    _static(
        "spec_conventional_commits",
        r"conventional\s+commits?",
        C.SPEC_ADHERENCE,
        T.CONVENTION,
        "Recent commits follow conventional commits",
        {"check": "conventional_commits"},
    ),
]


# --------------------------------------------------------------------------
# Markdown parsing
# --------------------------------------------------------------------------

_FENCE_RX = re.compile(r"^\s*(?:```|~~~)")
_TREE_BRANCH_RX = re.compile(r"[├└]")


def _split_sections(text: str) -> list[list[str]]:
    """Split on level-2 headings (`## `), ignoring headings inside fenced code."""
    sections: list[list[str]] = [[]]
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RX.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            sections.append([])
        sections[-1].append(line)
    return sections


def _parse_section(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Return (prose lines incl. non-tree code, tree code blocks)."""
    prose: list[str] = []
    trees: list[list[str]] = []
    block: list[str] | None = None
    for line in lines:
        if _FENCE_RX.match(line):
            if block is None:
                block = []
            else:
                _close_block(block, prose, trees)
                block = None
        elif block is not None:
            block.append(line)
        else:
            prose.append(line)
    if block is not None:  # unterminated fence
        _close_block(block, prose, trees)
    return prose, trees


def _close_block(block: list[str], prose: list[str], trees: list[list[str]]) -> None:
    if any(_TREE_BRANCH_RX.search(line) for line in block):
        trees.append(block)
    else:
        prose.extend(block)


# --------------------------------------------------------------------------
# Directory tree extraction
# --------------------------------------------------------------------------

_BRANCH_LINE_RX = re.compile(r"^(?P<prefix>[\s│|]*)[├└][─-]*\s*(?P<rest>.*)$")
_ENTRY_RX = re.compile(r"^(?P<name>\S+)(?P<tail>\s.*)?$")
_COMMENT_START_RX = re.compile(r"^\s*(?:#|←|<-|//|—|–|-\s|\(|\[)")
_VALID_NAME_RX = re.compile(r"^[\w.\-@+/]+$")
_KNOWN_UPPERCASE = {
    "Makefile", "Dockerfile", "Jenkinsfile", "Procfile", "LICENSE", "README",
    "CHANGELOG", "Pipfile", "Gemfile", "Vagrantfile", "CODEOWNERS", "NOTICE",
}  # fmt: skip
_COMMON_WORDS = {
    "the", "and", "or", "for", "to", "of", "in", "is", "it", "this", "that", "see",
    "note", "etc", "with", "from", "by", "as", "an", "on", "not", "are", "be", "we",
    "all", "any", "each", "your", "our", "if", "then",
}  # fmt: skip


def _clean_tree_entry(rest: str) -> tuple[str, bool] | None:
    """Return (name, is_dir) for a plausible path entry, or None for noise."""
    m = _ENTRY_RX.match(rest.strip())
    if not m:
        return None
    tail = m.group("tail")
    if tail and tail.strip() and not _COMMENT_START_RX.match(tail):
        return None  # trailing prose -> the whole line is a comment
    name = m.group("name").strip("`*_")
    if not _VALID_NAME_RX.match(name):
        return None
    is_dir = name.endswith("/")
    stripped = name.rstrip("/")
    if len(stripped) < 2 or not any(ch.isalnum() for ch in stripped):
        return None
    if stripped.startswith("/") or ".." in stripped.split("/"):
        return None
    if stripped.lower() in _COMMON_WORDS:
        return None
    if stripped[0].isupper() and not (is_dir or "." in stripped or stripped in _KNOWN_UPPERCASE):
        return None
    return stripped, is_dir


def _slug(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")


def _extract_tree(block: list[str]) -> list[Rule]:
    rules: list[Rule] = []
    stack: list[tuple[int, str]] = []  # (indent column, full path)
    for line in block:
        m = _BRANCH_LINE_RX.match(line)
        if not m:
            continue  # root marker, blank line or continuation
        col = len(m.group("prefix"))
        entry = _clean_tree_entry(m.group("rest"))
        if entry is None:
            continue
        name, _is_dir = entry
        while stack and stack[-1][0] >= col:
            stack.pop()
        path = f"{stack[-1][1]}/{name}" if stack else name
        stack.append((col, path))
        rules.append(
            Rule(
                f"struct_{_slug(path)}",
                C.ARCHITECTURE,
                T.FILE_EXISTS,
                f"Path `{path}` exists (from directory tree)",
                {"path": path},
                weight=0.5,
                source_text=line.strip(),
            )
        )
    return rules


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def extract_rules_from_text(text: str, agents_md_name: str = "AGENTS.md") -> list[Rule]:
    """Extract rules from AGENTS.md text. Deduplicates by id, first wins."""
    rules: dict[str, Rule] = {}

    def add(rule: Rule) -> None:
        rules.setdefault(rule.id, rule)

    add(
        Rule(
            "meta_agents_md",
            C.SPEC_ADHERENCE,
            T.FILE_EXISTS,
            "AGENTS.md exists in repo",
            {"path": agents_md_name, "alternatives": list(AGENTS_FILENAMES)},
            weight=2.0,
        )
    )

    for section in _split_sections(text):
        prose, trees = _parse_section(section)
        for line in prose:
            if not line.strip():
                continue
            for extractor in _LINE_EXTRACTORS:
                for rule in extractor(line):
                    rule.source_text = line.strip()
                    add(rule)
        for block in trees:
            for rule in _extract_tree(block):
                add(rule)
    return list(rules.values())


def extract_rules(agents_md_path: str | Path) -> list[Rule]:
    """Extract all checkable rules from an AGENTS.md file."""
    path = Path(agents_md_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return extract_rules_from_text(text, path.name)
