"""
tests/test_docs.py — Documentation integrity tests for TODO-v2-12.

Verifies:
- Every relative file link and examples/ reference in README.md and the two
  new doc files points to a path that actually exists in the repo.
- Every pattern or entry type name mentioned inside code fences in those docs
  is in the schema's canonical Literal sets.
- Every CLI flag mentioned in flag_cheatsheet.md is registered in the CLI
  source (init_cmd.py or add_cmd.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

# ── Repo root ──────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent

# ── Files under test ──────────────────────────────────────────────────────
README = REPO_ROOT / "README.md"
MIGRATION_DOC = REPO_ROOT / "docs" / "migration_v1_to_v2.md"
FLAG_CHEATSHEET = REPO_ROOT / "docs" / "flag_cheatsheet.md"

DOC_FILES = [README, MIGRATION_DOC, FLAG_CHEATSHEET]

# ── CLI source files to grep for flag registration ─────────────────────────
CLI_INIT_CMD = REPO_ROOT / "agentforge" / "cli" / "init_cmd.py"
CLI_ADD_CMD = REPO_ROOT / "agentforge" / "cli" / "add_cmd.py"

# ── Schema literals (import at test-time so they can't drift) ─────────────
from agentforge.schema.models import _PATTERN_LITERALS, _ENTRY_TYPE_LITERALS  # noqa: E402

_VALID_PATTERNS: frozenset[str] = frozenset(get_args(_PATTERN_LITERALS))
_VALID_ENTRY_TYPES: frozenset[str] = frozenset(get_args(_ENTRY_TYPE_LITERALS))
_VALID_TOOL_KINDS: frozenset[str] = frozenset({"mcp", "http", "agent"})


# ── Helpers ────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_fence_contents(text: str) -> list[str]:
    """Return the body of every fenced code block in *text*."""
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)


def _relative_links_in_doc(text: str) -> list[str]:
    """
    Return all relative paths that look like file references.

    Matches:
    - Markdown links: [text](path)  — only bare paths, not http(s):// URLs
    - Backtick references: `examples/foo.yaml` or `docs/bar.md`
    """
    md_links = re.findall(r"\[.*?\]\(([^)]+)\)", text)
    backtick_refs = re.findall(r"`((?:examples|docs|tests|agentforge)/[^`]+)`", text)
    relative: list[str] = []
    for ref in md_links + backtick_refs:
        # Skip absolute URLs and anchors
        if ref.startswith(("http://", "https://", "#")):
            continue
        relative.append(ref)
    return relative


def _examples_in_code_fences(text: str) -> list[str]:
    """Return all 'examples/...' strings that appear inside code fences."""
    refs: list[str] = []
    for block in _code_fence_contents(text):
        refs.extend(re.findall(r"examples/[\w.\-/]+", block))
    return refs


# ── Tests: doc files exist ─────────────────────────────────────────────────

@pytest.mark.parametrize("doc_path", [README, MIGRATION_DOC, FLAG_CHEATSHEET])
def test_doc_file_exists(doc_path: Path) -> None:
    assert doc_path.exists(), f"Expected doc file not found: {doc_path}"


# ── Tests: relative links resolve ─────────────────────────────────────────

def _collect_links() -> list[tuple[Path, str]]:
    """Collect (doc_file, relative_link) pairs from all doc files."""
    pairs: list[tuple[Path, str]] = []
    for doc in DOC_FILES:
        if not doc.exists():
            continue
        text = _read(doc)
        for ref in _relative_links_in_doc(text):
            pairs.append((doc, ref))
    return pairs


@pytest.mark.parametrize("doc_path,ref", _collect_links())
def test_relative_link_target_exists(doc_path: Path, ref: str) -> None:
    """Every relative path referenced in a doc must point to an existing file."""
    target = (REPO_ROOT / ref).resolve()
    assert target.exists(), (
        f"Broken link in {doc_path.relative_to(REPO_ROOT)}: "
        f"'{ref}' -> {target} does not exist"
    )


# ── Tests: pattern/entry names in code fences are schema-valid ─────────────

def _collect_pattern_names() -> list[tuple[Path, str]]:
    """
    Extract 'pattern: <name>' occurrences from code fences in all doc files.
    Returns (doc_file, name) pairs.
    """
    pairs: list[tuple[Path, str]] = []
    for doc in DOC_FILES:
        if not doc.exists():
            continue
        text = _read(doc)
        for block in _code_fence_contents(text):
            for name in re.findall(r"pattern:\s+(\w+)", block):
                pairs.append((doc, name))
    return pairs


def _collect_entry_type_names() -> list[tuple[Path, str]]:
    """
    Extract 'type: <name>' inside entry blocks from code fences in all doc files.
    Uses a simple heuristic: look for 'type: <name>' that follows an 'entry:' line
    within the same code block, or a bare 'entry.type: <name>' line.
    """
    pairs: list[tuple[Path, str]] = []
    for doc in DOC_FILES:
        if not doc.exists():
            continue
        text = _read(doc)
        for block in _code_fence_contents(text):
            # Match 'entry.type: name' or 'type: name' preceded by 'entry:' in block
            pairs.extend(
                (doc, name)
                for name in re.findall(r"entry\.type:\s+(\w+)", block)
            )
            # Also catch bare 'type: <name>' lines where the name is a known entry type
            for name in re.findall(r"\btype:\s+(\w+)", block):
                if name in _VALID_ENTRY_TYPES:
                    pairs.append((doc, name))
    return pairs


def _collect_tool_kind_names() -> list[tuple[Path, str]]:
    """Extract tool 'kind: <name>' occurrences from code fences.

    Uses the list-item form '- kind: <value>' so that sub-config 'kind:' fields
    such as 'orchestrator.kind: rule' are not matched.
    """
    pairs: list[tuple[Path, str]] = []
    for doc in DOC_FILES:
        if not doc.exists():
            continue
        text = _read(doc)
        for block in _code_fence_contents(text):
            for name in re.findall(r"-\s+kind:\s+(\w+)", block):
                pairs.append((doc, name))
    return pairs


@pytest.mark.parametrize("doc_path,name", _collect_pattern_names())
def test_pattern_name_is_schema_valid(doc_path: Path, name: str) -> None:
    assert name in _VALID_PATTERNS, (
        f"Pattern '{name}' in {doc_path.relative_to(REPO_ROOT)} is not in schema "
        f"_PATTERN_LITERALS: {sorted(_VALID_PATTERNS)}"
    )


@pytest.mark.parametrize("doc_path,name", _collect_entry_type_names())
def test_entry_type_is_schema_valid(doc_path: Path, name: str) -> None:
    assert name in _VALID_ENTRY_TYPES, (
        f"Entry type '{name}' in {doc_path.relative_to(REPO_ROOT)} is not in schema "
        f"_ENTRY_TYPE_LITERALS: {sorted(_VALID_ENTRY_TYPES)}"
    )


@pytest.mark.parametrize("doc_path,name", _collect_tool_kind_names())
def test_tool_kind_is_schema_valid(doc_path: Path, name: str) -> None:
    assert name in _VALID_TOOL_KINDS, (
        f"Tool kind '{name}' in {doc_path.relative_to(REPO_ROOT)} is not a valid "
        f"tool kind: {sorted(_VALID_TOOL_KINDS)}"
    )


# ── Tests: flags in flag_cheatsheet.md are registered in CLI source ────────

def _flags_in_cheatsheet() -> frozenset[str]:
    """Derive the documented-flags set directly from flag_cheatsheet.md."""
    text = FLAG_CHEATSHEET.read_text(encoding="utf-8")
    return frozenset(re.findall(r"(--[A-Za-z][A-Za-z0-9]+)", text))


def _cli_source_text() -> str:
    """Return concatenated source of init_cmd.py and add_cmd.py."""
    parts = []
    for f in (CLI_INIT_CMD, CLI_ADD_CMD):
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


@pytest.mark.parametrize("flag", sorted(_flags_in_cheatsheet()))
def test_flag_registered_in_cli_source(flag: str) -> None:
    """Every flag documented in flag_cheatsheet.md must appear in the CLI source."""
    source = _cli_source_text()
    assert flag in source, (
        f"Flag '{flag}' mentioned in flag_cheatsheet.md but not found in "
        f"init_cmd.py or add_cmd.py"
    )


# ── Tests: migration doc regression guards ────────────────────────────────

def test_migration_doc_flags_react_breaking_change() -> None:
    """migration_v1_to_v2.md must document the ReAct breaking change and its mitigation."""
    text = MIGRATION_DOC.read_text(encoding="utf-8").lower()
    assert "breaking" in text
    assert "react" in text
    assert "orchestrator" in text  # the mitigation path
