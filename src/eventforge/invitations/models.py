"""Invitation domain values."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    MAYBE = "MAYBE"


@dataclass(frozen=True, slots=True)
class Invitation:
    id: int
    event_id: int
    invitee_id: int
    status: InvitationStatus
