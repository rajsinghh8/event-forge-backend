"""Dependency-free unit coverage for task and invitation policy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eventforge.invitations.models import InvitationStatus
from eventforge.invitations.state import InvalidInvitationTransition, validate_invitation_transition
from eventforge.tasks.dependencies import InvalidTaskDependency, validate_dependency
from eventforge.tasks.lifecycle import InvalidTaskTransition, validate_task_transition
from eventforge.tasks.models import Task, TaskStatus


class TaskPolicyTests(unittest.TestCase):
    def test_completed_task_cannot_reopen(self) -> None:
        with self.assertRaises(InvalidTaskTransition):
            validate_task_transition(TaskStatus.COMPLETED, TaskStatus.TODO)

    def test_dependency_cycle_is_rejected(self) -> None:
        task = Task(1, 8, "A", TaskStatus.TODO)
        prerequisite = Task(2, 8, "B", TaskStatus.TODO)
        graph = {2: (3,), 3: (1,)}
        with self.assertRaises(InvalidTaskDependency):
            validate_dependency(task, prerequisite, lambda task_id: graph.get(task_id, ()))

    def test_completed_prerequisite_is_rejected(self) -> None:
        task = Task(1, 8, "A", TaskStatus.TODO)
        prerequisite = Task(2, 8, "B", TaskStatus.COMPLETED)
        with self.assertRaises(InvalidTaskDependency):
            validate_dependency(task, prerequisite, lambda _task_id: ())


class InvitationPolicyTests(unittest.TestCase):
    def test_accepted_invitation_cannot_be_changed(self) -> None:
        with self.assertRaises(InvalidInvitationTransition):
            validate_invitation_transition(InvitationStatus.ACCEPTED, InvitationStatus.DECLINED)

    def test_pending_invitation_may_be_accepted(self) -> None:
        validate_invitation_transition(InvitationStatus.PENDING, InvitationStatus.ACCEPTED)


if __name__ == "__main__":
    unittest.main()
