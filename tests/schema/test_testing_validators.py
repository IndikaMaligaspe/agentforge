"""
Tests for the TestingConfig model validator (TODO-7).

Covers the check_benchmarks_require_deepeval validator on TestingConfig:
- enable_benchmarks=True, eval_framework="none" -> ValidationError.
- enable_benchmarks=True, eval_framework="deepeval" -> valid.
- enable_benchmarks=False, eval_framework="none" -> valid (defaults).
- enable_benchmarks=False, eval_framework="deepeval" -> valid (dep installed, tests off).
"""
import pytest
from pydantic import ValidationError

from agentforge.schema.models import TestingConfig


# ── Schema-level validator tests ──────────────────────────────────────────────

def test_benchmarks_true_framework_none_raises():
    """enable_benchmarks=True with eval_framework='none' must raise a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        TestingConfig(eval_framework="none", enable_benchmarks=True)

    errors = exc_info.value.errors()
    messages = [e["msg"] for e in errors]
    assert any("deepeval" in m for m in messages), (
        f"Expected error message mentioning 'deepeval', got: {messages}"
    )
    assert any("eval_framework" in m for m in messages), (
        f"Expected error message mentioning 'eval_framework', got: {messages}"
    )


def test_benchmarks_true_framework_deepeval_is_valid():
    """enable_benchmarks=True with eval_framework='deepeval' must not raise."""
    cfg = TestingConfig(eval_framework="deepeval", enable_benchmarks=True)
    assert cfg.eval_framework == "deepeval"
    assert cfg.enable_benchmarks is True


def test_benchmarks_false_framework_none_is_valid():
    """Default state — enable_benchmarks=False, eval_framework='none' — must not raise."""
    cfg = TestingConfig(eval_framework="none", enable_benchmarks=False)
    assert cfg.eval_framework == "none"
    assert cfg.enable_benchmarks is False


def test_benchmarks_false_framework_deepeval_is_valid():
    """enable_benchmarks=False with eval_framework='deepeval' must not raise.

    This covers the case where a user has installed the dep for evaluation purposes
    but has not yet turned on benchmark scaffolding.
    """
    cfg = TestingConfig(eval_framework="deepeval", enable_benchmarks=False)
    assert cfg.eval_framework == "deepeval"
    assert cfg.enable_benchmarks is False


def test_defaults_are_both_off():
    """TestingConfig() with no args must default to eval_framework='none', enable_benchmarks=False."""
    cfg = TestingConfig()  # type: ignore[call-arg]
    assert cfg.eval_framework == "none"
    assert cfg.enable_benchmarks is False


def test_error_message_is_actionable():
    """The validation error message must guide the user toward the correct fix."""
    with pytest.raises(ValidationError) as exc_info:
        TestingConfig(eval_framework="none", enable_benchmarks=True)

    full_text = str(exc_info.value)
    assert "deepeval" in full_text
    assert "eval_framework" in full_text
