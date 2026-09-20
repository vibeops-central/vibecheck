from vibecheck.collectors import collect
from vibecheck.models import CheckResult, Rule, RuleCategory, RuleType


def rule(rule_type, **params):
    return Rule("r", RuleCategory.ARCHITECTURE, rule_type, "test rule", params)


def test_file_exists_direct(make_repo):
    repo = make_repo({"Makefile": "all:\n"})
    assert collect(rule(RuleType.FILE_EXISTS, path="Makefile"), repo).result == CheckResult.PASS


def test_file_exists_nested(make_repo):
    repo = make_repo({"src/alembic/env.py": ""})
    assert collect(rule(RuleType.FILE_EXISTS, path="alembic"), repo).result == CheckResult.PASS


def test_file_exists_missing(make_repo):
    repo = make_repo({"a.txt": ""})
    res = collect(rule(RuleType.FILE_EXISTS, path="Makefile"), repo)
    assert res.result == CheckResult.FAIL
    assert res.score == 0.0


def test_file_exists_glob(make_repo):
    repo = make_repo({"tests/bdd/features/readme.txt": ""})
    r = rule(RuleType.FILE_EXISTS, path="tests/bdd/features", glob="*.feature")
    assert collect(r, repo).result == CheckResult.FAIL
    (repo / "tests/bdd/features/a.feature").write_text("Feature: x")
    assert collect(r, repo).result == CheckResult.PASS


def test_file_exists_alternatives_and_find(make_repo):
    repo = make_repo({"docker/Dockerfile": "", "deep/er/module-info.java": ""})
    alt = rule(RuleType.FILE_EXISTS, path="Dockerfile", alternatives=["docker/Dockerfile"])
    assert collect(alt, repo).result == CheckResult.PASS
    assert collect(rule(RuleType.FILE_EXISTS, find=["module-info.java"]), repo).result == CheckResult.PASS


def test_file_exists_rejects_path_traversal(make_repo, tmp_path):
    (tmp_path / "outside.txt").write_text("x")
    repo = make_repo({"a.txt": ""})
    assert collect(rule(RuleType.FILE_EXISTS, path="../outside.txt"), repo).result == CheckResult.FAIL


def test_file_not_exists(make_repo):
    repo = make_repo({"pyproject.toml": ""})
    r = rule(RuleType.FILE_NOT_EXISTS, path="requirements.txt")
    assert collect(r, repo).result == CheckResult.PASS
    (repo / "requirements.txt").write_text("x")
    assert collect(r, repo).result == CheckResult.FAIL


def test_file_contains_match(make_repo):
    repo = make_repo({".gitignore": "node_modules\n.env\n"})
    r = rule(RuleType.FILE_CONTAINS, file=".gitignore", pattern=r"^\.env\b")
    assert collect(r, repo).result == CheckResult.PASS


def test_file_contains_no_match(make_repo):
    repo = make_repo({".gitignore": "node_modules\n"})
    r = rule(RuleType.FILE_CONTAINS, file=".gitignore", pattern=r"^\.env\b")
    assert collect(r, repo).result == CheckResult.FAIL
    assert collect(rule(RuleType.FILE_CONTAINS, file="missing", pattern="x"), repo).result == CheckResult.FAIL


def test_dir_structure(make_repo):
    repo = make_repo({"src/services/a.py": "", "src/repositories/b.py": ""})
    r = rule(RuleType.DIR_STRUCTURE, required_dirs=["services", "repositories"])
    res = collect(r, repo)
    assert res.result == CheckResult.PASS and res.score == 1.0


def test_dir_structure_half_passes_singular_names_accepted(make_repo):
    repo = make_repo({"service/a.py": ""})
    res = collect(rule(RuleType.DIR_STRUCTURE, required_dirs=["services", "repositories"]), repo)
    assert res.result == CheckResult.PASS and res.score == 0.5
    res = collect(rule(RuleType.DIR_STRUCTURE, required_dirs=["a", "b", "c"]), repo)
    assert res.result == CheckResult.FAIL


def test_pattern_usage_found(make_repo):
    repo = make_repo({"src/app.py": "async def handler():\n    pass\n"})
    res = collect(rule(RuleType.PATTERN_USAGE, patterns=["async def"]), repo)
    assert res.result == CheckResult.PASS
    assert "src/app.py" in res.evidence


def test_pattern_usage_missing(make_repo):
    repo = make_repo({"src/app.py": "def handler():\n    pass\n"})
    assert collect(rule(RuleType.PATTERN_USAGE, patterns=["async def"]), repo).result == CheckResult.FAIL


def test_pattern_usage_excludes_venv(make_repo):
    repo = make_repo(
        {
            ".venv/lib/x.py": "async def x(): ...",
            "node_modules/pkg/y.js": "async function y() {}",
            "tests/test_a.py": "async def t(): ...",
            "src/app.py": "print('hi')",
        }
    )
    res = collect(rule(RuleType.PATTERN_USAGE, patterns=["async def", "async function"]), repo)
    assert res.result == CheckResult.FAIL


