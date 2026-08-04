import json
import unittest
from pathlib import Path

from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import ProductRecognizerResult

DATASET_PATH = Path(__file__).parent / "fixtures" / "product_recognizer_baseline.json"
ALLOWED_RESULT_TYPES = {"unique", "ambiguous", "unknown"}


def load_baseline() -> dict:
    with DATASET_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def validate_baseline(dataset: dict) -> None:
    if dataset.get("schema_version") != 1:
        raise AssertionError("schema_version must be 1")
    catalogs = dataset.get("catalogs")
    cases = dataset.get("cases")
    if not isinstance(catalogs, dict) or not isinstance(cases, list):
        raise TypeError("dataset must contain catalogs and cases")

    case_ids: set[str] = set()
    for case in cases:
        required = {"case_id", "text", "catalog_fixture", "catalog_scope", "result_type", "reason"}
        missing = required - set(case)
        if missing:
            raise AssertionError(f"{case.get('case_id', '<unknown>')}: missing {sorted(missing)}")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise AssertionError(f"duplicate or invalid case_id: {case_id!r}")
        case_ids.add(case_id)
        result_type = case["result_type"]
        if result_type not in ALLOWED_RESULT_TYPES:
            raise AssertionError(f"{case_id}: invalid result_type {result_type!r}")
        fixture_name = case["catalog_fixture"]
        if fixture_name not in catalogs:
            raise AssertionError(f"{case_id}: missing catalog fixture {fixture_name!r}")
        catalog = catalogs[fixture_name]
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            raise TypeError(f"{fixture_name}: entries must be a list")
        catalog_ids = [entry.get("producto_presentacion_id") for entry in entries]
        if any(not isinstance(identifier, int) for identifier in catalog_ids):
            raise AssertionError(f"{fixture_name}: entries require integer IDs")
        if catalog.get("dynamic") is not True:
            if result_type == "unique":
                expected_id = case.get("expected_producto_presentacion_id")
                expected_ref = case.get("expected_producto_presentacion_id_ref")
                if not isinstance(expected_id, int) and not isinstance(expected_ref, str):
                    raise AssertionError(f"{case_id}: unique case requires an expected ID")
                if isinstance(expected_id, int) and expected_id not in catalog_ids:
                    raise AssertionError(f"{case_id}: expected ID {expected_id} is absent")
            elif result_type == "ambiguous":
                expected_ids = case.get("expected_candidate_ids")
                if not isinstance(expected_ids, list) or not expected_ids:
                    raise AssertionError(f"{case_id}: ambiguous case requires candidate IDs")
                missing_ids = [identifier for identifier in expected_ids if identifier not in catalog_ids]
                if missing_ids:
                    raise AssertionError(f"{case_id}: candidate IDs absent: {missing_ids}")
            elif case.get("expected_producto_presentacion_id") is not None or case.get("expected_candidate_ids"):
                raise AssertionError(f"{case_id}: unknown case cannot declare product IDs")
        elif result_type == "unique" and not isinstance(
            case.get("expected_producto_presentacion_id_ref"), str
        ):
            raise AssertionError(f"{case_id}: dynamic unique case requires an ID reference")
        if case["catalog_scope"] != catalog.get("scope"):
            raise AssertionError(f"{case_id}: catalog scope does not match fixture scope")
        if catalog.get("scope") == "pending_product_selection_restricted":
            candidate_ids = catalog.get("candidate_ids")
            if candidate_ids != catalog_ids:
                raise AssertionError(f"{case_id}: restricted candidate scope mismatch")
        limitation = case.get("known_fuzzy_limitation", False)
        note = case.get("limitation_note")
        if limitation is True and (not isinstance(note, str) or not note.strip()):
            raise AssertionError(f"{case_id}: limitation_note is required")
        if limitation is not True and note is not None:
            raise AssertionError(f"{case_id}: limitation_note requires known_fuzzy_limitation")


def _result_ids(result: ProductRecognizerResult) -> tuple[list[int], list[int]]:
    found = [entry["producto_presentacion_id"] for entry in result["encontrados"]]
    possible = [
        product["producto_presentacion_id"]
        for group in result["encontrados_posibles"]
        for product in group["productos"]
    ]
    return found, possible


def assert_case(testcase: unittest.TestCase, case: dict, catalog: list[dict]) -> None:
    result = FuzzyProductRecognizer().recognize(case["text"], catalog)
    found_ids, possible_ids = _result_ids(result)
    result_type = case["result_type"]
    if result_type == "unique":
        expected_id = case.get("expected_producto_presentacion_id")
        if expected_id is not None:
            testcase.assertEqual(found_ids, [expected_id], case["case_id"])
        testcase.assertEqual(possible_ids, [], case["case_id"])
    elif result_type == "ambiguous":
        testcase.assertEqual(found_ids, [], case["case_id"])
        testcase.assertEqual(possible_ids, case["expected_candidate_ids"], case["case_id"])
    else:
        testcase.assertEqual(found_ids, [], case["case_id"])
        testcase.assertEqual(possible_ids, [], case["case_id"])
        expected_unknown = case.get("expected_unmatched_fragments")
        if expected_unknown is not None:
            testcase.assertEqual(
                [entry["texto_origen"] for entry in result["no_encontrados"]],
                expected_unknown,
                case["case_id"],
            )
    expected_quantity = case.get("expected_quantity")
    if expected_quantity is not None:
        products = list(result["encontrados"])
        products.extend(product for group in result["encontrados_posibles"] for product in group["productos"])
        testcase.assertTrue(products, case["case_id"])
        testcase.assertTrue(
            all(product["cantidad"] == expected_quantity for product in products),
            case["case_id"],
        )


class ProductRecognizerBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_baseline()
        validate_baseline(cls.dataset)

    def test_dataset_schema_and_integrity(self):
        validate_baseline(self.dataset)

    def test_every_static_case_executes_against_fuzzy_recognizer(self):
        for case in self.dataset["cases"]:
            catalog = self.dataset["catalogs"][case["catalog_fixture"]]
            if catalog.get("dynamic") is True:
                continue
            with self.subTest(case_id=case["case_id"]):
                assert_case(self, case, catalog["entries"])


if __name__ == "__main__":
    unittest.main()
