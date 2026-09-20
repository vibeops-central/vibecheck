"""list[MetricResult] -> VibecheckReport."""

from __future__ import annotations

from pathlib import Path

from .collectors import collect_all
from .extractor import extract_rules, find_agents_md
from .models import CheckResult, DimensionScore, MetricResult, RuleCategory, VibecheckReport

WEIGHTS: dict[str, float] = {
    "architecture": 0.30,
    "security": 0.20,
    "testing": 0.20,
    "code_quality": 0.15,
    "spec_adherence": 0.15,
    "build": 0.00,  # informational only
}


def score_dimension(category: RuleCategory, results: list[MetricResult]) -> DimensionScore:
    scorable = [r for r in results if r.result != CheckResult.SKIP]
    total_weight = sum(r.rule.weight for r in scorable)
    score = sum(r.score * r.rule.weight for r in scorable) / total_weight if total_weight else 0.0
    count = lambda kind: sum(1 for r in results if r.result == kind)  # noqa: E731
    return DimensionScore(
        category=category,
        score=score,
        weight=WEIGHTS.get(category.value, 0.0),
        checks_passed=count(CheckResult.PASS),
        checks_failed=count(CheckResult.FAIL),
        checks_warned=count(CheckResult.WARN),
        checks_skipped=count(CheckResult.SKIP),
        results=results,
    )


def build_report(
    results: list[MetricResult],
    agents_md_path: str = "",
    repo_path: str = "",
    rules_extracted: int | None = None,
) -> VibecheckReport:
    grouped: dict[RuleCategory, list[MetricResult]] = {}
    for r in results:
        grouped.setdefault(r.rule.category, []).append(r)

    order = {name: i for i, name in enumerate(WEIGHTS)}
    dimensions = {
        cat.value: score_dimension(cat, rs)
        for cat, rs in sorted(grouped.items(), key=lambda kv: order.get(kv[0].value, len(order)))
    }

    # Composite: only dimensions with a scorable rule and non-zero weight.
    weighted = [
        (d.score, d.weight)
        for d in dimensions.values()
        if d.weight > 0 and (d.checks_passed + d.checks_failed + d.checks_warned) > 0
    ]
    total_weight = sum(w for _, w in weighted)
    composite = sum(s * w for s, w in weighted) / total_weight if total_weight else 0.0

    count = lambda kind: sum(1 for r in results if r.result == kind)  # noqa: E731
    skipped = count(CheckResult.SKIP)
    return VibecheckReport(
        composite_score=composite,
        dimensions=dimensions,
        rules_extracted=len(results) if rules_extracted is None else rules_extracted,
        rules_evaluated=len(results) - skipped,
        rules_passed=count(CheckResult.PASS),
        rules_failed=count(CheckResult.FAIL),
        agents_md_path=agents_md_path,
        repo_path=repo_path,
        rules_skipped=skipped,
        rules_warned=count(CheckResult.WARN),
    )


def evaluate(
    repo_path: str | Path,
    agents_md_path: str | Path | None = None,
) -> VibecheckReport:
    """Run the full pipeline. Returns a zero-score report if no AGENTS.md exists."""
    repo = Path(repo_path)
    agents = Path(agents_md_path) if agents_md_path else find_agents_md(repo)
    if agents is None or not agents.is_file():
        return build_report([], "", str(repo), rules_extracted=0)

    rules = extract_rules(agents)
    results = collect_all(rules, repo)
    return build_report(results, str(agents), str(repo), rules_extracted=len(rules))
