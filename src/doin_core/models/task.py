"""Tasks — pending work items in the DON network.

All work flows through a task queue on nodes:
  - Optimizers submit optimae → creates OPTIMAE_VERIFICATION task
  - Clients request inference → creates INFERENCE_REQUEST task
  - Evaluators pull pending tasks from any node and serve them
  - Completed tasks are logged as transactions on the blockchain
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """Types of tasks in the work queue."""

    OPTIMAE_VERIFICATION = "optimae_verification"
    INFERENCE_REQUEST = "inference_request"


class TaskStatus(str, Enum):
    """Lifecycle of a task."""

    PENDING = "pending"       # Waiting for an evaluator to claim
    CLAIMED = "claimed"       # An evaluator is working on it
    COMPLETED = "completed"   # Result available
    FAILED = "failed"         # Evaluator failed to process


class Task(BaseModel):
    """A unit of work in the DON network.

    Tasks are created by optimizers (verification) or clients (inference),
    stored in node work queues, and pulled by evaluators when available.
    Every lifecycle event (created, claimed, completed) is flooded to the
    network and logged on-chain.
    """

    id: str = Field(default="", description="Deterministic task hash")
    task_type: TaskType
    domain_id: str = Field(description="Which domain/model this task is for")
    status: TaskStatus = Field(default=TaskStatus.PENDING)

    # Who created / is working on this task
    requester_id: str = Field(description="Peer ID of the requester (optimizer or client)")
    evaluator_id: str | None = Field(default=None, description="Peer ID of the evaluator that claimed it")

    # Task payload — depends on task_type
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="For OPTIMAE_VERIFICATION: the hyperparams to verify. For INFERENCE: input data.",
    )

    # For OPTIMAE_VERIFICATION
    optimae_id: str | None = Field(default=None, description="ID of the optimae being verified")
    reported_performance: float | None = Field(default=None, description="Optimizer's claimed performance")

    # Result (filled when completed)
    result: dict[str, Any] | None = Field(default=None, description="Evaluation result")
    verified_performance: float | None = Field(default=None, description="Evaluator's measured performance")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: datetime | None = None
    completed_at: datetime | None = None

    # Priority (lower = higher priority; verification > inference)
    priority: int = Field(default=10, description="0=highest priority")

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self.compute_id()

    def compute_id(self) -> str:
        payload = json.dumps(
            {
                "task_type": self.task_type.value,
                "domain_id": self.domain_id,
                "requester_id": self.requester_id,
                "parameters": self.parameters,
                "created_at": self.created_at.isoformat(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def claim(self, evaluator_id: str) -> None:
        """Mark task as claimed by an evaluator."""
        self.status = TaskStatus.CLAIMED
        self.evaluator_id = evaluator_id
        self.claimed_at = datetime.now(timezone.utc)

    def complete(self, verified_performance: float | None = None, result: dict[str, Any] | None = None) -> None:
        """Mark task as completed with result."""
        self.status = TaskStatus.COMPLETED
        self.verified_performance = verified_performance
        self.result = result
        self.completed_at = datetime.now(timezone.utc)

    def fail(self, reason: str = "") -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.result = {"error": reason}
        self.completed_at = datetime.now(timezone.utc)


class TaskQueue(BaseModel):
    """In-memory ordered task queue for a node.

    Tasks are ordered by (priority, created_at).
    Evaluators pull the highest-priority pending task for domains they support.
    """

    tasks: dict[str, Task] = Field(default_factory=dict)

    def add(self, task: Task) -> None:
        """Add a task to the queue."""
        self.tasks[task.id] = task

    def get_pending(self, domain_id: str | None = None, limit: int = 10) -> list[Task]:
        """Get pending tasks, optionally filtered by domain.

        Returns tasks sorted by priority (ascending) then created_at.
        """
        pending = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.PENDING
            and (domain_id is None or t.domain_id == domain_id)
        ]
        pending.sort(key=lambda t: (t.priority, t.created_at))
        return pending[:limit]

    def get_pending_for_domains(self, domain_ids: list[str], limit: int = 10) -> list[Task]:
        """Get pending tasks for any of the given domains."""
        pending = [
            t for t in self.tasks.values()
            if t.status == TaskStatus.PENDING and t.domain_id in domain_ids
        ]
        pending.sort(key=lambda t: (t.priority, t.created_at))
        return pending[:limit]

    def claim(self, task_id: str, evaluator_id: str) -> Task | None:
        """Claim a pending task. Returns None if already claimed or not found."""
        task = self.tasks.get(task_id)
        if task is None or task.status != TaskStatus.PENDING:
            return None
        task.claim(evaluator_id)
        return task

    def complete(self, task_id: str, verified_performance: float | None = None, result: dict[str, Any] | None = None) -> Task | None:
        """Complete a claimed task with results."""
        task = self.tasks.get(task_id)
        if task is None or task.status != TaskStatus.CLAIMED:
            return None
        task.complete(verified_performance=verified_performance, result=result)
        return task

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING)

    @property
    def claimed_count(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status == TaskStatus.CLAIMED)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
