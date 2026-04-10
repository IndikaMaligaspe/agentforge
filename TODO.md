# TODO: Backport campaign-health-score improvements into agentforge (template layer)

## Context

We are backporting ten TODO items from `../madgicx/plans/AgentForge/TODO-upstream-contributions.md` into the agentforge scaffolding repo. Three features are in scope:

1. **Optional structlog JSON logging** — gated by `observability.structured_logging`
2. **Router vendor-neutrality (OpenAI/Anthropic)** — gated by `workflow.router_llm_provider`
3. **Optional multi-provider registry** — gated by top-level `enable_provider_registry`

**Critical reminder:** agentforge is a Jinja2 scaffolder. Every feature must be delivered as (a) a Pydantic schema field + (b) one or more `.j2` templates + (c) conditional wiring in the renderer. Nothing in this backport adds a runtime dependency to agentforge itself — structlog, langchain-anthropic, etc. belong in the generated project's `requirements.txt.j2`, not in agentforge's own environment.

Reference source files (read, port, generalize — do not copy FB/Google Ads specifics):

- `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/observability/logging.py`
- `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/tests/test_structlog_setup.py`
- `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/middleware/logging_middleware.py`
- `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/graph/nodes/query_router_node.py`
- `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/config/provider_registry.py`

---

## Design Decisions

### (a) Conditional-rendering mechanism

Today, `agentforge/engine/renderer.py` walks a static `STATIC_TEMPLATE_MAP: list[tuple[str, str]]` (lines 251-272). There is zero conditional rendering — every template renders every time.

**Chosen mechanism: predicate-tuple shape with an optional third element.**

We will change the type to:

```
STATIC_TEMPLATE_MAP: list[tuple[str, str] | tuple[str, str, Callable[[ProjectConfig], bool]]]
```

During `render_all`, if a tuple has a third element, call it with `config`; skip the template if it returns `False`. If no predicate, render unconditionally (preserves existing behaviour byte-for-byte).

**Why this over alternatives:**

- **Post-filter pass**: rejected — harder to reason about because templates would render first, then get thrown away.
- **Dict-of-lists by feature-flag**: rejected — too much structural churn for three flags, and new contributors would have to learn the taxonomy.
- **Separate `CONDITIONAL_TEMPLATE_MAP` list**: rejected — splits logic and order across two lists; ordering of the final write sequence becomes implicit.

Predicate tuples are minimally invasive: existing entries don't change, new entries opt in, and the renderer diff is ~5 lines.

For the **template-swap** case (TODO-3: pick between `logging.py.j2` and `logging_structlog.py.j2` for the same output path), we will NOT solve it with two predicated entries competing for the same path (error-prone). Instead, we introduce a tiny helper that resolves the template name from the config:

```
def _resolve_logging_template(config: ProjectConfig) -> str: ...
```

and register the entry with a computed source in a dedicated codepath (or via a fourth tuple-element variant: `(resolver_callable, rel_path)`). **Final choice:** extend `STATIC_TEMPLATE_MAP` entries to also allow the first element to be a `Callable[[ProjectConfig], str]` instead of a literal string. The renderer calls it to get the template name at render time. This keeps everything in one list, preserves order, and naturally handles swaps.

Summary of the new tuple shapes allowed in `STATIC_TEMPLATE_MAP`:

1. `(template_name: str, rel_path: str)` — existing, always renders.
2. `(template_name: str, rel_path: str, predicate: Callable[[ProjectConfig], bool])` — render only if predicate is true.
3. `(resolver: Callable[[ProjectConfig], str], rel_path: str)` — resolve template name at render time (swap).
4. `(resolver: Callable[[ProjectConfig], str], rel_path: str, predicate: Callable[[ProjectConfig], bool])` — combined.

The renderer will dispatch on `callable(entry[0])` and `len(entry) == 3`.

### (b) Context-alias strategy

