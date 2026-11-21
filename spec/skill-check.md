# Vibecheck — Skill Check Spec

> **Status:** Implemented in `src/vibecheck/skill.py`
> **Scope:** Static check of one agent skill (a folder with a `SKILL.md`) before it is installed
> **Not in scope:** Running the skill, LLM calls, network access, marketplace lookups

---

## 1. Why

Skills run with the agent's permissions, and they are usually picked by star count or
habit. `vibecheck skill` gives a repeatable answer to "should this skill get in?" before
it does.

```
vibecheck skill path/to/skill
```

It follows the v0.1 rules: static analysis only, no dependencies, runs offline.

## 2. The questions

| Question | Covered | How |
|---|---|---|
| **Permissions**: what does it read, write, run and call? | Yes | Pattern scan of `SKILL.md` and every text file in the folder |
| **Version**: is it pinned, and has it changed? | Yes | One sha256 over every file, compared with a lock file |
| **Cost**: what does it add to the context? | Partly | Estimated tokens (characters ÷ 4). Real cost per task needs runs |
| **Proof**: does it help on my own work? | No | Needs paired agent runs (with and without the skill). Shown as not covered |

## 3. Checks

### Permissions (50%)

| Check | Severity | Flags |
|---|---|---|
| `pipe-to-shell` | high | `curl … \| sh`, `wget … \| bash`, `base64 -d \| sh` |
| `reads-credentials` | high | `~/.ssh`, private key names, `.aws/credentials`, `.netrc`, `.git-credentials`, reading `.env`, keychain lookups |
| `hidden-characters` | high | Zero-width characters (a leading byte-order mark is ignored) |
| `injection-phrases` | medium | "ignore previous instructions", "do not tell the user", "without telling the user" |
| `network-calls` | medium | `curl`, `wget`, `requests`, `urllib`, `httpx`, `fetch(`, `nc -` |
| `install-steps` | medium | Package installs, `npx`, `sudo`, `chmod +x` |
| `shell-exec` | medium | `rm -rf`, `eval`, `os.system`, `subprocess`, `child_process`, `exec(` |
| `agent-files` | medium | `CLAUDE.md`, `AGENTS.md`, `MEMORY.md`, `SOUL.md`, `IDENTITY.md`, `~/.claude`, `.cursorrules`, `~/.codex` |
| `declares-tools` | medium | No `allowed-tools` in the frontmatter |

`injection-phrases` is medium on purpose: a static scan cannot tell a skill that gives such
an instruction from one that quotes it as something to refuse.

### Version (30%)

| Check | Severity | Passes when |
|---|---|---|
| `frontmatter` | medium | `name` and `description` are present |
| `pinned` | high | The skill's hash matches its entry in the lock file |

The lock file is `skills.lock.json` next to the skill folder, or `--lock PATH`:

```json
{"version": 1, "skills": {"tidy-notes": {"sha256": "…"}}}
```

`--pin` writes the current hash. Pin after a human has reviewed the skill.

### Cost (20%)

| Check | Severity | Pass | Review | Fail |
|---|---|---|---|---|
| `skill-md-size` | high | ≤ 5,000 tokens | ≤ 10,000 | above |
| `bundle-size` | medium | ≤ 25,000 tokens | ≤ 60,000 | above |
| `description-size` | medium | ≤ 1,024 characters | above | — |

## 4. Scoring

- Each check scores 1.0 (pass), 0.5 (review) or 0.0 (fail). High-severity checks weigh 3,
  medium checks 1.
- A dimension's score is the weighted mean of its checks. The skill score is
  0.5 × permissions + 0.3 × version + 0.2 × cost.
- **Blocked:** any failed high-severity permission check, or a hash that differs from the
  pinned one, blocks the skill whatever its score. A skill that was never pinned is not
  blocked; it loses the `pinned` points.

## 5. CLI

| Flag | Behaviour |
|---|---|
| `path` | Skill folder or its `SKILL.md` (default: `.`) |
| `-v` / `-vv` | Show findings / all checks, with `file:line` evidence |
| `--json` | JSON to stdout |
| `--lock PATH` | Lock file location |
| `--pin` | Record the current hash, then check |
| `--gate SCORE` | Exit 1 below SCORE (default 0.5) |

Exit codes: `0` passes, `1` blocked or below the gate, `2` no `SKILL.md` found.

`vibecheck skill` is dispatched on the first argument. To evaluate a repository in a folder
that is itself named `skill`, pass `./skill`.

## 6. Known limits

- **Pattern matching.** It finds text, not behaviour. Obfuscated code can pass, and
  harmless mentions can be flagged for review. It supports a human review; it does not
  replace one.
- **Binary and large files** (over 1 MB) are hashed but not scanned.
- **Token counts are estimates.**

## 7. Later

- Proof: paired evals (same tasks with and without the skill), logged to MLflow.
- Cost per task from real runs.
- Checking a whole skills folder in one call.
