# Vibecheck v0.1 — Technical Spec

> **Status:** Ready for implementation
> **Scope:** Static-only AGENTS.md-driven codebase evaluation CLI
> **Ship when:** Produces correct scores on 3 different AGENTS.md files with passing test suite

---

## 1. What This Is

A Python CLI tool that evaluates a codebase against the rules declared in its AGENTS.md file.

```
vibecheck .
```

It finds the AGENTS.md, extracts checkable rules from it, evaluates each rule against the actual repository, computes dimension scores and a composite Vibecheck Score, and prints the results.

v0.1 is static analysis only — no LLM calls, no external APIs, no network access. It runs offline in under 2 seconds on any repo.

---

## 2. Core Loop

```
Find AGENTS.md → Extract Rules → Evaluate Rules → Score Dimensions → Composite Score → Output
```

Each step has a single responsibility:

1. **Find** — Locate `AGENTS.md` (or `CLAUDE.md` symlink) in the repo root. Fail clearly if not found.
2. **Extract** — Parse the markdown into a list of typed `Rule` objects with check parameters.
3. **Evaluate** — Run each rule's check against the filesystem. Return `pass`, `fail`, `warn`, or `skip`.
4. **Score** — Group results by dimension, compute weighted dimension scores.
5. **Composite** — Weighted average of dimension scores = Vibecheck Score (0.0 - 1.0).
6. **Output** — Print to terminal (default, verbose, very verbose) or JSON to stdout.

---

## 3. Package Structure

```
vibecheck/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── vibecheck/
│       ├── __init__.py        # Public API: evaluate(), __version__
│       ├── models.py          # Data classes: Rule, MetricResult, DimensionScore, VibecheckReport
│       ├── extractor.py       # AGENTS.md → list[Rule]
│       ├── collectors.py      # Rule × repo → MetricResult (static checks)
│       ├── scorer.py          # list[MetricResult] → VibecheckReport
│       └── cli.py             # CLI entry point
├── tests/
│   ├── conftest.py            # Shared fixtures (temp repos, sample AGENTS.md)
│   ├── fixtures/              # Sample AGENTS.md files + expected repo structures
│   │   ├── fastapi/
│   │   │   ├── AGENTS.md      # FastAPI VibeOps blueprint rules
│   │   │   └── repo/          # Minimal repo that should score high
│   │   ├── java/
│   │   │   ├── AGENTS.md      # Java/Maven/Lambda rules
│   │   │   └── repo/
│   │   └── minimal/
│   │       ├── AGENTS.md      # Tiny AGENTS.md (5-6 rules)
│   │       └── repo/
│   ├── test_extractor.py
│   ├── test_collectors.py
│   ├── test_scorer.py
│   └── test_cli.py
└── .github/
    └── workflows/
        └── ci.yml             # Test on push
```

---

## 4. Data Models (`models.py`)

### RuleCategory

Enum of evaluation dimensions:

```python
class RuleCategory(str, Enum):
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    TESTING = "testing"
    CODE_QUALITY = "code_quality"
    SPEC_ADHERENCE = "spec_adherence"
    BUILD = "build"         # informational, weight=0 in composite
```

### RuleType

How the rule is verified:

```python
class RuleType(str, Enum):
    FILE_EXISTS = "file_exists"
    FILE_NOT_EXISTS = "file_not_exists"
    FILE_CONTAINS = "file_contains"
    DIR_STRUCTURE = "dir_structure"
    PATTERN_USAGE = "pattern_usage"
    PATTERN_ABSENCE = "pattern_absence"
    DEPENDENCY_CHECK = "dependency_check"
    COMMAND_CHECK = "command_check"
    CONVENTION = "convention"
    LLM_JUDGE = "llm_judge"           # skipped in v0.1
```

### Rule

A single checkable assertion extracted from AGENTS.md:

```python
@dataclass
class Rule:
    id: str                    # Unique identifier (e.g. "arch_layered")
    category: RuleCategory
    rule_type: RuleType
    description: str           # Human-readable (e.g. "Layered architecture enforced")
    check_params: dict         # Type-specific parameters for the collector
    weight: float = 1.0        # Relative importance within its category
    source_text: str = ""      # Original text from AGENTS.md that generated this rule
```

### CheckResult

```python
class CheckResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
```

### MetricResult

Result of evaluating one rule:

```python
@dataclass
class MetricResult:
    rule_id: str
    rule: Rule
    result: CheckResult
    score: float              # 0.0 - 1.0
    evidence: str             # What was found or not found
    details: dict             # Additional structured data
```

