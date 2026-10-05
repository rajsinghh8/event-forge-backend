"""Pure contract checks that do not require Bottle or Oracle to be installed."""
import ast
import pathlib
import unittest


SOURCE = pathlib.Path("src/eventforge/app.py")


class AppContractSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_source_is_valid_python_and_declares_all_openapi_routes(self):
        self.assertIsInstance(self.tree, ast.Module)
        for route in (
            '"/health"',
            '"/docs"',
            '"/openapi.json"',
            '"/api/events/{event_id}/vendors/{vendor_id}/payments"',
            '"/api/events/{event_id}/notifications/{id}"',
            '"/api/events/<event_id:int>/schedule/<item_id:int>"',
        ):
            self.assertIn(route, self.source)

    def test_validation_rules_are_present_in_executable_source(self):
        self.assertIn("TASK_COMPLETED_IMMUTABLE", self.source)
        self.assertIn("TASK_DEPENDENCY_CONFLICT", self.source)
        self.assertIn("CATEGORY_HAS_EXPENSES", self.source)
        self.assertIn("from must not be after to", self.source)
        self.assertIn('data.get("read", data.get("is_read"))', self.source)


if __name__ == "__main__":
    unittest.main()
