"""Phase 8: Core approval workflow and gates tests (12 tests)."""

from datetime import datetime

from backend.membrane.approval.workflow import (
    ApprovalRole,
    ApprovalDecision,
    ApprovalWorkflow,
    ApprovalRecord,
)
from backend.membrane.approval.gates import ApprovalGate
from backend.membrane.guiders.base import Decision


class TestApprovalWorkflow:
    """Test ApprovalWorkflow class."""

    def test_workflow_initialization(self):
        """Test workflow initializes empty."""
        workflow = ApprovalWorkflow()
        assert workflow.records == []
        assert workflow.cascade_verdict is None

    def test_set_cascade_verdict(self):
        """Test setting cascade verdict."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.BLOCK)
        assert workflow.cascade_verdict == Decision.BLOCK

    def test_check_cascade_gate_block(self):
        """Test cascade gate with BLOCK verdict."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.BLOCK)

        can_proceed, halt_reason = workflow.check_cascade_gate()
        assert not can_proceed
        assert halt_reason is not None
        assert "BLOCK" in halt_reason

    def test_check_cascade_gate_approve(self):
        """Test cascade gate with APPROVE verdict."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.APPROVE)

        can_proceed, halt_reason = workflow.check_cascade_gate()
        assert can_proceed
        assert halt_reason is None

    def test_check_cascade_gate_escalate(self):
        """Test cascade gate with ESCALATE verdict."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.ESCALATE)

        can_proceed, halt_reason = workflow.check_cascade_gate()
        assert can_proceed
        assert halt_reason is None

    def test_check_cascade_gate_none(self):
        """Test cascade gate with None verdict."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(None)

        can_proceed, halt_reason = workflow.check_cascade_gate()
        assert can_proceed
        assert halt_reason is None

    def test_record_approval(self):
        """Test recording approval."""
        workflow = ApprovalWorkflow()

        workflow.record_approval(
            approver_role=ApprovalRole.BUDGET_OWNER,
            decision=ApprovalDecision.APPROVE,
            principal="budget.owner@example.com",
            reasoning="Reviewed",
        )

        assert len(workflow.records) == 1
        assert workflow.records[0].approver_role == ApprovalRole.BUDGET_OWNER
        assert workflow.records[0].decision == ApprovalDecision.APPROVE

    def test_is_fully_approved(self):
        """Test dual approval check."""
        workflow = ApprovalWorkflow()

        # Only budget owner
        workflow.record_approval(
            approver_role=ApprovalRole.BUDGET_OWNER,
            decision=ApprovalDecision.APPROVE,
            principal="budget.owner@example.com",
        )
        assert not workflow.is_fully_approved()

        # Add treasurer
        workflow.record_approval(
            approver_role=ApprovalRole.TREASURER,
            decision=ApprovalDecision.APPROVE,
            principal="treasurer@example.com",
        )
        assert workflow.is_fully_approved()

    def test_is_rejected(self):
        """Test rejection detection."""
        workflow = ApprovalWorkflow()

        workflow.record_approval(
            approver_role=ApprovalRole.BUDGET_OWNER,
            decision=ApprovalDecision.REJECT,
            principal="budget.owner@example.com",
        )

        assert workflow.is_rejected()

    def test_get_result_with_block(self):
        """Test result when cascade blocks."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.BLOCK)

        result = workflow.get_result("test-job", "test-je")
        assert result.is_blocked
        assert not result.can_post
        assert result.halt_reason is not None

    def test_get_result_approved_and_can_post(self):
        """Test result when fully approved."""
        workflow = ApprovalWorkflow()
        workflow.set_cascade_verdict(Decision.APPROVE)

        workflow.record_approval(
            approver_role=ApprovalRole.BUDGET_OWNER,
            decision=ApprovalDecision.APPROVE,
            principal="budget.owner@example.com",
        )

        workflow.record_approval(
            approver_role=ApprovalRole.TREASURER,
            decision=ApprovalDecision.APPROVE,
            principal="treasurer@example.com",
        )

        result = workflow.get_result("test-job", "test-je")
        assert result.is_approved
        assert result.can_post
        assert not result.is_blocked


class TestApprovalGate:
    """Test ApprovalGate class."""

    def test_check_cascade_block(self):
        """Test gate rejects BLOCK verdict."""
        result = ApprovalGate.check_cascade_verdict(Decision.BLOCK)
        assert not result.passed
        assert result.reason is not None
        assert "BLOCK" in result.reason

    def test_check_cascade_approve(self):
        """Test gate accepts APPROVE verdict."""
        result = ApprovalGate.check_cascade_verdict(Decision.APPROVE)
        assert result.passed

    def test_check_cascade_escalate(self):
        """Test gate accepts ESCALATE verdict."""
        result = ApprovalGate.check_cascade_verdict(Decision.ESCALATE)
        assert result.passed

    def test_check_cascade_none(self):
        """Test gate accepts None verdict (backward compatibility)."""
        result = ApprovalGate.check_cascade_verdict(None)
        assert result.passed

    def test_check_approval_status_block(self):
        """Test approval gate rejects BLOCK verdict."""
        result = ApprovalGate.check_approval_status(True, Decision.BLOCK)
        assert not result.passed

    def test_check_approval_status_not_approved(self):
        """Test approval gate requires full approval."""
        result = ApprovalGate.check_approval_status(False, Decision.APPROVE)
        assert not result.passed

    def test_can_post_approved_and_approve(self):
        """Test can_post with full approval and APPROVE verdict."""
        can_post = ApprovalGate.can_post(True, Decision.APPROVE)
        assert can_post

    def test_can_post_not_approved(self):
        """Test can_post prevents posting without approval."""
        can_post = ApprovalGate.can_post(False, Decision.APPROVE)
        assert not can_post

    def test_can_post_cascade_block(self):
        """Test can_post prevents posting with BLOCK verdict."""
        can_post = ApprovalGate.can_post(True, Decision.BLOCK)
        assert not can_post

    def test_approval_record_to_dict(self):
        """Test ApprovalRecord serialization."""
        record = ApprovalRecord(
            approver_role=ApprovalRole.TREASURER,
            decision=ApprovalDecision.APPROVE,
            timestamp=datetime.utcnow(),
            principal="treasurer@example.com",
            reasoning="Approved",
        )

        data = record.to_dict()
        assert data["approver_role"] == "TREASURER"
        assert data["decision"] == "APPROVE"
        assert data["principal"] == "treasurer@example.com"
        assert data["reasoning"] == "Approved"

    def test_approval_result_to_dict(self):
        """Test ApprovalResult serialization."""
        from backend.membrane.approval.workflow import ApprovalResult

        result = ApprovalResult(
            job_id="test-job",
            je_id="test-je",
            cascade_verdict=Decision.APPROVE,
            is_approved=True,
            can_post=True,
        )

        data = result.to_dict()
        assert data["job_id"] == "test-job"
        assert data["je_id"] == "test-je"
        assert data["cascade_verdict"] == "APPROVE"
        assert data["is_approved"] is True
        assert data["can_post"] is True
