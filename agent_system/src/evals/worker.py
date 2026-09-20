"""Asynchronous evaluation worker and metrics computer.

Computes 5 primary evaluation metrics across recorded execution traces:
1. Intent Classification Accuracy
2. Schema Error Rate (including self-correction rate)
3. Retrieval Hit Rate
4. Policy Compliance Rate
5. Task Success Rate
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Any, Dict, List, Optional

from src.models.schemas import EvalMetrics

logger = logging.getLogger("AsyncEvalWorker")


class AsyncEvaluationWorker:
    """Consumes trace payloads asynchronously to evaluate system health and quality."""

    _instance: Optional[AsyncEvaluationWorker] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> AsyncEvaluationWorker:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AsyncEvaluationWorker, cls).__new__(cls)
                cls._instance._init_worker()
            return cls._instance

    def _init_worker(self) -> None:
        self.queue: queue.Queue = queue.Queue()
        self.processed_evals: List[Dict[str, Any]] = []
        self._is_running = True

        langsmith_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
        if langsmith_key:
            try:
                from langsmith import Client
                self.langsmith_client = Client()
                logger.info("LangSmith client connected for async evaluations.")
            except Exception as e:
                logger.warning(f"LangSmith initialization skipped: {e}")

        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def reset(self) -> None:
        """Resets evaluation state for clean test execution."""
        with self._lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    break
            self.processed_evals.clear()

    def submit_trace(self, eval_payload: Dict[str, Any]) -> None:
        """Enqueues an execution trace payload for asynchronous analysis."""
        self.queue.put(eval_payload)

    def _process_queue(self) -> None:
        while self._is_running:
            try:
                payload = self.queue.get(timeout=0.2)
                self._evaluate_single_trace(payload)
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in async eval processing: {e}")

    def _evaluate_single_trace(self, payload: Dict[str, Any]) -> None:
        intent = payload.get("intent")
        conf = payload.get("intent_confidence", 0.0)
        is_intent_accurate = bool(intent and intent != "UNKNOWN" and conf >= 0.70)

        val_errors = payload.get("validation_errors", [])
        schema_had_errors = len(val_errors) > 0
        context = payload.get("active_context") or {}
        retrieval_hit = bool(context.get("patient") or context.get("doctor") or context.get("available_slots"))

        # Policy compliance: check if write was executed without authorization
        requires_conf = payload.get("requires_confirmation", False)
        approval_granted = payload.get("user_approval_granted")
        tool_result = payload.get("tool_result")
        policy_compliant = not (requires_conf and not approval_granted and tool_result and tool_result.get("success") and payload.get("selected_tool") == "RequestSlotReschedule")

        # Task success: tool succeeded, policy legitimately blocked, or rejected per user instruction
        policy_dec = payload.get("policy_decision") or {}
        task_success = bool(
            (tool_result and tool_result.get("success"))
            or (not policy_dec.get("allowed", True))
            or (payload.get("hitl_status") == "REJECTED")
            or (payload.get("final_response") and not payload.get("security_flag", False))
        )

        retries = payload.get("retry_count", 0)
        schema_had_errors = bool(len(val_errors) > 0 or retries > 0)
        self_corrected = bool(retries > 0 and task_success)

        record = {
            "trace_id": payload.get("trace_id"),
            "intent_accurate": is_intent_accurate,
            "schema_had_errors": schema_had_errors,
            "self_corrected": self_corrected,
            "retries": retries,
            "retrieval_hit": retrieval_hit,
            "policy_compliant": policy_compliant,
            "task_success": task_success,
            "total_latency_ms": payload.get("total_latency_ms", 0.0),
            "total_cost_usd": payload.get("total_cost_usd", 0.0),
        }

        with self._lock:
            self.processed_evals.append(record)

    def compute_metrics(self) -> EvalMetrics:
        """Computes aggregate metrics across all processed evaluations."""
        self.queue.join()
        with self._lock:
            evals = list(self.processed_evals)

        total = len(evals)
        if total == 0:
            return EvalMetrics()

        traces_with_retries = [e for e in evals if e.get("retries", 0) > 0 or e.get("schema_had_errors")]
        recovery_rate = (
            round(sum(1 for e in traces_with_retries if e.get("self_corrected")) / len(traces_with_retries), 4)
            if traces_with_retries
            else 1.0
        )

        return EvalMetrics(
            intent_accuracy=round(sum(1 for e in evals if e["intent_accurate"]) / total, 4),
            schema_error_rate=round(sum(1 for e in evals if e["schema_had_errors"]) / total, 4),
            self_correction_recovery_rate=recovery_rate,
            retrieval_hit_rate=round(sum(1 for e in evals if e["retrieval_hit"]) / total, 4),
            policy_compliance_rate=round(sum(1 for e in evals if e["policy_compliant"]) / total, 4),
            task_success_rate=round(sum(1 for e in evals if e["task_success"]) / total, 4),
            total_traces=total,
            avg_latency_ms=round(sum(e["total_latency_ms"] for e in evals) / total, 2),
            total_cost_usd=round(sum(e["total_cost_usd"] for e in evals), 7),
        )