`_build_context` currently flattens deeply-nested values into short top-level keys (`enable_feedback_loop`, `enable_auth`, `router_llm_model`, etc.). Templates overwhelmingly use the short aliases.

**Chosen strategy: continue using short top-level aliases for every new flag**, to stay consistent with how every other flag is consumed in the templates today. Specifically, add:

- `structured_logging` — from `config.observability.structured_logging`
- `router_llm_provider` — from `config.workflow.router_llm_provider`
- `enable_provider_registry` — from `config.enable_provider_registry`

Templates will reference them as `{% if structured_logging %}`, `{% if router_llm_provider == "anthropic" %}`, etc. We will NOT use nested paths like `{{ observability.structured_logging }}` in the new templates — inconsistent with the rest of the codebase.

Note: the full nested dict is still available in the context via `data = config.model_dump()`, so templates that prefer nested access keep working.

### (c) Ordering rationale

The renderer-refactor TODO must land first, because TODO-3, TODO-5, and TODO-9 depend on conditional/swap rendering. Inside each feature, schema changes land before templates, templates land before renderer wiring, renderer wiring lands before tests. The snapshot regression test is last so the golden bytes reflect the post-refactor output (with all flags off).

Top-level order:

1. Renderer-level conditional rendering refactor (TODO-1)
2. Schema flags for all three features (TODO-2)
3. Structlog templates + wiring (TODO-3, TODO-4, TODO-5, TODO-6)
4. Router vendor neutrality (TODO-7, TODO-8)
5. Provider registry (TODO-9, TODO-10)
6. Docs (TODO-11)
7. Regression snapshot test (TODO-12)
8. End-to-end integration test with all flags on (TODO-13)

---

## Backwards Compatibility

When a user scaffolds a project with a `project.yaml` that does NOT mention any of the new flags, the following must all remain true:

1. All three new flags default to their pre-backport behaviour:
   - `observability.structured_logging = False`
   - `workflow.router_llm_provider = "openai"`
   - `enable_provider_registry = False`
2. The set of rendered files is byte-identical to the pre-refactor output.
3. `requirements.txt` contains the existing unconditional `structlog>=24.1.0` line exactly as today (Option B: we intentionally leave this untouched to preserve byte-identical output for existing scaffolds — see TODO-4).
4. `requirements.txt` does NOT contain `langchain-anthropic`.
5. `backend/observability/logging.py` is rendered from `logging.py.j2` (stdlib `JsonFormatter` path).
6. `backend/graph/nodes/query_router_node.py` imports `ChatOpenAI` from `langchain_openai` with the `model=` kwarg.
7. `backend/middleware/logging_middleware.py` contains no `clear_contextvars()` call.
8. No `backend/config/provider_registry.py` file exists.
9. No `backend/tests/test_structlog_setup.py` file exists.
10. The `project.yaml.j2` output for an "all-flags-off" project renders the same bytes as before.

The regression test in TODO-12 enforces this via a golden snapshot.

---

## Implementation Steps

### TODO-1: Refactor `TemplateRenderer` to support conditional and swap rendering

- **Goal:** Add the conditional-rendering mechanism described in Design Decision (a) without changing any scaffold output today.
- **Files to create/modify:**
  - `agentforge/engine/renderer.py`
- **What to implement:**
  - Change the type annotation of `STATIC_TEMPLATE_MAP` to accept the four tuple shapes described above.
  - Update the loop in `render_all` (lines 96-99) to:
    1. Resolve the template name (literal or via callable).
    2. Evaluate the predicate (if present); skip if false.
    3. Otherwise render normally.
  - No existing entries in `STATIC_TEMPLATE_MAP` change in this TODO. The shape becomes flexible but every current entry stays a 2-tuple.
  - Add inline comments explaining the four tuple shapes for future contributors.
- **Acceptance criteria:**
  - `pytest tests/test_renderer.py` passes unchanged.
  - `pytest tests/` passes overall.
  - Scaffolding against `tests/fixtures/minimal.yaml` and `tests/fixtures/full.yaml` produces byte-identical output to before the refactor (verify manually with `diff -r`).