def test_pattern_absence_clean(make_repo):
    repo = make_repo({"src/app.py": "import os\nkey = os.environ['KEY']\n"})
    r = rule(RuleType.PATTERN_ABSENCE, forbidden_patterns=[r"password\s*=\s*\"[^\"]+\"", "sk-ant-"])
    assert collect(r, repo).result == CheckResult.PASS


def test_pattern_absence_violation(make_repo):
    repo = make_repo({"src/app.py": "x = 1\npassword = \"hunter2\"\n"})
    r = rule(RuleType.PATTERN_ABSENCE, forbidden_patterns=[r"password\s*=\s*\"[^\"]+\""])
    res = collect(r, repo)
    assert res.result == CheckResult.FAIL
    assert "src/app.py:2" in res.evidence


def test_pattern_absence_respects_excludes(make_repo):
    repo = make_repo({"config.yml.example": "password: x", "src/app.py": "sk-ant-abcdefgh1234"})
    r = rule(
        RuleType.PATTERN_ABSENCE,
        forbidden_patterns=["sk-ant-"],
        exclude_files=["src/*"],
    )
    assert collect(r, repo).result == CheckResult.PASS


def test_dependency_check_pyproject(make_repo):
    repo = make_repo({"pyproject.toml": '[project]\ndependencies = ["ruff>=0.5"]\n'})
    assert collect(rule(RuleType.DEPENDENCY_CHECK, package="ruff"), repo).result == CheckResult.PASS
    assert collect(rule(RuleType.DEPENDENCY_CHECK, package="mypy"), repo).result == CheckResult.FAIL


def test_dependency_check_pom(make_repo):
    repo = make_repo(
        {"module/pom.xml": "<plugin><artifactId>maven-checkstyle-plugin</artifactId></plugin>"}
    )
    assert collect(rule(RuleType.DEPENDENCY_CHECK, package="checkstyle"), repo).result == CheckResult.PASS


def test_dependency_check_word_boundaries(make_repo):
    repo = make_repo({"requirements.txt": "blackbox==1.0\n"})
    assert collect(rule(RuleType.DEPENDENCY_CHECK, package="black"), repo).result == CheckResult.FAIL


def test_command_check(make_repo):
    repo = make_repo({"uv.lock": ""})
    assert collect(rule(RuleType.COMMAND_CHECK, package_manager="uv"), repo).result == CheckResult.PASS
    assert collect(rule(RuleType.COMMAND_CHECK, package_manager="maven"), repo).result == CheckResult.FAIL


def test_convention_no_skip_markers(make_repo):
    repo = make_repo({"tests/test_a.py": "def test_a():\n    assert True\n"})
    r = rule(RuleType.CONVENTION, check="no_skip_markers")
    assert collect(r, repo).result == CheckResult.PASS
    (repo / "tests/test_b.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_b():\n    pass\n")
    res = collect(r, repo)
    assert res.result == CheckResult.FAIL
    assert "tests/test_b.py:3" in res.evidence


def test_convention_skipif_is_not_skip(make_repo):
    repo = make_repo({"tests/test_a.py": "@pytest.mark.skipif(True, reason='x')\ndef test_a(): ...\n"})
    assert collect(rule(RuleType.CONVENTION, check="no_skip_markers"), repo).result == CheckResult.PASS


def test_convention_conventional_commits_skips_outside_git(make_repo):
    repo = make_repo({"a.txt": ""})
    res = collect(rule(RuleType.CONVENTION, check="conventional_commits"), repo)
    assert res.result == CheckResult.SKIP


def test_convention_conventional_commits_in_git(make_repo):
    import subprocess

    repo = make_repo({"a.txt": "x"})
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "PATH": __import__("os").environ["PATH"],
    }  # fmt: skip
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, env=env, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", ".")
    run("-c", "commit.gpgsign=false", "commit", "-q", "-m", "feat(core): add thing")
    r = rule(RuleType.CONVENTION, check="conventional_commits")
    assert collect(r, repo).result == CheckResult.PASS
    (repo / "b.txt").write_text("y")
    run("add", ".")
    run("-c", "commit.gpgsign=false", "commit", "-q", "-m", "did stuff")
    res = collect(r, repo)
    assert res.result == CheckResult.WARN and res.score == 0.5


def test_llm_judge_skipped(make_repo):
    repo = make_repo()
    res = collect(rule(RuleType.LLM_JUDGE), repo)
    assert res.result == CheckResult.SKIP
    assert "--full" in res.evidence


def test_dispatcher_catches_errors(make_repo):
    repo = make_repo({".gitignore": "x"})
    res = collect(rule(RuleType.FILE_CONTAINS, file=".gitignore", pattern="("), repo)  # bad regex
    assert res.result == CheckResult.SKIP
    assert "error" in res.evidence.lower()


def test_binary_files_skipped(make_repo):
    repo = make_repo()
    (repo / "blob.py").write_bytes(b"\xff\xfe\x00async def")
    assert collect(rule(RuleType.PATTERN_USAGE, patterns=["async def"]), repo).result == CheckResult.FAIL
