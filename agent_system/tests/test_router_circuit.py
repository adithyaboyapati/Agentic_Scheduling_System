"""Unit tests for dual-provider ModelRouter, CircuitBreaker state transitions, and failover."""

import time
import pytest
from src.models.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from src.models.router import ModelRouter
from src.models.schemas import IntentType


def test_circuit_breaker_transitions_and_fallback():
    breaker = CircuitBreaker(
        name="TestBreaker",
        failure_threshold=2,
        recovery_time_seconds=0.5,
    )

    def failing_primary():
        raise RuntimeError("Primary provider connection timeout")

    def successful_fallback():
        return "fallback_result"

    assert breaker.state == CircuitState.CLOSED

    # 1st failure: still CLOSED
    res1 = breaker.execute(failing_primary, successful_fallback)
    assert res1 == "fallback_result"
    assert breaker.state == CircuitState.CLOSED

    # 2nd failure: trips to OPEN
    res2 = breaker.execute(failing_primary, successful_fallback)
    assert res2 == "fallback_result"
    assert breaker.state == CircuitState.OPEN
    assert breaker.total_tripped == 1

    # While OPEN, primary is bypassed
    res3 = breaker.execute(failing_primary, successful_fallback)
    assert res3 == "fallback_result"

    # Wait for cooldown to transition to HALF_OPEN
    time.sleep(0.6)

    def succeeding_primary():
        return "primary_success"

    # In HALF_OPEN, successful trial closes the circuit
    res4 = breaker.execute(succeeding_primary, successful_fallback)
    assert res4 == "primary_success"
    assert breaker.state == CircuitState.CLOSED


def test_model_router_groq_to_openai_failover():
    router = ModelRouter(force_offline_mode=False)

    # Test simulated Groq failure triggers fallback to gpt-4o-mini
    res, meta = router.classify_intent_and_extract(
        sanitized_input="Please reschedule my appointment to next week.",
        simulate_groq_failure=True,
    )

    assert meta["provider"] == "fallback_gpt4o_mini"
    assert meta["model"] == "gpt-4o-mini"
    assert res.intent == IntentType.RESCHEDULE_APPOINTMENT


def test_model_router_cost_calculation():
    router = ModelRouter()
    # 1000 input tokens, 200 output tokens on gpt-4o ($2.50 / $10.00)
    cost = router.calculate_cost("openai-gpt-4o", tokens_in=1000, tokens_out=200)
    expected = (1000 * 2.50 + 200 * 10.00) / 1_000_000.0
    assert cost == round(expected, 7)