- **Test coverage expected:**
  - No new tests in this TODO; existing tests guard the no-op behaviour.

### TODO-2: Add all three schema flags in one commit

- **Goal:** Land the three Pydantic fields up front so template work can reference them.
- **Files to create/modify:**
  - `agentforge/schema/models.py`
  - `tests/test_schema.py` (add validation cases)
  - `tests/fixtures/full.yaml` (optionally extend to exercise all flags)
- **What to implement:**
  - In `ObservabilityConfig` (around line 182) add:
    - `structured_logging: bool = Field(False, description="Use structlog for JSON logging ...")`
  - In `WorkflowConfig` (around line 145) add:
    - `router_llm_provider: Literal["openai", "anthropic"] = Field("openai", description="LLM provider used in query_router_node classification.")`
  - In `ProjectConfig` (around line 213, alongside `security`) add:
    - `enable_provider_registry: bool = Field(False, description="Generate backend/config/provider_registry.py ...")`
  - Add an optional `@model_validator(mode="after")` on `WorkflowConfig` that issues a `warnings.warn(...)` (NOT a `ValueError`) when `router_llm_provider == "anthropic"` and `router_llm_model.value` starts with `gpt-`, or vice versa. Keep it a warning — mixing is legal, just likely a mistake.
  - Update the docstring example of `ProjectConfig` (lines 217-255) to mention the new flags and their defaults.
  - Extend `tests/test_schema.py` with cases that:
    - Default value of `structured_logging` is `False`.
    - Default value of `router_llm_provider` is `"openai"`.
    - Default value of `enable_provider_registry` is `False`.
    - Invalid value for `router_llm_provider` (e.g., `"gemini"`) raises `ValidationError`.
    - Provider/model mismatch triggers the warning but still validates.
- **Acceptance criteria:**
  - All existing schema tests still pass.
  - New tests pass.
  - A `project.yaml` that omits all three flags validates identically to before.
- **Test coverage expected:**
  - Schema tests for each new field (default, override, invalid value, mismatch warning).

### TODO-3: Create `logging_structlog.py.j2` template

- **Goal:** Add a new, opt-in structlog-based logging template ported from campaign-health-score, generalized for arbitrary scaffolded projects.
- **Files to create/modify:**
  - `agentforge/templates/logging_structlog.py.j2` (new)
- **What to implement:**
  - Port `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/observability/logging.py` (209 lines) into a Jinja template.
  - Parameterize where the existing `logging.py.j2` parameterizes: `{{ project_name }}`, `{{ log_rotation_bytes }}`, `{{ log_backup_count }}`, and iterate `{{ context_fields }}` for per-request contextvars.
  - Drop any `log_with_props` backward-compat shim from the source — new scaffolds shouldn't inherit dead code.
  - Do NOT port FB/Google Ads specifics — there should be none in the logging module, but double-check.
  - Do NOT wire this into the renderer yet — that happens in TODO-5.
- **Acceptance criteria:**
  - The file exists and is a valid Jinja template (no syntax errors; `env.get_template("logging_structlog.py.j2")` succeeds).
  - Manually rendering it against a sample context produces valid Python (pass it through `ast.parse()`).
- **Test coverage expected:**
  - Deferred to TODO-6.

### TODO-4: Leave `structlog` in `requirements.txt.j2` untouched (Option B)

- **Goal:** Preserve byte-identical backwards compatibility for existing scaffolds by NOT wrapping the pre-existing unconditional `structlog>=24.1.0` line.
- **Files to create/modify:**
  - None.
- **What to implement:**
  - **Decision: Option B.** agentforge's current `requirements.txt.j2` already ships `structlog>=24.1.0` as an unconditional dependency on line 33. It is pre-existing cruft — the current stdlib-based `logging.py.j2` does not import it — but scaffolded projects receive the dep regardless. We intentionally leave this line alone to avoid changing any existing scaffold's `requirements.txt`.
  - Because structlog is already always present, the structlog logging template (TODO-3) can `import structlog` unconditionally in its rendered output without needing any conditional on the deps side.
  - Do NOT add a second conditional `structlog` line either — the one that exists is sufficient.
