"""Capacity business error shared by invitation service and Oracle adapter."""


class EventCapacityExceeded(ValueError):
    """The event has no remaining confirmed-attendee capacity."""
