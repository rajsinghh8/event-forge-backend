"""Persistence ports for invitation use cases."""
from __future__ import annotations

from typing import Protocol

from .models import Invitation, InvitationStatus


class InvitationRepository(Protocol):
    def get_invitation(self, invitation_id: int) -> Invitation | None: ...
    def set_status(self, invitation_id: int, status: InvitationStatus) -> None: ...
    def accept_with_capacity(self, invitation_id: int) -> Invitation: ...
