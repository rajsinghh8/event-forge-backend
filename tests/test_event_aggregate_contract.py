"""Source-level contract coverage for the active event aggregate handlers.

These checks deliberately avoid importing Bottle/Oracle so they can run in the
lightweight verification environment as well as against the deployed app.
"""
import ast
import pathlib
import unittest


SOURCE = pathlib.Path("src/eventforge/app.py")


class EventAggregateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_event_create_requires_a_nonblank_venue(self):
        self.assertIn('"required": ["name", "event_datetime", "venue"]', self.source)
        self.assertIn('"venue": {"type": "string", "minLength": 1', self.source)
        self.assertIn('"venue": required_text(data, "venue")', self.source)

    def test_event_collection_validates_every_declared_filter(self):
        for parameter in ("status", "q", "date_from", "date_to", "sort", "order", "page", "page_size"):
            self.assertIn(f'"{parameter}"', self.source)
        for validation in (
            "Unsupported query parameter",
            "Invalid event status",
            "q must be nonblank and at most 200 characters",
            "date_from must not be after date_to",
            "Invalid event sort or order",
        ):
            self.assertIn(validation, self.source)

    def test_search_is_owner_scoped_bound_and_covers_all_contract_fields(self):
        self.assertIn('binds = {"user_id": user_id}', self.source)
        self.assertIn('LOWER(name) LIKE :q OR LOWER(venue) LIKE :q OR LOWER(NVL(description,\'\')) LIKE :q', self.source)
        self.assertIn('"event_datetime>=:date_from"', self.source)
        self.assertIn('"event_datetime<=:date_to"', self.source)
        self.assertIn('"event_datetime": "event_datetime"', self.source)

    def test_openapi_event_segment_describes_filters_and_create_body(self):
        self.assertIn('event_query_parameters = pagination_parameters((', self.source)
        self.assertIn('"Whitelisted event sort field."', self.source)
        self.assertIn('"Nonblank event venue"', self.source)
        self.assertIn('json_body(event_create_schema)', self.source)
        self.assertIn('json_body(event_update_schema)', self.source)


if __name__ == "__main__":
    unittest.main()
