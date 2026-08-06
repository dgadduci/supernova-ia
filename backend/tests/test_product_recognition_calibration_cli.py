import json
from pathlib import Path

from backend.cli import calibrate_product_recognizer as cli


class FakeSession:
    def __init__(self):
        self.closed = 0
        self.commits = 0

    def close(self):
        self.closed += 1


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.session


def dataset_path():
    return str(Path(__file__).parent.parent / "data" / "product_recognition_calibration_cases.json")


def test_cli_rejects_invalid_limit_without_opening_session(monkeypatch, tmp_path):
    factory = FakeSessionFactory(FakeSession())
    monkeypatch.setattr(cli, "_SessionLocal", factory)
    result = cli.main(["--dataset", dataset_path(), "--output", str(tmp_path / "report.json"), "--limit", "0"])
    assert result == 2
    assert factory.calls == 0


def test_cli_closes_owned_session_on_runner_failure(monkeypatch, tmp_path):
    session = FakeSession()
    monkeypatch.setattr(cli, "_SessionLocal", FakeSessionFactory(session))
    monkeypatch.setattr(cli, "load_settings", lambda: object())
    monkeypatch.setattr(cli, "ProductRecognitionCalibrationRunner", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("internal")))
    result = cli.main(["--dataset", dataset_path(), "--output", str(tmp_path / "report.json")])
    assert result == 1
    assert session.closed == 1
    assert session.commits == 0


def test_cli_source_does_not_reference_runtime_mode():
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "PRODUCT_RECOGNIZER_MODE" not in source


def test_cli_writes_only_report_summary(monkeypatch, tmp_path, capsys):
    session = FakeSession()
    monkeypatch.setattr(cli, "_SessionLocal", FakeSessionFactory(session))
    monkeypatch.setattr(cli, "load_settings", lambda: object())
    monkeypatch.setattr(cli, "OllamaEmbeddingClient", lambda settings: object())
    monkeypatch.setattr(cli, "FuzzyProductRecognizer", lambda: object())
    monkeypatch.setattr(cli, "ProductPresentationVectorSearchService", lambda session, settings: object())

    class Runner:
        def __init__(self, **kwargs):
            pass

        def run(self, dataset, *, commerce_id=None, limit=None):
            return {
                "case_count": 1,
                "policy_count": 1,
                "eligibility": {"status": "pending"},
            }

    monkeypatch.setattr(cli, "ProductRecognitionCalibrationRunner", Runner)
    output = tmp_path / "report.json"
    result = cli.main(["--dataset", dataset_path(), "--output", str(output)])
    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["case_count"] == 1
    assert capsys.readouterr().out.strip() == "cases=1 policies=1 eligibility=pending"
    assert session.closed == 1