- **Acceptance criteria:**
  - `requirements.txt.j2` is unchanged from `master`.
  - Rendered `requirements.txt` bytes for any config (flag on or off) match today's bytes exactly (guarded by the regression snapshot in TODO-13).
- **Test coverage expected:**
  - Covered by the TODO-13 regression snapshot (all flags off) and TODO-14 integration test (all flags on).

### TODO-5: Wire renderer to swap between `logging.py.j2` and `logging_structlog.py.j2`

- **Goal:** Use the swap capability added in TODO-1 to pick the right logging template based on the flag.
- **Files to create/modify:**
  - `agentforge/engine/renderer.py`
- **What to implement:**
  - Define a module-level helper `_resolve_logging_template(config: ProjectConfig) -> str` that returns `"logging_structlog.py.j2"` if `config.observability.structured_logging` else `"logging.py.j2"`.
  - Change the `STATIC_TEMPLATE_MAP` entry currently at line 263:
    - From: `("logging.py.j2", "backend/observability/logging.py")`
    - To: `(_resolve_logging_template, "backend/observability/logging.py")`
  - No other entries change.
- **Acceptance criteria:**
  - Scaffolding with `structured_logging=False` renders the stdlib template to `backend/observability/logging.py`.
  - Scaffolding with `structured_logging=True` renders the structlog template to the same path.
  - Existing tests still pass.
- **Test coverage expected:**
  - Extend the rendering tests (see TODO-6) to cover both paths.

### TODO-6: Agentforge-level test for the structlog template

- **Goal:** Add a test that scaffolds a project with `structured_logging=True` and asserts the expected content.
- **Files to create/modify:**
  - `tests/test_structlog_template.py` (new)
  - `tests/fixtures/structlog.yaml` (new, or extend `full.yaml`)
- **What to implement:**
  - Load a fixture config with `structured_logging: true`.
  - Call `TemplateRenderer().render_all(config)`.
  - Assert the file at `backend/observability/logging.py` contains `import structlog`.
  - Assert the file at `requirements.txt` contains `structlog>=24.1.0` (Option B: the line is always there, regardless of the flag — this is a sanity check that it is reachable).
  - Ast-parse the rendered `logging.py` to confirm it is valid Python.
  - Also add a case with `structured_logging=False` that asserts the rendered `logging.py` does NOT contain `import structlog` (stdlib template used). The `requirements.txt` structlog line stays present in both cases under Option B.
- **Acceptance criteria:**
  - New test file passes.
  - Existing tests unchanged.
- **Test coverage expected:**
  - Both branches of the flag.

### TODO-7: Update `logging_middleware.py.j2` for structlog branch

- **Goal:** When `structured_logging=True`, the middleware should use `clear_contextvars()` and structlog-native calls. When false, unchanged.
- **Files to create/modify:**
  - `agentforge/templates/logging_middleware.py.j2`
- **What to implement:**
  - Wrap the imports in `{% if structured_logging %}`:
    - Add `from structlog.contextvars import bind_contextvars, clear_contextvars`.
  - At the start of `dispatch()`, when the flag is on, call `clear_contextvars()` before setting the request id.
  - Replace the `extra={"props": {...}}` logging calls with native structlog-style calls when the flag is on (e.g., `logger.info("request_started", method=..., path=..., ...)`).
  - Keep the existing stdlib path 100% unchanged when the flag is off.
  - Reference: `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/middleware/logging_middleware.py`.
- **Acceptance criteria:**
  - Both branches render without Jinja errors.
  - Both branches produce valid Python (ast-parse).
  - Backwards-compat branch output is byte-identical to the current template output.
- **Test coverage expected:**
  - Extend `tests/test_structlog_template.py` to render both middleware branches and assert key substrings.