### DimensionScore

Score for one evaluation dimension:

```python
@dataclass
class DimensionScore:
    category: RuleCategory
    score: float              # 0.0 - 1.0 (weighted average of rule scores in this dimension)
    weight: float             # Weight in composite (e.g. 0.30 for architecture)
    checks_passed: int
    checks_failed: int
    checks_warned: int
    checks_skipped: int
    results: list[MetricResult]
```

### VibecheckReport

Complete evaluation:

```python
@dataclass
class VibecheckReport:
    composite_score: float
    dimensions: dict[str, DimensionScore]
    rules_extracted: int
    rules_evaluated: int
    rules_passed: int
    rules_failed: int
    agents_md_path: str
    repo_path: str

    def to_dict(self) -> dict:
        """JSON-serializable dict."""

    def to_mlflow_metrics(self) -> dict[str, float]:
        """Flat dict for mlflow.log_metrics() — future use."""
```

---

## 5. Extractor (`extractor.py`)

### Input
Path to an AGENTS.md file.

### Output
`list[Rule]` — all checkable rules extracted from the document.

### Strategy

Parse the markdown into sections (split on `## `). For each section, run pattern-based extractors that recognise common rule shapes. Each extractor returns zero or more `Rule` objects.

Deduplicate by `rule.id` — first extraction wins.

### Rule Patterns to Extract in v0.1

These are the patterns the extractor must recognise. Each maps natural language in AGENTS.md to a typed `Rule`.

**Build / Environment:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "uses uv" / "uses maven" / "uses npm" | `build_{pm}` | Presence of lock file or config (uv.lock, pom.xml, package-lock.json) |
| "NOT pip" / "never use pip" | `build_no_{tool}` | Absence of requirements.txt |

**Architecture:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "Router → Service → Repository" or similar layered pattern | `arch_layered` | directories named services/, repositories/ (or service/, repository/) exist under src/ or project root |
| "dependency injection" | `arch_di` | Pattern `Depends(` or `@Inject` or `@inject` in source files |
| "/api/v1" or "versioned API" | `arch_api_versioning` | Pattern `/api/v1` or `/api/v2` in source files |
| "async" / "async-first" | `arch_async` | Pattern `async def` or `async function` in source files |
| "Pydantic Settings" / "BaseSettings" | `arch_pydantic_settings` | Pattern `BaseSettings` in source files |
| "Alembic" / "migration" | `arch_alembic` | Directory `alembic/` or `migrations/` exists |
| "Makefile" | `arch_makefile` | File `Makefile` exists |
| "Docker" | `arch_docker` | File `Dockerfile` or `docker-compose.yml` exists (check nested in `docker/` too) |
| "OpenAPI" | `arch_openapi` | File matching `openapi.yaml` or `openapi.json` exists |
| "hexagonal" / "onion" / "ports and adapters" | `arch_hexagonal` | Directories: domain/, application/, infrastructure/ |
| "JPMS" / "module-info.java" | `arch_jpms` | File `module-info.java` exists somewhere in source tree |
| Directory tree in code block (with │├└─ characters) | `struct_{name}` | Each entry in the tree is checked as file_exists (weight: 0.5) |

**Security:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "authenticated by default" / "JWT" / "all endpoints authenticated" | `sec_auth` | Patterns: jwt, JWT, verify_token, get_current_user, Bearer, OAuth |
| "no secrets in source" / "never commit secrets" | `sec_no_secrets` | Absence of patterns like `password = "...`, `secret = "...`, `sk-ant-` in source files (exclude tests, .md, .example files) |
| ".env in gitignore" | `sec_env_gitignore` | .gitignore contains `.env` |
| "bcrypt" / "password hashing" | `sec_password_hashing` | Pattern: bcrypt, argon2, hashpw, hash_password |
| "role-based" / "RBAC" / "authorization" | `sec_rbac` | Pattern: role, permission, is_admin, authorize |

**Testing:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "unit test" / "tests/unit" | `test_unit_dir` | Directory tests/unit/ or test/unit/ exists |
| "integration test" / "tests/integration" | `test_integration_dir` | Directory tests/integration/ or test/integration/ exists |
| "BDD" / "Gherkin" / ".feature" / "pytest-bdd" / "Cucumber" | `test_bdd` | Any .feature file exists in the repo |
| "conftest" / "fixtures" | `test_conftest` | File tests/conftest.py exists |
| "never delete tests" / "never skip tests" | `test_no_skip` | Absence of `@pytest.mark.skip` and `pytest.skip(` in test files |
| "component test" / "contract test" / "Pact" | `test_component` | Directory tests/component/ or similar exists |

