# Vibecheck

Evaluate a codebase against its AGENTS.md policy.

## Install

```bash
pip install git+https://github.com/vibeops-central/vibecheck
```

The package is named `vibeops-check` and installs the `vibecheck` command. It is not on
PyPI yet; the `vibecheck` name there belongs to an unrelated project.

## Usage

```bash
vibecheck .
```

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

Options:

| Flag | Behaviour |
|---|---|
| `path` | Repo to evaluate (default: `.`) |
| `-v` | Show failed rules with evidence |
| `-vv` | Show all rules |
| `--json` | JSON to stdout |
| `--no-color` | Disable ANSI colors |
| `--agents-md PATH` | Explicit AGENTS.md location |
| `--gate SCORE` | Exit 1 if the score is below SCORE (default 0.5) |

Exit codes: `0` score at or above the gate, `1` below it, `2` no AGENTS.md found.

## What it checks

Rules are grouped into five weighted dimensions:

- **Architecture** (30%) — layering, DI, async, migrations, Docker, declared directory trees
- **Security** (20%) — auth, password hashing, RBAC, no committed secrets, `.env` ignored
- **Testing** (20%) — unit/integration/component test dirs, BDD, conftest, no skipped tests
- **Code Quality** (15%) — linters, type checkers, SQLAlchemy 2.0 / Pydantic v2 idioms
- **Spec Adherence** (15%) — `specs/`, ADRs, Gherkin-first, conventional commits

Build rules (package manager checks) are reported but carry no weight.

## How it works

Vibecheck finds your `AGENTS.md`, extracts the checkable rules it declares using pattern
matching, evaluates each one statically against the repository's files, and combines the
results into per-dimension scores and a composite Vibecheck Score (0.0 – 1.0). v0.1 is
static only: no LLM calls, no network access, no runtime dependencies.

## Checking a skill

Vibecheck scores your own codebase. To vet an agent skill before you install it, use
[vibeskill](https://github.com/vibeops-central/vibeskill).

## Python API

```python
from vibecheck import evaluate

report = evaluate(".")
print(report.composite_score)
```

## Learn more

Part of the [VibeOps](https://github.com/nlauchande/vibeops) framework.

## License

MIT