### TODO-8: Add structlog project-level test template

- **Goal:** Scaffolded projects with `structured_logging=True` should get a smoke test file automatically.
- **Files to create/modify:**
  - `agentforge/templates/test_structlog_setup.py.j2` (new)
  - `agentforge/engine/renderer.py` (register the new entry with a predicate)
- **What to implement:**
  - Port `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/tests/test_structlog_setup.py` into a Jinja template. Generalize away any project-specific paths or module imports.
  - Register the template in `STATIC_TEMPLATE_MAP` with the conditional 3-tuple form:
    - `("test_structlog_setup.py.j2", "backend/tests/test_structlog_setup.py", lambda c: c.observability.structured_logging)`
- **Acceptance criteria:**
  - With flag on, file is generated at `backend/tests/test_structlog_setup.py`.
  - With flag off, file does not exist in the output.
  - The generated file parses as valid Python and imports work (verified at scaffold time via ast-parse).
- **Test coverage expected:**
  - Extend `tests/test_structlog_template.py` with both-branches assertion on file presence.

### TODO-9: Update `query_router_node.py.j2` for OpenAI/Anthropic split

- **Goal:** Render the router to use either `ChatOpenAI` or `ChatAnthropic` based on `router_llm_provider`.
- **Files to create/modify:**
  - `agentforge/templates/query_router_node.py.j2`
  - `agentforge/templates/requirements.txt.j2`
  - `agentforge/engine/renderer.py` (add `router_llm_provider` to `_build_context`)
- **What to implement:**
  - In `_build_context`, add `data["router_llm_provider"] = config.workflow.router_llm_provider` alongside the other workflow aliases (line ~226).
  - In `query_router_node.py.j2`:
    - Wrap the import in `{% if router_llm_provider == "anthropic" %} ... {% else %} ... {% endif %}`.
    - Wrap the LLM instantiation similarly. **Gotcha:** Anthropic uses `model_name=`, OpenAI uses `model=`. The rest of the line (`temperature=0`) is identical.
    - Reference: `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/graph/nodes/query_router_node.py`.
  - In `requirements.txt.j2`:
    - Add a conditional block:
      ```
      {% if router_llm_provider == "anthropic" %}
      langchain-anthropic>=0.1.0,<0.4.0
      {% endif %}
      ```
    - The pin range is intentional — the Anthropic LangChain integration has had breaking changes in minor versions.
- **Acceptance criteria:**
  - Scaffolding with default config (`router_llm_provider="openai"`) produces byte-identical router and requirements files to today.
  - Scaffolding with `router_llm_provider="anthropic"` produces a router that imports `ChatAnthropic` and a requirements file with `langchain-anthropic`.
  - Ast-parse of both variants succeeds.
- **Test coverage expected:**
  - New tests in `tests/test_renderer.py` (or a dedicated `tests/test_router_provider.py`) that cover both providers and assert the import statement and constructor kwarg.

### TODO-10: Create `provider_registry.py.j2` template (generic, no FB/Google Ads)

- **Goal:** Port the multi-provider abstraction from campaign-health-score, stripped of any domain-specific provider definitions.
- **Files to create/modify:**
  - `agentforge/templates/provider_registry.py.j2` (new)
  - `agentforge/templates/providers.yaml.j2` (new, optional sample config)
- **What to implement:**
  - Start from `/Users/indikamaligaspe/code4zeero/madgicx/campaign-health-score/backend/config/provider_registry.py`.
  - **Keep:** abstract `ProviderConfig` / `ProviderSpec` / `MetricMapping` dataclasses (or equivalents), a `ProviderRegistry` class, a `register()` API, a `get(name)` API.
  - **Strip:** all references to Facebook, Google Ads, or any other concrete provider. Remove any hardcoded `facebook` / `google_ads` literals, enums, or config.
  - Add a commented-out example at the bottom of the template showing how a user would register a custom provider.
  - Render a minimal `providers.yaml` that's an empty placeholder with comments explaining the schema.
  - Do NOT wire into renderer yet — that happens in TODO-11.
