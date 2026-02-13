"""Tests for the Task model and TaskQueue."""

from doin_core.models.task import Task, TaskQueue, TaskStatus, TaskType


class TestTask:
    def test_create_verification_task(self):
        task = Task(
            task_type=TaskType.OPTIMAE_VERIFICATION,
            domain_id="mimo-v1",
            requester_id="optimizer-1",
            parameters={"learning_rate": 0.001},
            optimae_id="opt-123",
            reported_performance=-0.05,
            priority=0,
        )
        assert task.id  # Auto-generated
        assert task.status == TaskStatus.PENDING
        assert task.task_type == TaskType.OPTIMAE_VERIFICATION

    def test_create_inference_task(self):
        task = Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="mimo-v1",
            requester_id="client-1",
            parameters={"input": [1, 2, 3]},
            priority=10,
        )
        assert task.status == TaskStatus.PENDING
        assert task.optimae_id is None

    def test_claim_task(self):
        task = Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="test",
            requester_id="client",
        )
        task.claim("evaluator-1")
        assert task.status == TaskStatus.CLAIMED
        assert task.evaluator_id == "evaluator-1"
        assert task.claimed_at is not None

    def test_complete_task(self):
        task = Task(
            task_type=TaskType.OPTIMAE_VERIFICATION,
            domain_id="test",
            requester_id="optimizer",
        )
        task.claim("evaluator-1")
        task.complete(verified_performance=-0.03, result={"used_synthetic": True})
        assert task.status == TaskStatus.COMPLETED
        assert task.verified_performance == -0.03
        assert task.completed_at is not None

    def test_fail_task(self):
        task = Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="test",
            requester_id="client",
        )
        task.claim("evaluator-1")
        task.fail("OOM")
        assert task.status == TaskStatus.FAILED
        assert task.result == {"error": "OOM"}


class TestTaskQueue:
    def _make_queue(self) -> TaskQueue:
        q = TaskQueue()
        q.add(Task(
            task_type=TaskType.OPTIMAE_VERIFICATION,
            domain_id="mimo-v1",
            requester_id="opt-1",
            priority=0,
        ))
        q.add(Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="mimo-v1",
            requester_id="client-1",
            priority=10,
        ))
        q.add(Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="cnn-v1",
            requester_id="client-2",
            priority=10,
        ))
        return q

    def test_pending_count(self):
        q = self._make_queue()
        assert q.pending_count == 3

    def test_get_pending_all(self):
        q = self._make_queue()
        tasks = q.get_pending()
        assert len(tasks) == 3
        # Verification (priority=0) should come first
        assert tasks[0].task_type == TaskType.OPTIMAE_VERIFICATION

    def test_get_pending_by_domain(self):
        q = self._make_queue()
        tasks = q.get_pending(domain_id="cnn-v1")
        assert len(tasks) == 1
        assert tasks[0].domain_id == "cnn-v1"

    def test_get_pending_for_domains(self):
        q = self._make_queue()
        tasks = q.get_pending_for_domains(["mimo-v1", "cnn-v1"])
        assert len(tasks) == 3
        tasks = q.get_pending_for_domains(["cnn-v1"])
        assert len(tasks) == 1

    def test_claim_removes_from_pending(self):
        q = self._make_queue()
        pending = q.get_pending()
        task_id = pending[0].id

        claimed = q.claim(task_id, "evaluator-1")
        assert claimed is not None
        assert claimed.status == TaskStatus.CLAIMED
        assert q.pending_count == 2
        assert q.claimed_count == 1

    def test_claim_already_claimed_returns_none(self):
        q = self._make_queue()
        task_id = q.get_pending()[0].id
        q.claim(task_id, "evaluator-1")
        result = q.claim(task_id, "evaluator-2")
        assert result is None

    def test_complete_updates_status(self):
        q = self._make_queue()
        task_id = q.get_pending()[0].id
        q.claim(task_id, "evaluator-1")
        completed = q.complete(task_id, verified_performance=-0.01)
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
        assert q.completed_count == 1

    def test_complete_unclaimed_returns_none(self):
        q = self._make_queue()
        task_id = q.get_pending()[0].id
        # Try completing without claiming first
        result = q.complete(task_id, verified_performance=-0.01)
        assert result is None

    def test_verification_higher_priority_than_inference(self):
        """Verification tasks should always be served before inference."""
        q = TaskQueue()
        # Add inference first
        q.add(Task(
            task_type=TaskType.INFERENCE_REQUEST,
            domain_id="test",
            requester_id="client",
            priority=10,
        ))
        # Add verification second
        q.add(Task(
            task_type=TaskType.OPTIMAE_VERIFICATION,
            domain_id="test",
            requester_id="optimizer",
            priority=0,
        ))
        tasks = q.get_pending()
        assert tasks[0].task_type == TaskType.OPTIMAE_VERIFICATION
