import io
import json
import unittest
import unittest.mock

from backend.config.settings import Settings
from backend.diagnostics import (
    CONTROLLED_INTENT_CORPUS,
    PROMPT_TEMPLATE_VERSION,
    IntentFixture,
)
from backend.intents.schemas.intent_classification import IntentName
from backend.llm.intent_classifier import IntentClassifier
from backend.scripts.audit_intent_classifier import (
    AuditReport,
    FixtureReport,
    build_report,
    effective_non_secret_settings,
    main,
    render_report,
)


def _settings() -> Settings:
    return Settings(
        llm_url="http://llm.test/api/generate",
        llm_model="qwen2.5-coder:7b-ctx8192",
        llm_timeout=30,
        llm_keep_alive="2h",
        llm_num_ctx=8192,
        llm_num_predict=1500,
        llm_log_content=False,
        llm_log_max_chars=1000,
        ollama_proxy_url=None,
    )


class _StubQueryLlm:
    def __init__(self, payload):
        self._payload = payload

    def request(self, prompt: str) -> dict:
        return self._payload


def _payment_ok() -> dict:
    return {
        "intents": [
            {
                "intent": "set_metodo_de_pago",
                "mensaje": "Pago en Efectivo (prueba cierre)",
            }
        ],
        "mensaje": "Pago en Efectivo (prueba cierre)",
    }


def _make_classifier(payload: dict) -> IntentClassifier:
    return IntentClassifier(query_llm=_StubQueryLlm(payload))


class _SimpleStub:
    def __init__(self, fn):
        self._fn = fn

    def request(self, prompt: str) -> dict:
        return self._fn(prompt)


class EffectiveSettingsTest(unittest.TestCase):
    def test_settings_excludes_url_proxy_and_credentials(self):
        settings = Settings(
            llm_url="http://secret-host/api",
            llm_model="qwen2.5-coder:7b-ctx8192",
            llm_timeout=30,
            llm_keep_alive="2h",
            llm_num_ctx=8192,
            llm_num_predict=1500,
            llm_log_content=False,
            llm_log_max_chars=1000,
            ollama_proxy_url="socks5h://127.0.0.1:9050",
        )
        view = effective_non_secret_settings(settings)
        self.assertEqual(view["model"], "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(view["num_ctx"], 8192)
        self.assertEqual(view["num_predict"], 1500)
        self.assertEqual(view["temperature"], 0)
        self.assertEqual(view["keep_alive"], "2h")
        serialized = json.dumps(view)
        self.assertNotIn("secret-host", serialized)
        self.assertNotIn("127.0.0.1", serialized)
        self.assertNotIn("socks5", serialized)
        self.assertNotIn("llm_url", serialized)


class BuildReportTest(unittest.TestCase):
    def test_report_marks_payment_regression_pass_when_only_set_metodo_de_pago(self):
        def _factory() -> IntentClassifier:
            return _make_classifier(_payment_ok())

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[
                IntentFixture(
                    fixture_id="F-REG-PAGO-EFECTIVO",
                    description="payment regression",
                    message="Pago en Efectivo (prueba cierre)",
                    expected_intents=(IntentName.SET_METODO_DE_PAGO,),
                    expected_source_fragments=("Pago en Efectivo (prueba cierre)",),
                )
            ],
        )
        self.assertEqual(report.passed, 1)
        self.assertEqual(report.failed, 0)
        fixture = report.fixtures[0]
        self.assertTrue(fixture.matched)
        self.assertEqual(fixture.failure_category, "ok")
        self.assertEqual(fixture.expected_intents, ["set_metodo_de_pago"])
        self.assertEqual(fixture.actual_intents, ["set_metodo_de_pago"])
        self.assertIsNotNone(fixture.parsed_response)
        assert fixture.parsed_response is not None
        self.assertEqual(fixture.parsed_response["intents"][0]["intent"], "set_metodo_de_pago")
        self.assertEqual(fixture.prompt_template_version, PROMPT_TEMPLATE_VERSION)
        self.assertEqual(len(fixture.prompt_fingerprint), 64)
        self.assertIn("Pago en Efectivo (prueba cierre)", fixture.rendered_prompt)

    def test_report_flags_contamination_before_intent_mismatch(self):
        def _factory() -> IntentClassifier:
            return _make_classifier(
                {
                    "intents": [
                        {"intent": "agregar_producto", "mensaje": "una empanada"},
                        {"intent": "set_metodo_de_pago", "mensaje": "Efectivo"},
                    ],
                    "mensaje": "Pago en Efectivo (prueba cierre)",
                }
            )

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[
                IntentFixture(
                    fixture_id="F-REG-PAGO-EFECTIVO",
                    description="payment regression",
                    message="Pago en Efectivo (prueba cierre)",
                    expected_intents=(IntentName.SET_METODO_DE_PAGO,),
                    expected_source_fragments=("Pago en Efectivo (prueba cierre)",),
                )
            ],
        )
        self.assertEqual(report.failed, 1)
        fixture = report.fixtures[0]
        self.assertFalse(fixture.matched)
        self.assertEqual(fixture.failure_category, "contamination_detected")
        self.assertEqual(
            fixture.actual_intents, ["agregar_producto", "set_metodo_de_pago"]
        )
        self.assertEqual(fixture.contamination_offenders, ["una empanada"])

    def test_report_evaluates_full_corpus_against_deterministic_stub(self):
        def _factory() -> IntentClassifier:
            def _request(prompt: str) -> dict:
                if "stub-regression-sentinel" in prompt:
                    return _payment_ok()
                return {
                    "intents": [
                        {"intent": "agregar_producto", "mensaje": "stub"}
                    ],
                    "mensaje": "stub",
                }

            return IntentClassifier(query_llm=_SimpleStub(_request))

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
        )
        self.assertEqual(len(report.fixtures), len(CONTROLLED_INTENT_CORPUS))
        passing_ids = {
            fixture.fixture_id
            for fixture in report.fixtures
            if fixture.matched
        }
        self.assertEqual(passing_ids, set())
        for fixture in report.fixtures:
            self.assertFalse(
                fixture.matched,
                f"unexpected pass for {fixture.fixture_id}",
            )
            self.assertIn(
                fixture.failure_category,
                {"intent_mismatch", "fragment_missing", "contamination_detected"},
            )

    def test_report_recognises_payment_when_fixture_message_matches_response(self):
        def _factory() -> IntentClassifier:
            def _request(prompt: str) -> dict:
                return _payment_ok()

            return IntentClassifier(query_llm=_SimpleStub(_request))

        fixture = IntentFixture(
            fixture_id="F-CUSTOM-PAGO",
            description="custom payment",
            message="Pago en Efectivo (prueba cierre)",
            expected_intents=(IntentName.SET_METODO_DE_PAGO,),
            expected_source_fragments=("Pago en Efectivo (prueba cierre)",),
        )
        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[fixture],
        )
        self.assertEqual(len(report.fixtures), 1)
        self.assertTrue(report.fixtures[0].matched)
        self.assertEqual(report.fixtures[0].failure_category, "ok")
        self.assertEqual(report.fixtures[0].contamination_offenders, [])