- **Acceptance criteria:**
  - Template file exists and is a valid Jinja template.
  - Manual render against a sample context produces valid Python (ast-parse).
  - No string `"facebook"` or `"google"` or `"ads"` appears in the rendered file (grep check).
- **Test coverage expected:**
  - Deferred to TODO-11.

### TODO-11: Wire `provider_registry.py.j2` with predicate + add tests

- **Goal:** Only render the provider-registry files when the flag is on.
- **Files to create/modify:**
  - `agentforge/engine/renderer.py`
  - `tests/test_provider_registry_template.py` (new)
- **What to implement:**
  - Add `data["enable_provider_registry"] = config.enable_provider_registry` in `_build_context`.
  - Add two predicated entries to `STATIC_TEMPLATE_MAP`:
    - `("provider_registry.py.j2", "backend/config/provider_registry.py", lambda c: c.enable_provider_registry)`
    - `("providers.yaml.j2", "backend/config/providers.yaml", lambda c: c.enable_provider_registry)`
  - Add tests that:
    - With flag off, neither file appears in `render_all` output.
    - With flag on, both files appear and contain expected sentinel strings.
- **Acceptance criteria:**
  - Both tests pass.
  - Default scaffold output (flag off) unchanged.
- **Test coverage expected:**
  - Both branches of the flag; ast-parse of the generated registry module.

### TODO-12: Docs — README and project.yaml.j2 "Optional features" section

- **Goal:** Document the three new flags for end users.
- **Files to create/modify:**
  - `agentforge/README.md`
  - `agentforge/templates/project.yaml.j2`
- **What to implement:**
  - In `README.md`, add a section titled **Optional features** that documents:
    - `observability.structured_logging` — what it does, default (`false`), what files/deps change, "recommended for production/K8s".
    - `workflow.router_llm_provider` — what it does, default (`"openai"`), values, what files/deps change.
    - `enable_provider_registry` — what it does, default (`false`), what files are generated.
  - In `project.yaml.j2`, add commented-out lines showing each flag under its respective section. Do NOT uncomment them by default — the rendered `project.yaml` must stay backwards-compatible for all-flags-off scaffolds.
- **Acceptance criteria:**
  - `README.md` renders cleanly as GitHub markdown.
  - The example in the README validates against `ProjectConfig` (add a quick test if reasonable).
  - Rendered `project.yaml` for a default config is byte-identical to before.
- **Test coverage expected:**
  - Snapshot test in TODO-13 will catch any accidental output changes.

### TODO-13: Regression snapshot test — all flags OFF

- **Goal:** Lock in backwards compatibility by snapshotting the full scaffold output and failing on any future drift.
- **Files to create/modify:**
  - `tests/test_scaffold_snapshot.py` (new)
  - `tests/fixtures/snapshots/default_scaffold/` (new directory with golden files)
- **What to implement:**
  - Create a test that scaffolds a project from a canonical fixture (`tests/fixtures/minimal.yaml` with all new flags omitted).
  - Walk every rendered file and compare byte-for-byte against a committed golden snapshot.
  - On first run, the test generates the snapshot (behind a `--update-snapshots` flag or env var). On every subsequent run, it asserts equality.
  - The snapshot should be generated AFTER all earlier TODOs are merged so it reflects the final state.
- **Acceptance criteria:**
  - Test fails loudly if any template's default-config output changes.
  - Test passes on a clean run of the backport branch.
  - Snapshot files are committed to the repo.
- **Test coverage expected:**
  - Full-project snapshot.
  - If the scaffold includes non-deterministic content (timestamps, UUIDs), sanitize before comparison.

### TODO-14: End-to-end integration test — all flags ON

- **Goal:** Sanity-check that a project scaffolded with every new flag enabled produces a coherent, importable output.
- **Files to create/modify:**
  - `tests/test_integration.py` (extend existing)
  - `tests/fixtures/all_flags_on.yaml` (new)