**Code Quality:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "ruff" / "eslint" / "flake8" / other linter names | `qual_{linter}` | Package name in pyproject.toml / requirements.txt / package.json |
| "mypy" / "pyright" / "typescript" | `qual_{checker}` | Package name in dependency files |
| "Mapped[" (SQLAlchemy 2.0) | `qual_sqlalchemy_mapped` | Pattern `Mapped[` in source files |
| "model_validate" / "model_dump" (Pydantic v2) | `qual_pydantic_v2` | Pattern `model_validate` or `model_dump` in source files |

**Spec Adherence:**

| AGENTS.md pattern | Rule ID | Check |
|---|---|---|
| "specs/" / "spec-first" / "technical design" | `spec_dir` | Directory specs/ exists |
| "ADR" / "architecture decision" | `spec_adr` | Directory specs/adr/ or adr/ exists |
| "Gherkin before code" / "spec gate" | `spec_gherkin_first` | Any .feature file exists |
| "conventional commits" | `spec_conventional_commits` | Recent git commits match `type(scope): description` pattern |

**Meta (always added):**

| Rule ID | Check |
|---|---|
| `meta_agents_md` | AGENTS.md exists in repo (weight: 2.0) |

### Directory Tree Extraction

AGENTS.md files often contain a directory tree in a fenced code block:

```
├── src/
│   ├── services/
│   └── models/
├── tests/
└── Makefile
```

The extractor must:
1. Find fenced code blocks containing tree-drawing characters (│├└─)
2. Extract entries that look like file/directory names (not comment text)
3. Create `file_exists` rules with weight 0.5 for each

**Filter out noise:** Reject entries that start with uppercase (likely comments), are common English words, or are shorter than 2 characters.

### What the Extractor Does NOT Do in v0.1

