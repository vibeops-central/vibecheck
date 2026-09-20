import time

from vibecheck import evaluate


def test_full_pipeline_minimal(fixture_repo):
    report = evaluate(fixture_repo("minimal"))
    assert report.rules_extracted == 6
    assert report.rules_failed == 0
    assert report.composite_score == 1.0


def test_full_pipeline_fastapi(fixture_repo):
    report = evaluate(fixture_repo("fastapi"))
    assert 0.85 <= report.composite_score <= 0.95, report.composite_score
    failed = {r.rule_id for d in report.dimensions.values() for r in d.results if r.result.value == "fail"}
    assert failed == {"test_integration_dir", "arch_openapi", "spec_adr"}


def test_full_pipeline_java(fixture_repo):
    report = evaluate(fixture_repo("java"))
    assert 0.80 <= report.composite_score <= 0.90, report.composite_score
    failed = {r.rule_id for d in report.dimensions.values() for r in d.results if r.result.value == "fail"}
    assert failed == {"qual_spotbugs", "spec_adr"}


def test_full_pipeline_no_agents_md(tmp_path):
    report = evaluate(tmp_path)
    assert report.composite_score == 0.0
    assert report.rules_extracted == 0


def test_evaluate_is_fast(fixture_repo, tmp_path):
    repo = fixture_repo("fastapi")
    for i in range(500):
        sub = repo / "src" / f"pkg{i % 20}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"m{i}.py").write_text("def f():\n    return 1\n" * 20)
    start = time.perf_counter()
    evaluate(repo)
    assert time.perf_counter() - start < 2.0