class RenderReportTest(unittest.TestCase):
    def test_text_renderer_does_not_leak_url_or_credentials(self):
        report = AuditReport(
            corpus_version="intent-corpus/test",
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_template_hash="abc",
            effective_settings={
                "model": "qwen2.5-coder:7b-ctx8192",
                "num_ctx": 8192,
                "num_predict": 1500,
                "temperature": 0,
                "keep_alive": "2h",
            },
        )
        report.fixtures.append(
            FixtureReport(
                fixture_id="F-TEST",
                description="demo",
                expected_intents=["saludo"],
                actual_intents=["saludo"],
                matched=True,
                failure_category="ok",
                expected_source_fragments=[],
                preserved_source_fragments=[],
                parsed_response={
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                },
                rendered_prompt="PROMPT",
                prompt_fingerprint="f" * 64,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
            )
        )
        text = render_report(report)
        self.assertIn("passed                   : 1", text)
        self.assertIn("failed                   : 0", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("socks5", text)
        self.assertNotIn("token", text.casefold())

    def test_json_renderer_round_trips_through_to_dict(self):
        report = AuditReport(
            corpus_version="intent-corpus/test",
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_template_hash="abc",
            effective_settings={
                "model": "qwen2.5-coder:7b-ctx8192",
                "num_ctx": 8192,
                "num_predict": 1500,
                "temperature": 0,
                "keep_alive": "2h",
            },
        )
        report.fixtures.append(
            FixtureReport(
                fixture_id="F-TEST",
                description="demo",
                expected_intents=["saludo"],
                actual_intents=["saludo"],
                matched=True,
                failure_category="ok",
                expected_source_fragments=[],
                preserved_source_fragments=[],
                parsed_response={
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                },
                rendered_prompt="PROMPT",
                prompt_fingerprint="f" * 64,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
            )
        )
        serialized = json.dumps(report.to_dict())
        self.assertIn("passed", serialized)
        self.assertIn("fixtures", serialized)


class MainEntryPointTest(unittest.TestCase):
    def test_dry_run_renders_prompts_without_calling_llm(self):
        buffer = io.StringIO()
        with unittest.mock.patch("sys.stdout", buffer):
            exit_code = main(["--dry-run", "--format", "json"])
        self.assertEqual(exit_code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["total"], len(CONTROLLED_INTENT_CORPUS))
        for fixture in payload["fixtures"]:
            self.assertEqual(fixture["failure_category"], "dry_run")
            self.assertIn("Catálogo de posibles intents", fixture["rendered_prompt"])

    def test_only_filter_runs_single_fixture(self):
        buffer = io.StringIO()
        with unittest.mock.patch("sys.stdout", buffer):
            main(
                [
                    "--dry-run",
                    "--format",
                    "json",
                    "--only",
                    "F-REG-PAGO-EFECTIVO",
                ]
            )
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["fixtures"][0]["fixture_id"], "F-REG-PAGO-EFECTIVO")


