"""
agentforge CLI flags translator.

This module is the single source of truth for mapping CLI flag values to a
``dict`` patch that can be merged into a base ``ProjectConfig`` dict and
validated with ``ProjectConfig.model_validate``.

All functions here are **pure** — no I/O, no side-effects.  Commands call
``flags_to_config_patch(...)`` and then merge the result into their base
config dict before handing it to the schema validator.

Pattern / entry choices are derived at import time from the canonical Literal
type aliases in ``agentforge.schema.models`` via ``typing.get_args``, so this
module never hard-codes the allowed values.
"""
from __future__ import annotations

from typing import get_args

from ..schema.models import (
    _ENTRY_TYPE_LITERALS,
    _PATTERN_LITERALS,
)

# ── Derived choice tuples (single source of truth) ────────────────────────────

#: All valid pattern strings, e.g. ("react", "workflow", "fanout", "orchestrator", "planner")
PATTERN_CHOICES: tuple[str, ...] = get_args(_PATTERN_LITERALS)

#: All valid entry-type strings, e.g. ("intent_router", "passthrough", "direct")
ENTRY_TYPE_CHOICES: tuple[str, ...] = get_args(_ENTRY_TYPE_LITERALS)

#: Valid orchestrator kind strings (sourced directly from OrchestratorConfig.kind field).
ORCHESTRATOR_KIND_CHOICES: tuple[str, ...] = ("llm", "rule")

#: Valid tool kind strings.
TOOL_KIND_CHOICES: tuple[str, ...] = ("mcp", "http", "agent")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_class_name(key: str) -> str:
    """Convert a slug key to a PascalCase class name with 'Agent' suffix.

    Examples::

        _to_class_name("alpha")   -> "AlphaAgent"
        _to_class_name("my_bot")  -> "MyBotAgent"
        _to_class_name("sql")     -> "SqlAgent"
    """
    return "".join(word.capitalize() for word in key.split("_")) + "Agent"


def parse_agents(agents_csv: str | None) -> list[dict]:
    """Parse a comma-separated agent key string into a list of agent dicts.

    Each dict contains only ``key`` and ``class_name``; all other
    ``AgentConfig`` fields use their schema defaults when the dict is
    validated.

    Args:
        agents_csv: Comma-separated agent keys, e.g. ``"alpha,beta,my_bot"``.
            Leading/trailing whitespace around each key is stripped.
            Returns an empty list when *agents_csv* is ``None`` or empty.

    Returns:
        A list of ``{"key": str, "class_name": str}`` dicts.
    """
    if not agents_csv:
        return []
    return [
        {"key": key.strip(), "class_name": _to_class_name(key.strip())}
        for key in agents_csv.split(",")
        if key.strip()
    ]


def build_tool_entry(kind: str, name: str) -> dict:
    """Build a minimal tool entry dict for the given *kind* and *name*.

    The generated dict satisfies ``ProjectConfig.model_validate`` for each
    tool kind:

    - ``mcp``  — only requires ``name`` and ``description``; ``kind`` is the
      default so we include it explicitly for clarity.
    - ``http`` — additionally requires ``url``; we supply a placeholder that
      is a syntactically valid URL so the patch round-trips through
      ``model_validate``.  Callers should update ``url`` before using the
      config in production.
    - ``agent`` — additionally requires ``service_url`` and ``agent_key``;
      same placeholder approach as ``http``.

    Args:
        kind: One of ``"mcp"``, ``"http"``, or ``"agent"``.
        name: Slug-style name for the tool (must match ``^[a-z][a-z0-9_]*$``).

    Returns:
        A dict ready to append to an agent's ``tools`` list.
    """
    base: dict = {"kind": kind, "name": name, "description": f"{name} tool"}
    if kind == "http":
        base["url"] = "http://localhost/"
    elif kind == "agent":
        base["service_url"] = "http://localhost/"
        base["agent_key"] = name
    return base


# ── Public API ────────────────────────────────────────────────────────────────

def flags_to_config_patch(
    *,
    # Entry group (mutually exclusive — caller must enforce)
    entry_type: str | None = None,
    # Pattern group (mutually exclusive — caller must enforce)
    pattern: str | None = None,
    # Orchestrator kind
    orchestrator_kind: str | None = None,
    # Agents (comma-separated)
    agents_csv: str | None = None,
    # Tool flags (each is a list of names — may be specified multiple times)
    mcp_tools: list[str] | None = None,
    http_tools: list[str] | None = None,
    agent_tools: list[str] | None = None,
) -> dict:
    """Translate CLI flag values into a ``ProjectConfig``-compatible patch dict.

    The returned dict is a **partial** config that should be deep-merged into
    a base config dict (e.g. loaded from ``project.yaml``) before passing to
    ``ProjectConfig.model_validate``.  The function is **pure** — it performs
    no I/O and raises no Typer exceptions.

    Mutual exclusion for the entry and pattern flag groups is the caller's
    responsibility (``init_cmd.py`` enforces it before calling this function).

    Args:
        entry_type: One of the strings in :data:`ENTRY_TYPE_CHOICES`, or ``None``.
        pattern: One of the strings in :data:`PATTERN_CHOICES`, or ``None``.
        orchestrator_kind: ``"llm"`` or ``"rule"``, or ``None``.
        agents_csv: Comma-separated agent keys, e.g. ``"alpha,beta"``.
        mcp_tools: List of MCP tool names to append to each agent's tool list
            (applied globally — commands may scope this per-agent separately).
        http_tools: List of HTTP tool names (placeholder URL generated).
        agent_tools: List of agent-call tool names (placeholder URL generated).

    Returns:
        A dict containing only the keys that were explicitly set by flags.
        Keys not set are omitted so that merging preserves existing config.
    """
    patch: dict = {}

    # ── Entry ─────────────────────────────────────────────────────────────────
    if entry_type is not None:
        patch["entry"] = {"type": entry_type}

    # ── Pattern ───────────────────────────────────────────────────────────────
    if pattern is not None:
        patch["pattern"] = pattern

    # ── Orchestrator kind ─────────────────────────────────────────────────────
    if orchestrator_kind is not None:
        patch["orchestrator"] = {"kind": orchestrator_kind}

    # ── Agents ────────────────────────────────────────────────────────────────
    agent_list = parse_agents(agents_csv)
    if agent_list:
        patch["agents"] = agent_list

    # ── Tools — build a list from all tool flags ──────────────────────────────
    # Tools are attached to ALL agents declared via --agents; if no agents are
    # declared via flags the tools list is kept at the top level of the patch
    # so callers can apply it to the appropriate agent.
    tool_entries: list[dict] = []
    for name in (mcp_tools or []):
        tool_entries.append(build_tool_entry("mcp", name))
    for name in (http_tools or []):
        tool_entries.append(build_tool_entry("http", name))
    for name in (agent_tools or []):
        tool_entries.append(build_tool_entry("agent", name))

    if tool_entries:
        if agent_list:
            # Attach tools to every agent created by --agents.
            for agent in patch["agents"]:
                agent["tools"] = list(tool_entries)
        else:
            # No --agents flag: surface tools at the patch root so the caller
            # can decide where to attach them (e.g. add_cmd merges per agent).
            patch["tools"] = tool_entries

    return patch
