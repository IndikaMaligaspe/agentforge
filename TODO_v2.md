# TODO: AgentForge v2 — Composable Agentic Primitives

## Context
AgentForge today scaffolds a single opinionated shape: `intent_router -> supervisor -> one-or-more agents` whose `agent.py` is a stub that calls `llm.invoke()` exactly once. Real ReAct tool loops, parallel fan-out, deterministic workflows with HITL, and planner/DAG patterns all require hand-editing the generated code today. v2 introduces **composable primitives** so `project.yaml` can express any of these shapes directly.

The planner pattern (PlanAndRunNode / SolverNode / ComposerNode, backed by a real ReAct `GraphAgent`) is being ported from `madgicx/agentic-cli/agentic_cli/templates/planner/`. The Campaign Health Score PRD (`madgicx/plans/Campaign_health_score/CAMPAIGN_HEALTH_SCORE_PRD.md`) is the forcing-function real-world validation target.

## Architecture Decision

### Primitive model (locked)
- **Entry types** (how the graph receives work): `intent_router` (LLM parses free text — existing `query_router_node`), `passthrough` (UI supplies intent; LLM only extracts inputs), `direct` (structured params, no LLM).
- **Execution patterns**: `react`, `workflow`, `fanout`, `orchestrator` (sub-kind `llm` | `rule`), `planner`.
- **Tool kinds**: `mcp` (existing), `http` (NEW httpx stub), `agent` (NEW cross-service — reuses TODO-8 JWT stack).

### Schema evolution strategy
Add top-level `entry: EntryConfig` and `pattern: Literal[...]` + per-pattern sub-configs. Old configs — which have neither — are rewritten at parse time by a Pydantic `model_validator(mode="before")` into:
```
entry.type: intent_router
pattern: orchestrator
orchestrator.kind: llm
```
This preserves the existing `query_router -> supervisor -> agents` topology byte-for-byte.

### Renderer strategy
One shared base set of templates (`base_agent.py.j2`, `state.py.j2`, `main.py.j2`, `README.md.j2`, etc.) plus a per-pattern overlay directory (`templates/patterns/{react,workflow,fanout,orchestrator,planner}/`). Renderer reads `config.pattern` and composes base + overlay. Legacy config goes through the `orchestrator/llm` overlay, which MUST be structurally identical to today's output.

### CLI translator
A single `agentforge/cli/flags.py` module maps flag bundles to schema mutations. Flags round-trip: every flag corresponds to exactly one schema field so `init -> load -> dump` is idempotent.

### Non-negotiable invariants
1. `examples/project.full.yaml` renders byte-identical to HEAD at end of v2.
2. Current 293 tests pass unmodified through TODO-v2-0 and TODO-v2-1.
3. No user action for migration — old YAMLs just keep working.
4. `src/auth/`-equivalents (generated `security/jwt.py` stack from TODO-8) are NOT reimplemented by the `agent` tool kind; it imports and reuses.

## Implementation Steps

### TODO-v2-0 (NON-NEGOTIABLE FIRST): Schema scaffolding + backwards-compat validator
- Files to modify: `agentforge/schema/models.py`
- Files to create: `tests/test_schema_v2_compat.py`
- What to implement:
  - Add `EntryConfig(type: Literal["intent_router","passthrough","direct"], screen_context_fields: list[str] | None = None)`.
  - Add `ReactConfig`, `WorkflowConfig`, `FanoutConfig`, `OrchestratorConfig(kind: Literal["llm","rule"])`, `PlannerConfig(max_replans: int = 2, validator_enabled: bool = True, composer_enabled: bool = True)`.
  - Add to `ProjectConfig`: `entry: EntryConfig | None`, `pattern: Literal[...] | None`, `react/workflow/fanout/orchestrator/planner: ... | None`.
  - Add `@model_validator(mode="before")` that detects legacy shape (no `entry`, no `pattern`, has `workflow.default_intent`, `len(agents) >= 1`) and injects `entry.type=intent_router`, `pattern=orchestrator`, `orchestrator.kind=llm`.
  - Forbid `workflow.enable_feedback_loop` / `enable_validation_node` except when resolved `pattern in {orchestrator, react}`.
- Schema changes: additive only. All new top-level fields default `None` and are omitted from `model_dump(exclude_none=True)` on legacy round-trip.
- Tests to add: legacy YAML → validated model has injected `entry`/`pattern`; round-trip dump of legacy YAML excludes new keys; invalid combos raise `ValidationError`.
- Acceptance: all 293 existing tests pass unchanged; new compat tests pass.
- Risk: Pydantic `exclude_none` must be enforced in `loader.dump` — otherwise legacy dump gains new keys and breaks byte-identity. Add explicit `model_dump(mode="json", exclude_none=True)` there.