class AuditContaminationDetectionTest(unittest.TestCase):
    """The audit must flag responses whose ``mensaje`` fields reproduce
    content not present in the current fixture message.
    """

    def test_audit_flags_response_reproducing_prompt_example_content(self):
        def _factory() -> IntentClassifier:
            return _make_classifier(
                {
                    "intents": [
                        {
                            "intent": "set_direccion_entrega",
                            "mensaje": "Tilcara 2020",
                        }
                    ],
                    "mensaje": "Tilcara 2020",
                }
            )

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[
                IntentFixture(
                    fixture_id="F-REG-PAGO-EFECTIVO",
                    description="payment regression",
                    message="Pago en Efectivo (prueba cierre)",
                    expected_intents=(IntentName.SET_METODO_DE_PAGO,),
                    expected_source_fragments=("Pago en Efectivo (prueba cierre)",),
                )
            ],
        )
        fixture = report.fixtures[0]
        self.assertFalse(fixture.matched)
        self.assertEqual(fixture.failure_category, "contamination_detected")
        self.assertIn("Tilcara 2020", fixture.contamination_offenders)
        self.assertEqual(report.failed, 1)

    def test_audit_passes_when_returned_mensaje_is_substring_of_fixture(self):
        def _factory() -> IntentClassifier:
            return _make_classifier(
                {
                    "intents": [
                        {
                            "intent": "set_metodo_de_pago",
                            "mensaje": "Pago en Efectivo (prueba cierre)",
                        }
                    ],
                    "mensaje": "Pago en Efectivo (prueba cierre)",
                }
            )

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[
                IntentFixture(
                    fixture_id="F-REG-PAGO-EFECTIVO",
                    description="payment regression",
                    message="Pago en Efectivo (prueba cierre)",
                    expected_intents=(IntentName.SET_METODO_DE_PAGO,),
                    expected_source_fragments=("Pago en Efectivo (prueba cierre)",),
                )
            ],
        )
        fixture = report.fixtures[0]
        self.assertTrue(fixture.matched)
        self.assertEqual(fixture.contamination_offenders, [])
        self.assertEqual(report.passed, 1)

    def test_audit_offenders_surface_in_serialized_report(self):
        def _factory() -> IntentClassifier:
            return _make_classifier(
                {
                    "intents": [
                        {
                            "intent": "agregar_producto",
                            "mensaje": "una empanada de carne",
                        }
                    ],
                    "mensaje": "una empanada de carne",
                }
            )

        report = build_report(
            classifier_factory=_factory,
            settings=_settings(),
            fixtures=[
                IntentFixture(
                    fixture_id="F-CUSTOM",
                    description="custom contamination",
                    message="Pago en Efectivo (prueba cierre)",
                    expected_intents=(IntentName.SET_METODO_DE_PAGO,),
                    expected_source_fragments=(),
                )
            ],
        )
        fixture = report.fixtures[0]
        self.assertEqual(fixture.failure_category, "contamination_detected")
        serialized = json.dumps(fixture.to_dict())
        self.assertIn("contamination_offenders", serialized)
        self.assertIn("una empanada de carne", serialized)


if __name__ == "__main__":
    unittest.main()
