from vibecheck.models import CheckResult, MetricResult, Rule, RuleCategory, RuleType
from vibecheck.scorer import build_report


def mr(category, result, weight=1.0, rid="r"):
    rule = Rule(rid, category, RuleType.FILE_EXISTS, "d", {}, weight)
    score = {CheckResult.PASS: 1.0, CheckResult.FAIL: 0.0, CheckResult.WARN: 0.5, CheckResult.SKIP: 0.0}[result]
    return MetricResult(rid, rule, result, score, "")


ALL = [
    RuleCategory.ARCHITECTURE,
    RuleCategory.SECURITY,
    RuleCategory.TESTING,
    RuleCategory.CODE_QUALITY,
    RuleCategory.SPEC_ADHERENCE,
]


def test_composite_all_passing():
    report = build_report([mr(c, CheckResult.PASS) for c in ALL])
    assert report.composite_score == 1.0


def test_composite_all_failing():
    report = build_report([mr(c, CheckResult.FAIL) for c in ALL])
    assert report.composite_score == 0.0


def test_composite_weights():
    fail_arch = [mr(c, CheckResult.FAIL if c == RuleCategory.ARCHITECTURE else CheckResult.PASS) for c in ALL]
    fail_quality = [mr(c, CheckResult.FAIL if c == RuleCategory.CODE_QUALITY else CheckResult.PASS) for c in ALL]
    a = build_report(fail_arch).composite_score
    q = build_report(fail_quality).composite_score
    assert abs(a - 0.70) < 1e-9
    assert abs(q - 0.85) < 1e-9
    assert a < q


def test_dimension_skipped_excluded():
    results = [
        mr(RuleCategory.SECURITY, CheckResult.PASS, rid="a"),
        mr(RuleCategory.SECURITY, CheckResult.SKIP, rid="b"),
    ]
    report = build_report(results)
    dim = report.dimensions["security"]
    assert dim.score == 1.0
    assert (dim.checks_passed, dim.checks_skipped) == (1, 1)
    assert report.rules_skipped == 1 and report.rules_evaluated == 1


def test_empty_dimension():
    # Testing has only skipped rules -> excluded from composite entirely.
    results = [
        mr(RuleCategory.ARCHITECTURE, CheckResult.PASS),
        mr(RuleCategory.TESTING, CheckResult.SKIP),
    ]
    assert build_report(results).composite_score == 1.0
    assert build_report([]).composite_score == 0.0


def test_rule_weight():
    results = [
        mr(RuleCategory.ARCHITECTURE, CheckResult.PASS, weight=2.0, rid="a"),
        mr(RuleCategory.ARCHITECTURE, CheckResult.FAIL, weight=1.0, rid="b"),
    ]
    dim = build_report(results).dimensions["architecture"]
    assert abs(dim.score - 2 / 3) < 1e-9


def test_build_dimension_is_informational():
    results = [mr(RuleCategory.ARCHITECTURE, CheckResult.PASS), mr(RuleCategory.BUILD, CheckResult.FAIL)]
    report = build_report(results)
    assert report.composite_score == 1.0
    assert report.dimensions["build"].score == 0.0


def test_dimension_order_is_stable():
    results = [mr(c, CheckResult.PASS) for c in reversed(ALL)]
    assert list(build_report(results).dimensions) == [c.value for c in ALL]


def test_report_serialization():
    report = build_report([mr(RuleCategory.SECURITY, CheckResult.PASS)])
    d = report.to_dict()
    assert d["vibecheck_score"] == 1.0
    assert d["dimensions"]["security"]["results"][0]["result"] == "pass"
    assert report.to_mlflow_metrics()["vibecheck_security"] == 1.0