### TODO-v2-1: Renderer pattern dispatch
- Files to modify: `agentforge/writer/scaffold.py`, `agentforge/engine/__init__.py` (or wherever Jinja env is built).
- Files to create: `agentforge/templates/patterns/orchestrator/` (move-or-symlink current supervisor/agent/workflow templates here).
- What to implement: resolver function `resolve_pattern(config) -> str` returning directory name; Jinja `ChoiceLoader` that prefers `patterns/{pattern}/X.j2` then falls back to `templates/X.j2`.
- Tests to add: `tests/test_renderer_dispatch.py` — legacy config resolves to `orchestrator`; rendered file tree identical to pre-TODO tree (golden compare).
- Acceptance: `examples/project.full.yaml` still renders byte-identical.
- Risk: template-set explosion. Mitigation: every pattern overlay owns at most `agent.py.j2`, `workflow.py.j2` (or pattern-specific orchestrator node), plus one pattern-local node file. Everything else stays shared.

### TODO-v2-2: Fix `react` scaffold — real ReAct loop
- Files to create: `agentforge/templates/patterns/react/agent.py.j2`, `agentforge/templates/patterns/react/graph_agent.py.j2`.
- What to implement: port `GraphAgent` from `agentic-cli` templates — agent node ↔ tool node cycle until `finish_reason=="stop"` or `max_steps`. Drop Madgicx-specific mixins (account scoping, campaign context).
- Schema: `ReactConfig(max_steps: int = 12, tool_choice: Literal["auto","required"] = "auto")`.
- Generated deps: add `langgraph>=0.2` prebuilt tool node helpers (verify already present in `pyproject.toml.j2`).
- Tests to add: render `pattern: react` fixture; AST-compile generated `agent.py`; snapshot test. Unit test: mock LLM returns tool_call → state → tool result → final message.
- Acceptance: generated `react` project executes a two-step tool loop in a unit test.
- Risk (embed in template header comment): **BREAKING for anyone who overrode the old stub `agent.py`**. Call this out in migration docs. Orchestrator pattern preserves single-invoke behavior so legacy projects are unaffected.

### TODO-v2-3: `fanout` templates
- Files to create: `agentforge/templates/patterns/fanout/orchestrator_node.py.j2`, `agentforge/templates/patterns/fanout/reducer_node.py.j2`, `agentforge/templates/patterns/fanout/workflow.py.j2`.
- What to implement: static N-way parallel — `orchestrator_node` emits `Send(agent_key, sub_state)` per configured agent; reducer merges returns by `Annotated[list, operator.add]` on `state.fanout_results`.
- Schema: `FanoutConfig(reducer: Literal["concat","merge_dict"] = "concat")`.
- Tests to add: render Campaign Health Score-style fixture with 3 parallel agents; assert graph has 3 edges from orchestrator.
- Acceptance: AST-compile passes; LangGraph `compile()` call succeeds in test harness.

### TODO-v2-4: `workflow` templates (deterministic + HITL)
- Files to create: `agentforge/templates/patterns/workflow/workflow.py.j2` (state machine with `interrupt_before=["human_review"]`), `agentforge/templates/patterns/workflow/human_review_node.py.j2`.
- Schema: `WorkflowConfig(steps: list[StepConfig], hitl_before: list[str] = [])`.
- Generated deps: checkpointer already present (reuse `graph/postgres_with_saver.py.j2`).
- Tests to add: resume-from-interrupt unit test.
- Acceptance: `interrupt_before` values surface in compiled graph metadata.

### TODO-v2-5: `planner` templates (port from agentic-cli)
- Files to create: `agentforge/templates/patterns/planner/plan_and_run_node.py.j2`, `plan_precheck_node.py.j2`, `solver_node.py.j2`, `composer_node.py.j2`, `validator_node.py.j2`, `workflow.py.j2`.
- What to implement: port `PlanAndRunNode` (LLM produces JSON DAG), `PlanPrecheckNode` (structural pre-execution check — no LLM), concurrent `SolverNode` using `asyncio.gather` across independent plan steps, `ValidatorNode` (post-execution LLM check of plan coverage; triggers replan up to `max_replans`), `ComposerNode` (stitches results into final answer). Drop Madgicx-specific account/campaign mixins — keep inputs generic (`query: str`, `context: dict`).
- Graph edges: `plan → precheck → [solver | replan] → validate → [compose | replan]`. Precheck routes back to `plan` on failure (counts against `max_replans`); solver only runs if precheck passes.
- `PlanPrecheckNode` responsibilities (cheap, deterministic — no LLM call):
  1. JSON schema validation of the DAG shape.
  2. All `tool` refs resolve against the tool registry.
  3. All `deps` refs point to existing step ids; no cycles (topological sort).
  4. JSON Pointer `${stepN/...}` refs in args point to declared deps.
  5. Optional: per-tool arg schema check if the tool declares one.
  On failure, emits a structured error back to `PlanAndRunNode` for replan with the failure reason appended to the prompt.
