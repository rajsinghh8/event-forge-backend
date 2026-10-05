"""Oracle invitation adapter with serialized accepted-count maintenance."""
from __future__ import annotations

from typing import Any

from .capacity import EventCapacityExceeded
from .models import Invitation, InvitationStatus
from .state import validate_invitation_transition


class OracleInvitationRepository:
    """Uses a locked event row so simultaneous accepts cannot overbook capacity."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def get_invitation(self, invitation_id: int) -> Invitation | None:
        sql = """SELECT id, event_id, invitee_id, status
                 FROM invitations WHERE id = :invitation_id"""
        with self._connection.cursor() as cursor:
            cursor.execute(sql, invitation_id=invitation_id)
            row = cursor.fetchone()
        return None if row is None else Invitation(row[0], row[1], row[2], InvitationStatus(row[3]))

    def set_status(self, invitation_id: int, status: InvitationStatus) -> None:
        sql = "UPDATE invitations SET status = :status, responded_at = SYSTIMESTAMP WHERE id = :invitation_id"
        with self._connection.cursor() as cursor:
            cursor.execute(sql, status=status.value, invitation_id=invitation_id)
            if cursor.rowcount != 1:
                raise LookupError(invitation_id)
        self._connection.commit()

    def accept_with_capacity(self, invitation_id: int) -> Invitation:
        """Lock event counter, then change RSVP and increment in one transaction."""
        locked_sql = """SELECT i.id, i.event_id, i.invitee_id, i.status,
                               e.capacity, e.confirmed_count
                        FROM invitations i
                        JOIN events e ON e.id = i.event_id
                        WHERE i.id = :invitation_id
                        FOR UPDATE OF e.confirmed_count"""
        update_invitation = """UPDATE invitations
                               SET status = :accepted, responded_at = SYSTIMESTAMP
                               WHERE id = :invitation_id"""
        increment_count = """UPDATE events
                             SET confirmed_count = confirmed_count + 1,
                                 updated_at = SYSTIMESTAMP
                             WHERE id = :event_id"""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(locked_sql, invitation_id=invitation_id)
                row = cursor.fetchone()
                if row is None:
                    raise LookupError(invitation_id)
                invitation = Invitation(row[0], row[1], row[2], InvitationStatus(row[3]))
                validate_invitation_transition(invitation.status, InvitationStatus.ACCEPTED)
                capacity, confirmed_count = row[4], row[5]
                if capacity is not None and confirmed_count >= capacity:
                    raise EventCapacityExceeded("event capacity has been reached")
                cursor.execute(update_invitation, accepted=InvitationStatus.ACCEPTED.value, invitation_id=invitation_id)
                cursor.execute(increment_count, event_id=invitation.event_id)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return Invitation(invitation.id, invitation.event_id, invitation.invitee_id, InvitationStatus.ACCEPTED)