- No LLM-based extraction
- No understanding of section semantics (e.g. "Section 5 = hard constraints" doesn't affect rule weight)
- No cross-reference between sections
- No extraction from skills files (`.claude/skills/`)

---

## 6. Collectors (`collectors.py`)

Each collector is a function: `(Rule, repo_path) → MetricResult`

### file_exists

Check if a path exists. Search in repo root first, then common subdirectories (src/, app/, lib/, tests/).

`check_params`: `{"path": "alembic"}` or `{"path": "tests/bdd/features", "glob": "*.feature"}`

If `glob` is specified, the directory must exist AND contain matching files.

### file_not_exists

Check that a path does NOT exist.

`check_params`: `{"path": "requirements.txt"}`

### file_contains

Check that a specific file contains a regex pattern.

`check_params`: `{"file": ".gitignore", "pattern": "\\.env"}`

### dir_structure

Check that expected directories exist (for layered architecture checks). Pass if at least half of the required directories are found.

`check_params`: `{"required_dirs": ["services", "repositories"]}`

Search in repo root AND common source directories (src/, app/).

### pattern_usage

Check that at least one source file contains at least one of the given patterns. Search in source directories, exclude tests/venv/node_modules.

`check_params`: `{"patterns": ["Depends(", "@inject"]}`

### pattern_absence

Check that NO source file contains any of the forbidden patterns.

`check_params`: `{"forbidden_patterns": ["password = \"", "sk-ant-"], "exclude_files": ["*.md", "*.example", "tests/*"]}`

### dependency_check

Check if a package name appears in dependency files (pyproject.toml, requirements.txt, pom.xml, package.json).

`check_params`: `{"package": "ruff"}`

### command_check

Check if a package manager is used by looking for its lock/config files.

`check_params`: `{"package_manager": "uv"}` → check for uv.lock

### convention

Check naming/structural conventions.

`check_params`: `{"check": "no_skip_markers"}` → scan test files for @pytest.mark.skip
`check_params`: `{"check": "conventional_commits"}` → check recent git log

### Dispatcher

A `COLLECTORS` dict maps `RuleType → collector function`. The dispatcher calls the right collector, catches exceptions, and returns `SKIP` on error.

`LLM_JUDGE` rules return `SKIP` with evidence "Requires --full mode (not available in v0.1)".

---

## 7. Scorer (`scorer.py`)

### Dimension Scoring

Group `MetricResult`s by `rule.category`. For each dimension:

1. Filter out SKIP and NOT_APPLICABLE results
2. Compute weighted score: `sum(result.score × rule.weight) / sum(rule.weight)`
3. Count passed/failed/warned/skipped

### Composite Score

Default weights:

```python
WEIGHTS = {
    "architecture": 0.30,
    "security": 0.20,
    "testing": 0.20,
    "code_quality": 0.15,
    "spec_adherence": 0.15,
    "build": 0.00,       # informational only
}
```

Composite = weighted average of dimension scores, using only dimensions that have at least one scorable rule.

### Public API

```python
def evaluate(
    repo_path: str | Path,
    agents_md_path: str | Path | None = None,
) -> VibecheckReport:
```

This is the main entry point. It runs the full pipeline and returns a report.

---

## 8. CLI (`cli.py`)

### Entry Point

```toml
# pyproject.toml
[project.scripts]
vibecheck = "vibecheck.cli:main"
```

### Arguments

```
vibecheck [path] [-v] [-vv] [--json] [--no-color] [--agents-md PATH] [--gate SCORE]
```

| Flag | Behaviour |
|---|---|
| `path` | Repo to evaluate (default: `.`) |
| `-v` | Show failed rules with evidence |
| `-vv` | Show all rules (passed and failed) |
| `--json` | JSON to stdout, no formatting |
| `--no-color` | Disable ANSI colors |
| `--agents-md PATH` | Explicit AGENTS.md location |
| `--gate SCORE` | Exit code 1 if composite score < SCORE |

### Default Output

```
  ⚡ Vibecheck 0.1.0
  ──────────────────────────────────────────────
  Score: 0.901
  ──────────────────────────────────────────────
  Architecture     ██████████████████░░  0.84  30%
  Security         █████████████████░░░  0.88  20%
  Testing          ████████████████████  1.00  20%
  Code Quality     ████████████████████  1.00  15%
  Spec Adherence   ████████████████░░░░  0.83  15%
  ──────────────────────────────────────────────
  64 rules · 52 passed · 10 failed · 2 skipped
```

### Exit Codes

- 0: Score >= 0.5 (or >= `--gate` threshold)
- 1: Score < 0.5 (or < `--gate` threshold)
- 2: No AGENTS.md found

### No AGENTS.md

```
  ⚡ Vibecheck 0.1.0
  ──────────────────────────────────────────────
  No AGENTS.md found.
  ──────────────────────────────────────────────
  This repository has no VibeOps policy to evaluate against.
  Create an AGENTS.md to define your engineering standards.
  
  Learn more: https://github.com/nlauchande/vibeops
```

Exit code 2.

---

## 9. Test Plan

### Fixtures

Three sample AGENTS.md files with matching minimal repos:

**fixtures/minimal/**
- AGENTS.md: ~20 lines. States: uses uv, has tests directory, has Makefile.
- repo/: Contains uv.lock, pyproject.toml, tests/, Makefile.
- Expected: 5-6 rules, all passing, score ~1.0.

**fixtures/fastapi/**
- AGENTS.md: Subset of the real fastapi-vibeops-blueprint AGENTS.md (~50 lines). States: uv, layered architecture, async, Pydantic Settings, JWT auth, bcrypt, BDD/Gherkin, ruff, mypy, specs directory, no hardcoded secrets.
- repo/: Minimal directory structure matching the blueprint (src/api/v1/, src/services/, src/repositories/, src/core/security.py with bcrypt, tests/unit/, tests/bdd/features/auth.feature, alembic/, specs/, Makefile, .gitignore with .env).
- Expected: ~25 rules, ~22 passing, score ~0.88.

**fixtures/java/**
- AGENTS.md: Subset of the Java hexagonal AGENTS.md (~40 lines). States: Maven, JPMS, hexagonal architecture, domain/application/infrastructure modules, Guice DI, Gherkin for component tests, Terraform.
- repo/: Minimal structure (pom.xml, domain/src/main/java/module-info.java, application/, infrastructure/, terraform/, specs/).
- Expected: ~20 rules, ~17 passing, score ~0.85.

### Test Cases

**test_extractor.py:**
- `test_extract_minimal` — correct number of rules, correct IDs, correct categories
- `test_extract_fastapi` — detects layered architecture, auth, BDD, linting rules
- `test_extract_java` — detects JPMS, hexagonal, Maven rules
- `test_extract_no_rules` — empty AGENTS.md returns only `meta_agents_md`
- `test_extract_deduplication` — same rule mentioned twice → extracted once
- `test_extract_tree_parsing` — directory tree in code block → file_exists rules
- `test_extract_tree_noise_filtering` — comments in tree are not extracted as paths

**test_collectors.py:**
- `test_file_exists_direct` — file at repo root
- `test_file_exists_nested` — file under src/
- `test_file_exists_missing` — returns FAIL
- `test_file_exists_glob` — directory exists but no matching files → FAIL
- `test_pattern_usage_found` — pattern in source file → PASS
- `test_pattern_usage_missing` — pattern not in any file → FAIL
- `test_pattern_usage_excludes_venv` — pattern in .venv/ is ignored
- `test_pattern_absence_clean` — no forbidden patterns → PASS
- `test_pattern_absence_violation` — forbidden pattern found → FAIL with location
- `test_file_contains_match` — .gitignore contains .env → PASS
- `test_file_contains_no_match` — pattern not in file → FAIL
- `test_dependency_check_pyproject` — finds package in pyproject.toml
- `test_dependency_check_pom` — finds package in pom.xml
- `test_llm_judge_skipped` — LLM_JUDGE rule returns SKIP

**test_scorer.py:**
- `test_composite_all_passing` — score is 1.0
- `test_composite_all_failing` — score is 0.0
- `test_composite_weights` — architecture (30%) failure weighted more than code_quality (15%)
- `test_dimension_skipped_excluded` — skipped rules don't affect dimension score
- `test_empty_dimension` — dimension with no rules doesn't affect composite
- `test_rule_weight` — rule with weight=2.0 counts double

**test_cli.py:**
- `test_default_output` — contains score, dimension bars, rule count
- `test_verbose_shows_failures` — `-v` shows failed rules
- `test_json_output` — `--json` produces valid JSON with vibecheck_score key
- `test_no_agents_md` — exit code 2, message about missing AGENTS.md
- `test_gate_pass` — `--gate 0.5` with score 0.8 → exit 0
- `test_gate_fail` — `--gate 0.9` with score 0.8 → exit 1

**Integration:**
- `test_full_pipeline_fastapi` — run evaluate() on fastapi fixture, verify score is 0.85-0.95
- `test_full_pipeline_java` — run evaluate() on java fixture, verify score is 0.80-0.90
- `test_full_pipeline_no_agents_md` — run evaluate() on repo without AGENTS.md, verify score is 0.0

---

## 10. pyproject.toml

```toml
[project]
name = "vibecheck"
version = "0.1.0"
description = "AGENTS.md-driven codebase evaluation"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "Natu Lauchande"}]
keywords = ["vibeops", "agents", "evaluation", "code-quality"]

# Zero required dependencies for v0.1
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]

[project.scripts]
vibecheck = "vibecheck.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vibecheck"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Zero runtime dependencies. Python stdlib only. This is deliberate — vibecheck should install instantly and never conflict with anything.

---

## 11. Performance Constraints

- Full evaluation must complete in **under 2 seconds** on a repo with 500 files.
- The extractor must handle AGENTS.md files up to 2000 lines without timeout.
- No regex that can catastrophically backtrack — test with adversarial inputs.
- File reading must skip binary files gracefully (catch UnicodeDecodeError).

---

## 12. Not In Scope for v0.1

- MLflow integration
- Jev / LLM judge integration
- `--diff` mode
- `--watch` mode
- `--pre-commit` mode
- Skills extraction (`.claude/skills/`)
- AGENTS.md generation (`vibecheck init`)
- GitHub Action
- Config file (vibecheck.toml)
- Custom weights override
- AST-level analysis
- Any network access

---

## 13. Implementation Order

1. `models.py` — data classes only, no logic
2. Test fixtures — create the 3 sample AGENTS.md + repo directories
3. `extractor.py` + `test_extractor.py` — extract rules, test against fixtures
4. `collectors.py` + `test_collectors.py` — evaluate rules, test each collector
5. `scorer.py` + `test_scorer.py` — compute scores, test weighting
6. `cli.py` + `test_cli.py` — wire it together, test output formats
7. Integration tests — full pipeline against all 3 fixtures
8. `pyproject.toml` + README.md — packaging and install verification

Run `pytest` after each step. Do not proceed to the next step with failing tests.

---

## 14. README.md

The README should contain:

- One-line description: "Evaluate a codebase against its AGENTS.md policy."
- Install: `pip install vibecheck` or `uv add vibecheck`
- Usage: `vibecheck .` with example output
- What it checks (the 5 dimensions)
- How it works (1 paragraph: extracts rules from AGENTS.md, evaluates statically, scores)
- Link to VibeOps framework
- License: MIT
