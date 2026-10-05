"""Invitation RSVP use cases and activity/notification contracts."""
from __future__ import annotations

from typing import Protocol

from eventforge.tasks.models import ActivityContract, NotificationContract

from .capacity import EventCapacityExceeded
from .models import Invitation, InvitationStatus
from .repository import InvitationRepository
from .state import validate_invitation_transition


class InvitationNotFound(LookupError):
    pass


__all__ = ["EventCapacityExceeded", "InvitationNotFound", "InvitationService"]


class InvitationPublisher(Protocol):
    def publish_activity(self, activity: ActivityContract) -> None: ...
    def publish_notification(self, notification: NotificationContract) -> None: ...


class InvitationService:
    def __init__(self, invitations: InvitationRepository, publisher: InvitationPublisher) -> None:
        self._invitations = invitations
        self._publisher = publisher

    def respond(self, invitation_id: int, status: InvitationStatus) -> Invitation:
        invitation = self._invitations.get_invitation(invitation_id)
        if invitation is None:
            raise InvitationNotFound(invitation_id)
        validate_invitation_transition(invitation.status, status)
        if status is InvitationStatus.ACCEPTED:
            # Repository locks the event capacity row and updates its count atomically.
            invitation = self._invitations.accept_with_capacity(invitation_id)
        else:
            self._invitations.set_status(invitation_id, status)
            invitation = Invitation(invitation.id, invitation.event_id, invitation.invitee_id, status)
        self._publisher.publish_activity(ActivityContract(invitation.event_id, invitation.invitee_id, "invitation.responded", {"invitation_id": invitation.id, "status": status.value}))
        self._publisher.publish_notification(NotificationContract(invitation.invitee_id, "invitation", {"invitation_id": invitation.id, "status": status.value}))
        return invitation
