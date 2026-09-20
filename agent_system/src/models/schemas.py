"""Pydantic schemas and type definitions for state, tools, intents, and traces."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Supported user intentions in the healthcare appointment system."""
    RESCHEDULE_APPOINTMENT = "RESCHEDULE_APPOINTMENT"
    CHECK_AVAILABILITY = "CHECK_AVAILABILITY"
    VIEW_APPOINTMENT = "VIEW_APPOINTMENT"
    CANCEL_APPOINTMENT = "CANCEL_APPOINTMENT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class EntityExtraction(BaseModel):
    """Structured entities extracted from user prompt and context."""
    patient_id: Optional[str] = Field(default=None, description="Patient identifier, e.g. P101")
    doctor_id: Optional[str] = Field(default=None, description="Doctor identifier, e.g. DOC1")
    appointment_id: Optional[str] = Field(default=None, description="Target appointment identifier, e.g. APT-201")
    target_date: Optional[str] = Field(default=None, description="Requested appointment date (YYYY-MM-DD)")
    target_slot: Optional[str] = Field(default=None, description="Requested slot timestamp, e.g. 2026-09-22T10:00:00")
    reason: Optional[str] = Field(default=None, description="Stated reason for rescheduling or inquiry")


class IntentClassificationResult(BaseModel):
    """Result of Step 2 Intent Classification and Entity Extraction."""
    intent: IntentType = Field(..., description="Classified intent")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score")
    entities: EntityExtraction = Field(default_factory=EntityExtraction, description="Extracted parameters")
    reasoning: str = Field(default="", description="Brief chain-of-thought or explanation for classification")


class PolicyDecisionResult(BaseModel):
    """Structured decision produced in Step 4 Policy Enforcement."""
    allowed: bool = Field(..., description="True if action complies with business & clinical rules")
    requires_confirmation: bool = Field(default=False, description="True if action is a high-risk write requiring HITL")
    policy_code: str = Field(..., description="Machine-readable rule code, e.g. POLICY_24H_OK or POLICY_24H_VIOLATION")
    reason: str = Field(..., description="Clinical/operational explanation for the decision")
    hours_until_appointment: Optional[float] = Field(default=None, description="Hours remaining before appointment starts")


class ToolSelection(BaseModel):
    """Selected tool for Step 5."""
    tool_name: str = Field(..., description="Registered name of the tool to execute")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Raw arguments to pass to the tool")


class ToolValidationResult(BaseModel):
    """Result of Step 6 Pydantic input validation."""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    validated_args: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list, description="Structured Pydantic error details")


class SelfCorrectionRecord(BaseModel):
    """Record of an automated self-correction dynamic feedback loop attempt."""
    attempt: int
    tool_name: str
    failed_args: Dict[str, Any]
    validation_errors: List[str]
    repaired_args: Dict[str, Any]
    correction_strategy: str  # "llm_reflection" | "deterministic_repair" | "slot_reconciliation"
    success: bool
    timestamp: Optional[str] = None


class ToolExecutionResult(BaseModel):
    """Result of Step 7 Tool Execution."""
    success: bool
    tool_name: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class TraceRecord(BaseModel):
    """Granular execution trace logged for each graph step."""
    trace_id: str
    step_name: str
    provider: str = Field(..., description="groq | openai | fallback_gpt4o_mini | deterministic | system")
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    ttft_ms: float = 0.0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    status: str = "success"
    timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvalMetrics(BaseModel):
    """Aggregate evaluation metrics calculated asynchronously in Step 12."""
    intent_accuracy: float = 0.0
    schema_error_rate: float = 0.0
    self_correction_recovery_rate: float = 0.0
    retrieval_hit_rate: float = 0.0
    policy_compliance_rate: float = 0.0
    task_success_rate: float = 0.0
    total_traces: int = 0
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
