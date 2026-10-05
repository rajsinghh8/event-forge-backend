import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "src")

from eventforge.domain.errors import ConflictError
from eventforge.domain.schedule import ScheduleEntry
from eventforge.services.schedule import ScheduleService


class MemoryScheduleRepository:
    def __init__(self):
        self.entries = {}

    def overlapping(self, event_id, starts_at, ends_at, *, lock=False):
        probe = ScheduleEntry("probe", event_id, "probe", starts_at, ends_at)
        return [entry for entry in self.entries.values() if entry.event_id == event_id and entry.overlaps(probe)]

    def get(self, schedule_id):
        return self.entries.get(schedule_id)

    def add(self, entry):
        self.entries[entry.id] = entry
        return entry

    def update(self, entry):
        self.entries[entry.id] = entry
        return entry

    def delete(self, schedule_id):
        return self.entries.pop(schedule_id, None) is not None


class ScheduleOverlapTests(unittest.TestCase):
    def setUp(self):
        self.service = ScheduleService(MemoryScheduleRepository())
        self.start = datetime(2025, 1, 1, 9, tzinfo=timezone.utc)
        self.service.create("event-1", "Setup", self.start, self.start + timedelta(hours=1))

    def test_rejects_positive_duration_overlap(self):
        with self.assertRaises(ConflictError):
            self.service.create("event-1", "Clashing", self.start + timedelta(minutes=30), self.start + timedelta(hours=2))

    def test_allows_back_to_back_ranges(self):
        entry = self.service.create("event-1", "Next", self.start + timedelta(hours=1), self.start + timedelta(hours=2))
        self.assertEqual(entry.starts_at, self.start + timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
