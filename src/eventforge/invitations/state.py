"""Pure invitation RSVP state policy."""
from __future__ import annotations

from .models import InvitationStatus


class InvalidInvitationTransition(ValueError):
    pass


_ALLOWED: dict[InvitationStatus, frozenset[InvitationStatus]] = {
    InvitationStatus.PENDING: frozenset({InvitationStatus.ACCEPTED, InvitationStatus.DECLINED, InvitationStatus.MAYBE}),
    InvitationStatus.MAYBE: frozenset({InvitationStatus.ACCEPTED, InvitationStatus.DECLINED}),
    InvitationStatus.ACCEPTED: frozenset(),
    InvitationStatus.DECLINED: frozenset(),
}


def validate_invitation_transition(current: InvitationStatus, requested: InvitationStatus) -> None:
    """Only a pending/maybe RSVP can be resolved; accepted and declined are final."""
    if current == requested or requested not in _ALLOWED[current]:
        raise InvalidInvitationTransition(f"invitation cannot transition from {current} to {requested}")
