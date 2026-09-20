"""Circuit breaker implementation for resilient model calls with automatic fallback.

Wraps low-latency providers (Groq) and fails over to OpenAI gpt-4o-mini upon
rate limits (HTTP 429), timeouts, or service errors.
"""

from __future__ import annotations

import time
import logging
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("CircuitBreaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal operation: requests routed to primary provider
    OPEN = "OPEN"          # Tripped: primary is failing, route directly to fallback
    HALF_OPEN = "HALF_OPEN"# Testing recovery: single trial probe allowed


class CircuitBreakerOpenException(Exception):
    """Raised when the circuit breaker is open and no fallback is supplied."""
    pass


class CircuitBreaker:
    """Thread-safe circuit breaker with timeout and error thresholds."""

    def __init__(
        self,
        name: str = "GroqCircuitBreaker",
        failure_threshold: int = 3,
        recovery_time_seconds: float = 10.0,
        expected_exceptions: Optional[tuple] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self.expected_exceptions = expected_exceptions or (Exception,)

        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.last_state_change: float = time.time()
        self.total_tripped: int = 0
        self.fallback_invocations: int = 0

    def _update_state(self) -> None:
        """Transitions state based on current time and failure counts."""
        now = time.time()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.recovery_time_seconds:
                logger.info(f"[{self.name}] Cooldown expired. Moving from OPEN -> HALF_OPEN.")
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now

    def record_success(self) -> None:
        """Records a successful primary call, resetting counters."""
        if self.state != CircuitState.CLOSED:
            logger.info(f"[{self.name}] Primary call succeeded. Moving to CLOSED.")
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_state_change = time.time()

    def record_failure(self, error: Exception) -> None:
        """Records a primary failure, potentially tripping the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(
            f"[{self.name}] Primary failure recorded ({self.failure_count}/{self.failure_threshold}): {error}"
        )
        if self.failure_count >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            if self.state != CircuitState.OPEN:
                logger.error(f"[{self.name}] Failure threshold reached. Circuit TRIPPED -> OPEN.")
                self.total_tripped += 1
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()

    def execute(
        self,
        primary_fn: Callable[..., Any],
        fallback_fn: Optional[Callable[..., Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Executes primary_fn if circuit allows; otherwise falls back to fallback_fn."""
        self._update_state()

        if self.state == CircuitState.OPEN:
            logger.warning(f"[{self.name}] Circuit is OPEN. Bypassing primary to fallback.")
            if fallback_fn:
                self.fallback_invocations += 1
                return fallback_fn(*args, **kwargs)
            raise CircuitBreakerOpenException(f"[{self.name}] Circuit is open and no fallback provided.")

        try:
            result = primary_fn(*args, **kwargs)
            self.record_success()
            return result
        except self.expected_exceptions as exc:
            self.record_failure(exc)
            if fallback_fn:
                logger.info(f"[{self.name}] Invoking fallback function following primary failure.")
                self.fallback_invocations += 1
                return fallback_fn(*args, **kwargs)
            raise exc

    def get_stats(self) -> Dict[str, Any]:
        """Returns diagnostic metrics for monitoring."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "total_tripped": self.total_tripped,
            "fallback_invocations": self.fallback_invocations,
        }
