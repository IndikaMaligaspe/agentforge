"""
Template rendering engine for agentforge.
"""
from __future__ import annotations

from agentforge.schema.models import ProjectConfig, LEGACY_DEFAULT_PATTERN

# LEGACY_DEFAULT_PATTERN is imported from agentforge.schema.models — that module
# is the single source of truth for the "orchestrator" string.
# Used below when config.pattern is None (programmatically-built configs that
# did not pass through the before-validator).


def resolve_pattern(config: ProjectConfig) -> str:
    """
    Return the execution pattern directory name for the given config.

    For configs loaded from YAML (or any dict source), the schema's
    ``model_validator(mode="before")`` guarantees that ``config.pattern`` is
    always populated.  For configs built programmatically via Python keyword
    args, the before-validator may not have fired; in that case a ``None``
    pattern is treated as the legacy ``"orchestrator"`` equivalent.

    The return value is one of the ``_PATTERN_LITERALS`` members defined in
    ``agentforge.schema.models`` — the set of valid names lives there and is
    not re-declared here.

    Args:
        config: A validated ``ProjectConfig`` instance.

    Returns:
        The pattern directory name (e.g. ``"orchestrator"``).
    """
    if config.pattern is None:
        return LEGACY_DEFAULT_PATTERN
    return config.pattern