- Schema: `PlannerConfig(max_replans: int = 2, max_concurrency: int = 4, precheck_enabled: bool = True, validator_enabled: bool = True, composer_enabled: bool = True)`.
- Risks embedded as scaffold header comments:
  - **State size**: plan results can balloon quickly; scaffold comment recommends summarisation step before ComposerNode and a checkpointer with TTL.
  - **Idempotency**: steps may be replayed on replan; scaffold comment warns tool authors to make `http` / `agent` tools idempotent or include idempotency keys.
- Tests to add: render planner fixture; AST-compile; unit test with mocked LLM returning a 3-step DAG; precheck unit tests for each failure class (bad tool ref, cycle, unresolved JSON Pointer); integration test where first plan fails precheck and second plan passes.
- Acceptance: generated planner project compiles, passes a replan round-trip test, and precheck rejects malformed DAGs before any tool executes.

### TODO-v2-6: Entry types `passthrough` and `direct`
- Files to create: `agentforge/templates/patterns/_entry/passthrough_node.py.j2`, `direct_entry.py.j2`.
- What to implement: `passthrough` — LLM extracts only `inputs` (intent supplied by caller in request body); `direct` — FastAPI endpoint accepts typed `inputs` model and bypasses LLM parsing entirely.
- Modify: `main.py.j2` to branch on `entry.type`.
- Tests to add: render each entry type; hit generated FastAPI endpoint in TestClient.
- Acceptance: all three entry types route to the same downstream pattern graph.

### TODO-v2-7: Tool kinds — `mcp`, `http`, `agent`
- Files to modify: `agentforge/schema/models.py` (promote `Tool` to tagged union on `kind`), `agentforge/templates/mcp_client.py.j2`.
- Files to create: `agentforge/templates/tools/http_tool.py.j2`, `agentforge/templates/tools/agent_tool.py.j2`, `agentforge/templates/tools/tool_registry.py.j2`.
- Schema: `McpTool`, `HttpTool(url, method, auth_env_var, timeout_s)`, `AgentTool(service_url, agent_key, auth_env_var)`. All three share `kind: Literal[...]` discriminator.
- `agent` tool implementation MUST import and reuse the JWT verifier stack generated by TODO-8 (`security/jwt.py`). Scaffold comment: "DO NOT copy the JWT logic here — import from `security.jwt`."
- `http` tool: httpx-based; OpenAPI ingestion explicitly DEFERRED (noted in scaffold TODO comment).
- Tests: render each tool kind; AST-compile; mock http/agent call in unit test.
- Acceptance: tool registry resolves all three kinds by string key.
- Risk: a config upgrade is required for any existing `mcp`-only tool declarations that don't currently have `kind` field. Handle in the TODO-v2-0 `model_validator(mode="before")`: default missing `kind` to `"mcp"`.

### TODO-v2-8: CLI flag surface + centralized translator
- Files to create: `agentforge/cli/flags.py`.
- Files to modify: `agentforge/cli/init_cmd.py`, `agentforge/cli/add_cmd.py`.
- Flags (1:1 with schema):
  - `--withIntentRouter` / `--withPassthrough` / `--withDirectInput` → `entry.type`
  - `--withReactAgent` / `--withWorkflow` / `--withFanout` / `--withOrchestrator` / `--withPlanner` → `pattern`
  - `--orchestratorKind {llm,rule}` → `orchestrator.kind`
  - `--agents A,B,C` → `agents[]`
  - `--mcp NAME` / `--http NAME` / `--agent NAME` → `tools[]` with `kind`
- Translator returns a `dict` patch merged into the base config; validation runs after.
- Tests: property test — every flag combination round-trips through `dump`/`load` unchanged.
- Acceptance: `agentforge init --withPlanner --agents alpha,beta --mcp foo --http bar` produces a valid `project.yaml` that loads.

### TODO-v2-9: Examples — per-pattern + real-world
- Files to create under `examples/`:
  - `examples/campaign_health.yaml` (`entry: intent_router`, `pattern: orchestrator`, `orchestrator.kind: rule`, 4 agents fanned by supervisor — expressibility target from CHS PRD)
  - `examples/copilot.yaml` (`entry: passthrough`, `pattern: react`, single `copilot` agent)
  - `examples/planner.yaml`
  - `examples/fanout.yaml`
  - `examples/workflow.yaml`
- Acceptance: each renders cleanly and its generated project AST-compiles.

