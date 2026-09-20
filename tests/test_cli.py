import json

import pytest

from vibecheck.cli import main


@pytest.fixture
def fastapi_repo(fixture_repo):
    return fixture_repo("fastapi")


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    return code, capsys.readouterr().out


def test_default_output(capsys, fastapi_repo):
    code, out = run(capsys, fastapi_repo, "--no-color")
    assert code == 0
    assert "Vibecheck 0.1.0" in out
    assert "Score: 0." in out
    assert "Architecture" in out and "█" in out
    assert "rules ·" in out and "passed" in out
    assert "\033[" not in out


def test_verbose_shows_failures(capsys, fastapi_repo):
    _, default = run(capsys, fastapi_repo, "--no-color")
    _, out = run(capsys, fastapi_repo, "-v", "--no-color")
    assert "Failed rules:" in out and "✗" in out
    assert "Failed rules:" not in default
    assert "✓" not in out  # -v hides passing rules


def test_very_verbose_shows_all(capsys, fastapi_repo):
    _, out = run(capsys, fastapi_repo, "-vv", "--no-color")
    assert "All rules:" in out and "✓" in out and "✗" in out


def test_json_output(capsys, fastapi_repo):
    code, out = run(capsys, fastapi_repo, "--json")
    data = json.loads(out)
    assert code == 0
    assert 0.0 <= data["vibecheck_score"] <= 1.0
    assert "architecture" in data["dimensions"]


def test_no_agents_md(capsys, tmp_path):
    code, out = run(capsys, tmp_path, "--no-color")
    assert code == 2
    assert "No AGENTS.md found" in out


def test_no_agents_md_json(capsys, tmp_path):
    code, out = run(capsys, tmp_path, "--json")
    assert code == 2
    assert "error" in json.loads(out)


def test_gate_pass(capsys, fastapi_repo):
    code, _ = run(capsys, fastapi_repo, "--gate", "0.5")
    assert code == 0


def test_gate_fail(capsys, fastapi_repo):
    code, _ = run(capsys, fastapi_repo, "--gate", "0.99")
    assert code == 1


def test_explicit_agents_md(capsys, tmp_path, fixtures_dir):
    repo = tmp_path / "bare"
    repo.mkdir()
    code, out = run(capsys, repo, "--agents-md", fixtures_dir / "minimal" / "AGENTS.md", "--json")
    assert code in (0, 1)
    assert json.loads(out)["rules_extracted"] == 6


def test_default_path_is_cwd(capsys, monkeypatch, fastapi_repo):
    monkeypatch.chdir(fastapi_repo)
    code, out = run(capsys, "--no-color")
    assert code == 0 and "Score:" in out