- **What to implement:**
  - Create a fixture that sets:
    ```yaml
    observability:
      structured_logging: true
    workflow:
      router_llm_provider: anthropic
      router_llm_model: claude-3-haiku-20240307
    enable_provider_registry: true
    ```
  - Scaffold to a temp dir.
  - Ast-parse every generated `.py` file. Assert zero parse errors.
  - Grep the generated `requirements.txt` for `structlog`, `langchain-anthropic`.
  - Grep the generated `query_router_node.py` for `ChatAnthropic`, `model_name=`.
  - Grep the generated `logging.py` for `import structlog`.
  - Assert `backend/config/provider_registry.py` and `backend/tests/test_structlog_setup.py` exist.
- **Acceptance criteria:**
  - Integration test passes.
  - All generated Python parses cleanly.
- **Test coverage expected:**
  - End-to-end smoke; not a runtime test (we don't pip install and execute the generated project).

---

## Risk Areas

1. **Renderer refactor ordering.** TODO-1 MUST land before any conditional templates. If TODO-3/5/8/11 are attempted before the refactor, they will fail because `STATIC_TEMPLATE_MAP` has no way to skip or swap entries.
2. **Pre-existing unconditional `structlog` in `requirements.txt.j2`.** Line 33 unconditionally installs `structlog`. Decision documented in TODO-4: **Option B** — leave the line untouched. This guarantees byte-identical backwards compatibility for existing scaffolds and means the new structlog logging template can `import structlog` unconditionally without any deps-side conditional. The cost is that `structured_logging=False` scaffolds still ship the unused dep, which is the pre-existing state.
3. **`langchain-anthropic` version drift.** The Anthropic LangChain integration has had breaking changes in minor versions. Pin as `>=0.1.0,<0.4.0` and revisit before release.
4. **Template parameterization creep.** When porting `logging_structlog.py.j2`, resist the urge to expose every line as a Jinja variable. Only parameterize what the existing `logging.py.j2` parameterizes: `project_name`, `log_rotation_bytes`, `log_backup_count`, `context_fields`.
5. **Generalizing `provider_registry.py`.** The source file is campaign-health-score-specific. Grep the port aggressively for `facebook`, `google`, `ads`, `campaign` and strip every match. The rendered output must be fully generic.
6. **Jinja `StrictUndefined`.** The renderer uses `StrictUndefined` (line 61), so any typo in a new context alias will blow up at render time. Every new alias must be added to `_build_context` before it can be referenced in a template.
7. **Test fixtures.** `tests/fixtures/full.yaml` and `minimal.yaml` may need to be extended (additively — do NOT change existing fields) to exercise new flags.
8. **Order of files in `render_all` output.** Adding new entries (provider registry, test file) changes list length and position. The snapshot test must account for this when all-flags-on, and must NOT see new files when all-flags-off.

---

## Test Requirements

Summary of tests added across this backport:

1. **Schema tests** (TODO-2) — defaults, overrides, invalid values, provider/model mismatch warning.
2. **Renderer unit tests** — unchanged tests still pass (TODO-1).
3. **Structlog template tests** (TODO-6) — both branches of `structured_logging`.
4. **Middleware template tests** (TODO-7) — both branches.
5. **Router template tests** (TODO-9) — both providers.
6. **Provider registry template tests** (TODO-11) — both branches of the flag.
7. **Regression snapshot test** (TODO-13) — locks in default (all-flags-off) output.
8. **End-to-end integration test** (TODO-14) — all-flags-on scaffold, ast-parse every file.

All new tests must live under `/Users/indikamaligaspe/code4zeero/agentforge/tests/`. Agentforge itself must NOT gain new runtime dependencies (no structlog, no langchain-anthropic in agentforge's own environment); everything goes into the generated project's `requirements.txt` via `requirements.txt.j2`.

---

Does this plan look correct? Should I adjust anything before we start implementation?