### TODO-v2-10: Per-pattern render + AST-compile + snapshot tests
- Files to create: `tests/test_render_per_pattern.py`, `tests/snapshots/{pattern}/…`.
- For each pattern fixture: render to a `tmp_path`, walk generated tree, `compile(src, path, "exec")` every `.py` file, snapshot-compare the file list + a hash of each file body.
- Acceptance: 5 patterns × (tree snapshot + all-files AST-compile) all green.

### TODO-v2-11: Extend e2e full scaffold test
- Files to modify: `tests/e2e/test_full_scaffold.py`, `examples/project.full.yaml` stays frozen; add `examples/project.maximalist.yaml` that uses one of each pattern via a multi-entry config OR run the existing e2e once per pattern fixture.
- Acceptance: e2e passes across all patterns end-to-end (install deps, run pytest inside generated project).

### TODO-v2-12: Docs
- Files to create/modify: `README.md` (add per-pattern section), `docs/migration_v1_to_v2.md`, `docs/flag_cheatsheet.md`.
- Migration doc MUST flag:
  - ReAct stub override break (TODO-v2-2).
  - No action needed for users who didn't override.
  - Tool-kind default `mcp` injection.
- Acceptance: docs link-checked; examples in docs match actual fixtures.

### TODO-v2-13: Schema re-export + drift test
- Files to modify: `scripts/export_schema.py`, the JSON schema artifact, drift test.
- Acceptance: drift test passes against newly exported schema; no drift on subsequent runs.

### TODO-v2-14 (NON-NEGOTIABLE LAST): Byte-identity regression
- Files to create: `tests/test_byte_identity_v1.py`.
- What to implement: for every YAML under `examples/` that predates v2 (initially just `project.full.yaml`), render through current renderer and compare byte-for-byte against a committed golden tree checked in at TODO-v2-0 time.
- Acceptance: zero diff. If this test fails, v2 is not shippable.

### TODO-v2-15: Campaign Health Score v2 config fixture
- Files to create: `tests/fixtures/campaign_health_v2.yaml` (authored directly against the v2 schema), `tests/test_campaign_health_v2.py`.
- What to implement: render fixture, AST-compile, assert the generated workflow graph has the expected topology (intent_router node -> rule-based orchestrator -> 4 parallel agent nodes -> reducer). Plus a second fixture for the passthrough+react copilot.
- Acceptance: both renders clean and AST-compile; topology assertions pass.

## Risk Areas
1. **Byte-identity regression** (TODO-v2-14). Any accidental whitespace change to a shared template breaks it. Enforced by `test_byte_identity_v1` and by keeping `orchestrator/llm` overlay templates as the original files relocated — not rewritten.
2. **ReAct behavioral break** (TODO-v2-2). Only affects users who overrode the generated stub. Mitigated by: (a) orchestrator pattern keeps single-invoke semantics, (b) migration doc, (c) the change requires an explicit `pattern: react` opt-in.
3. **Planner state size + idempotency** (TODO-v2-5). Scaffold comments + doc warnings. No runtime safety net — by design, generated code is user-owned.
4. **Agent-tool JWT reuse** (TODO-v2-7). A reimplementation here would fork the auth stack. Enforced by code review checklist + scaffold import-only comment.
5. **Template-set explosion**. Mitigated by shared-base + per-pattern-overlay via Jinja `ChoiceLoader` (TODO-v2-1).
6. **Pydantic legacy-dump leak**. `model_dump(exclude_none=True)` must be set in `loader.dump` in TODO-v2-0 or legacy round-trips gain new keys.

## Test Requirements
- Schema compat tests (TODO-v2-0): legacy injection, invalid combos, exclude_none round-trip.
- Per-pattern render + AST-compile + snapshot (TODO-v2-10).
- Unit tests for ReAct loop, fanout reducer, workflow interrupt/resume, planner replan, each tool kind.
- CLI flag round-trip property test (TODO-v2-8).
- Extended e2e full scaffold (TODO-v2-11).
- Byte-identity regression (TODO-v2-14) — the ship gate.
- Campaign Health Score fixture + copilot fixture (TODO-v2-15).

---

Does this plan look correct? Should I adjust anything before we start implementation? Specifically, please confirm:
1. The TODO-v2-0 strategy of `model_validator(mode="before")` + `exclude_none=True` in `loader.dump` is acceptable for backwards-compat (vs. a separate `v1.py` model).
2. Relocating current templates under `templates/patterns/orchestrator/` in TODO-v2-1 is acceptable — the alternative (leaving them in place and overlaying only for non-orchestrator patterns) is slightly less symmetric but avoids touching existing files.
3. `examples/project.maximalist.yaml` (TODO-v2-11) as a single-file multi-pattern e2e is acceptable, or whether you prefer per-pattern separate e2e runs.
