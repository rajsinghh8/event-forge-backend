"""Source-level contract checks for the finance routes (no Oracle dependency)."""
import pathlib
import unittest


SOURCE = pathlib.Path("src/eventforge/app.py")


class FinanceContractSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_expense_writes_lock_and_check_budget_before_dml(self):
        self.assertIn('event(cursor, event_id, user_id, lock=True)', self.source)
        self.assertIn('"BUDGET_LIMIT_EXCEEDED"', self.source)
        self.assertIn('proposed_expense_total(cursor, event_id, 0, amount)', self.source)
        self.assertIn('proposed_expense_total(cursor, event_id, old["amount"], amount)', self.source)
        self.assertLess(
            self.source.index('enforce_budget(cursor, event_id, user_id, proposed_expense_total(cursor, event_id, 0, amount))'),
            self.source.index('INSERT INTO eventforge_expenses'),
        )

    def test_finance_mutations_have_activity_and_collection_validation(self):
        for action in (
            "CATEGORY_CREATED", "CATEGORY_UPDATED", "CATEGORY_DELETED",
            "EXPENSE_CREATED", "EXPENSE_UPDATED", "EXPENSE_DELETED",
        ):
            self.assertIn(action, self.source)
        self.assertIn('def finance_collection_query(kind):', self.source)
        self.assertIn('"Unsupported query parameter"', self.source)
        self.assertIn('"from must not be after to"', self.source)
        self.assertIn('"Invalid sort field"', self.source)


if __name__ == "__main__":
    unittest.main()
