import json
from pathlib import Path

import pytest

from backend.services.product_recognition_calibration_report import (
    read_report,
    serialize_report,
    write_report_atomic,
)


def test_report_serialization_is_sorted_deterministic_and_safe():
    report = {"z": [1, 2], "a": {"value": 1.0}}
    first = serialize_report(report)
    second = serialize_report({"a": {"value": 1.0}, "z": [1, 2]})
    assert first == second
    assert json.loads(first) == report
    with pytest.raises(ValueError):
        serialize_report({"vectors": [1.0]})
    with pytest.raises(ValueError):
        serialize_report({"value": float("nan")})


def test_report_is_written_atomically(tmp_path: Path):
    output = tmp_path / "report.json"
    write_report_atomic({"case_count": 1}, output)
    assert read_report(output) == {"case_count": 1}
    assert not list(tmp_path.glob(".*"))
