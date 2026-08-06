import pytest

from backend.services.product_recognition_calibration_runner import _eligibility


def metric(rate):
    return {"count": 1, "denominator": 1, "rate": rate}


def base_metrics():
    return {
        "decision_accuracy": metric(0.5),
        "false_positives": metric(0.0),
        "restricted_candidate_accuracy": metric(1.0),
        "canonical_match_accuracy": metric(1.0),
        "alias_match_accuracy": metric(1.0),
        "latency_p95": 10.0,
    }


def criteria():
    return {
        "primary_metric": "decision_accuracy",
        "required_improvement": 0.1,
        "false_positive_tolerance": 0.1,
        "latency_budget": 20.0,
    }


def test_missing_eligibility_inputs_are_pending():
    result = _eligibility(base_metrics(), base_metrics(), None)
    assert result == {
        "status": "pending",
        "reasons": [
            "missing_primary_metric",
            "missing_required_improvement",
            "missing_false_positive_tolerance",
            "missing_latency_budget",
        ],
    }


def test_complete_eligibility_can_pass():
    fuzzy = base_metrics()
    hybrid = base_metrics()
    hybrid["decision_accuracy"] = metric(0.7)
    hybrid["commerce_isolation"] = {"passed": True}
    assert _eligibility(fuzzy, hybrid, criteria()) == {"status": "eligible", "reasons": []}


@pytest.mark.parametrize(
    "field, reason",
    [
        ("decision_accuracy", "primary_metric_improvement_failed"),
        ("false_positives", "false_positive_tolerance_failed"),
        ("restricted_candidate_accuracy", "restricted_candidate_non_regression_failed"),
        ("canonical_match_accuracy", "canonical_match_accuracy_failed"),
        ("alias_match_accuracy", "alias_match_accuracy_failed"),
        ("latency_p95", "latency_budget_failed"),
    ],
)
def test_failed_eligibility_gate_has_stable_reason(field, reason):
    fuzzy = base_metrics()
    hybrid = base_metrics()
    if field == "decision_accuracy":
        hybrid[field] = metric(0.5)
    elif field == "false_positives":
        hybrid[field] = metric(0.2)
    elif field == "restricted_candidate_accuracy" or field in {"canonical_match_accuracy", "alias_match_accuracy"}:
        hybrid[field] = metric(0.0)
    elif field == "latency_p95":
        hybrid[field] = 30.0
    hybrid["commerce_isolation"] = {"passed": True}
    result = _eligibility(fuzzy, hybrid, criteria())
    assert result["status"] == "not_eligible"
    assert reason in result["reasons"]
