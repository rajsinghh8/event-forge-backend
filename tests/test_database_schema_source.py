"""Source-level Oracle schema contract checks; no Oracle client is required."""
import pathlib
import unittest


DATABASE_SOURCE = pathlib.Path("src/eventforge/database.py")


class DatabaseSchemaSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DATABASE_SOURCE.read_text(encoding="utf-8")
        cls.sql = " ".join(cls.source.upper().split())

    def test_canonical_nullable_and_required_columns_are_declared(self):
        for fragment in (
            "VENUE VARCHAR2(300) NOT NULL",
            "PRIORITY VARCHAR2(20) NOT NULL",
            "ASSIGNEE VARCHAR2(200)",
            "DESCRIPTION CLOB",
            "CONTACT_DETAILS CLOB",
            "BOOKING_STATUS VARCHAR2(40) NOT NULL",
            "READ_AT TIMESTAMP WITH TIME ZONE",
        ):
            self.assertIn(fragment, self.sql)
        self.assertNotIn("IS_READ NUMBER", self.sql)
        self.assertNotIn("CONTACT_NAME", self.sql)
        self.assertNotIn("BOOKING_REFERENCE", self.sql)

    def test_foreign_keys_cover_owner_and_all_event_children(self):
        for constraint in (
            "EF_EVENTS_OWNER_FK",
            "EF_TASKS_EVENT_FK",
            "EF_TASK_DEPS_TASK_FK",
            "EF_TASK_DEPS_DEPENDENCY_FK",
            "EF_INVITATIONS_EVENT_FK",
            "EF_CATEGORIES_EVENT_FK",
            "EF_EXPENSES_EVENT_FK",
            "EF_EXPENSES_CATEGORY_FK",
            "EF_SCHEDULE_EVENT_FK",
            "EF_VENDORS_EVENT_FK",
            "EF_PAYMENTS_EVENT_FK",
            "EF_PAYMENTS_VENDOR_FK",
            "EF_NOTIFICATIONS_EVENT_FK",
            "EF_ACTIVITY_EVENT_FK",
            "EF_ACTIVITY_ACTOR_FK",
        ):
            self.assertIn("CONSTRAINT " + constraint + " FOREIGN KEY", self.sql)

    def test_check_constraints_protect_enum_capacity_and_money_invariants(self):
        for constraint in (
            "EF_EVENTS_STATUS_CK CHECK",
            "EF_TASKS_STATUS_CK CHECK",
            "EF_TASKS_PRIORITY_CK CHECK",
            "EF_INVITATIONS_STATUS_CK CHECK",
            "EF_NOTIFICATIONS_TYPE_CK CHECK",
            "EF_EVENTS_CAPACITY_CK CHECK",
            "EF_EVENTS_BUDGET_CK CHECK",
            "EF_EVENTS_GUESTS_CK CHECK",
            "EF_CATEGORIES_AMOUNT_CK CHECK",
            "EF_EXPENSES_AMOUNT_CK CHECK",
            "EF_VENDORS_COST_CK CHECK",
            "EF_VENDORS_PAID_CK CHECK",
            "EF_PAYMENTS_AMOUNT_CK CHECK",
        ):
            self.assertIn("CONSTRAINT " + constraint, self.sql)
        self.assertIn("CAPACITY IS NULL OR CAPACITY >= 1", self.sql)
        self.assertIn("PAID_AMOUNT >= 0 AND PAID_AMOUNT <= COST", self.sql)

    def test_indexes_match_owner_event_and_filter_queries(self):
        for index in (
            "EF_EVENTS_OWNER_STATUS_IX",
            "EF_TASKS_EVENT_FILTER_IX",
            "EF_TASK_DEPS_DEPENDENCY_IX",
            "EF_INVITATIONS_EVENT_STATUS_IX",
            "EF_CATEGORIES_EVENT_NAME_IX",
            "EF_EXPENSES_EVENT_FILTER_IX",
            "EF_SCHEDULE_EVENT_TIME_IX",
            "EF_VENDORS_EVENT_FILTER_IX",
            "EF_PAYMENTS_EVENT_VENDOR_IX",
            "EF_NOTIFICATIONS_EVENT_READ_IX",
            "EF_ACTIVITY_EVENT_CREATED_IX",
        ):
            self.assertIn("CREATE INDEX " + index, self.sql)

    def test_bootstrap_handles_existing_tables_and_indexes(self):
        self.assertIn('getattr(exc.args[0], "code", None) != 955', self.source)


if __name__ == "__main__":
    unittest.main()
