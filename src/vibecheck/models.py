"""Data classes for Vibecheck."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuleCategory(str, Enum):
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    TESTING = "testing"
    CODE_QUALITY = "code_quality"
    SPEC_ADHERENCE = "spec_adherence"
    BUILD = "build"  # informational, weight=0 in composite


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
    LLM_JUDGE = "llm_judge"  # skipped in v0.1


class CheckResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class Rule:
    id: str
    category: RuleCategory
    rule_type: RuleType
    description: str
    check_params: dict = field(default_factory=dict)
    weight: float = 1.0
    source_text: str = ""


@dataclass
class MetricResult:
    rule_id: str
    rule: Rule
    result: CheckResult
    score: float
    evidence: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class DimensionScore:
    category: RuleCategory
    score: float
    weight: float
    checks_passed: int
    checks_failed: int
    checks_warned: int
    checks_skipped: int
    results: list[MetricResult] = field(default_factory=list)


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
    rules_skipped: int = 0
    rules_warned: int = 0

    def to_dict(self) -> dict:
        """JSON-serializable dict."""
        from . import __version__

        return {
            "vibecheck_score": round(self.composite_score, 4),
            "version": __version__,
            "agents_md_path": self.agents_md_path,
            "repo_path": self.repo_path,
            "rules_extracted": self.rules_extracted,
            "rules_evaluated": self.rules_evaluated,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "rules_warned": self.rules_warned,
            "rules_skipped": self.rules_skipped,
            "dimensions": {
                name: {
                    "score": round(d.score, 4),
                    "weight": d.weight,
                    "passed": d.checks_passed,
                    "failed": d.checks_failed,
                    "warned": d.checks_warned,
                    "skipped": d.checks_skipped,
                    "results": [
                        {
                            "rule_id": r.rule_id,
                            "description": r.rule.description,
                            "result": r.result.value,
                            "score": r.score,
                            "weight": r.rule.weight,
                            "evidence": r.evidence,
                        }
                        for r in d.results
                    ],
                }
                for name, d in self.dimensions.items()
            },
        }

    def to_mlflow_metrics(self) -> dict[str, float]:
        """Flat dict for mlflow.log_metrics() — future use."""
        metrics: dict[str, float] = {"vibecheck_score": self.composite_score}
        for name, d in self.dimensions.items():
            metrics[f"vibecheck_{name}"] = d.score
        return metrics
