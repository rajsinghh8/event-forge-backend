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
        self.assertIn('SET read_at=:read_at', self.source)
        self.assertIn('"description replaces details"', self.source)
        self.assertIn('"booking_status"', self.source)
        self.assertIn('"VENDOR_PAYMENT_CREATED"', self.source)
        self.assertNotIn('data.get("read", data.get("is_read"))', self.source)

    def test_schedule_vendor_and_payment_handlers_use_validated_filters_and_activity(self):
        for token in (
            '"Invalid schedule sort"',
            '"Invalid vendor sort"',
            '"Invalid payment sort"',
            '"SCHEDULE_CREATED"',
            '"SCHEDULE_UPDATED"',
            '"SCHEDULE_DELETED"',
            '"VENDOR_CREATED"',
            '"VENDOR_UPDATED"',
            '"VENDOR_DELETED"',
            '"NOTIFICATION_READ_STATE_UPDATED"',
        ):
            self.assertIn(token, self.source)

    def test_task_and_invitation_routes_are_explicit_transactional_handlers(self):
        self.assertIn('def invitations(event_id):', self.source)
        self.assertIn('def invitation(event_id, invitation_id):', self.source)
        self.assertNotIn('simple_resource("invitations"', self.source)
        self.assertIn("EVENT_CAPACITY_REACHED", self.source)
        self.assertIn("confirmed_guest_count=confirmed_guest_count+1", self.source)
        self.assertIn("confirmed_guest_count=confirmed_guest_count-1", self.source)
        self.assertIn("TASK_TRANSITIONS", self.source)
        self.assertIn("priority,assignee", self.source)
        self.assertIn("TASK_CREATED", self.source)
        self.assertIn('"overdue-task"', self.source)
        self.assertIn("collection_page(cursor", self.source)


if __name__ == "__main__":
    unittest.main()
