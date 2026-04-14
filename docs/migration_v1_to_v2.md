# Migrating from AgentForge v1 to v2

## Short version: you probably do not need to do anything

For most users, no action is needed. V2 is fully backwards-compatible via
schema auto-migration. Existing `project.yaml` files that do not set `pattern`
or `entry` continue to work exactly as before — the schema before-validator
fills in safe defaults automatically before any validation or rendering step
runs.

Run `agentforge validate` at any time to confirm your config is still valid.

---

## Breaking changes

### 1. ReAct scaffold changed to a real ReAct loop (TODO-v2-2)

In v1, `agentforge init` produced a single-invoke agent stub. In v2, choosing
`pattern: react` generates a full, bounded ReAct tool-calling loop
(configurable via the `react.*` sub-config).

**Who is affected**: users who manually edited the old single-invoke scaffold
and then set `pattern: react` explicitly in their `project.yaml`.

**Who is NOT affected**: users who never set `pattern` at all — the
legacy-compat validator automatically assigns `pattern: orchestrator` to any
config that omits the field, which exactly preserves the pre-v2 single-invoke
behaviour.

**How to opt out explicitly**: add `pattern: orchestrator` to your
`project.yaml`. This is the recommended migration path for anyone who wants
to keep the prior behaviour while adopting v2 features in other areas:

```yaml
# Explicitly preserve v1 orchestrator behaviour
pattern: orchestrator
```

The legacy-compat validator already does this automatically for configs that
omit `pattern`, so custom stubs continue working unless the user explicitly
opts into `pattern: react`.

### 2. Tool-kind default injection (TODO-v2-0)

Existing `ToolConfig` entries that do not have a `kind` field are
auto-assigned `kind: "mcp"` by the schema before-validator before any
validation step runs.

**No user action needed.** The injection is transparent. If you open a
validated `project.yaml` in an editor you will see `kind: mcp` written out
explicitly, which you can leave or adjust to `kind: http` or `kind: agent`
as needed.

---

## v1 to v2 field mapping

| v1 field | v2 field | Notes |
|----------|----------|-------|
| _(absent)_ | `pattern` | Auto-set to `"orchestrator"` for v1 configs |
| _(absent)_ | `entry.type` | Optional in v2; no default is injected |
| `agents[].tools[].mcp_resource` | `agents[].tools[].kind: mcp` + `mcp_resource` | `kind` auto-injected if absent |
| _(absent)_ | `agents[].tools[].kind: http` | New in v2; requires `url`, `method` |
| _(absent)_ | `agents[].tools[].kind: agent` | New in v2; requires `service_url`, `agent_key` |
| _(absent)_ | `react.*` | New in v2; only used with `pattern: react` |
| _(absent)_ | `fanout.*` | New in v2; only used with `pattern: fanout` |
| _(absent)_ | `orchestrator.*` | New in v2; only used with `pattern: orchestrator` |
| _(absent)_ | `planner.*` | New in v2; only used with `pattern: planner` |
| _(absent)_ | `workflow_sm.*` | New in v2; only used with `pattern: workflow` |
| `workflow.*` | `workflow.*` | Unchanged; all v1 sub-fields still valid |
| `metadata.*` | `metadata.*` | Unchanged |
| `database.*` | `database.*` | Unchanged |
| `api.*` | `api.*` | Unchanged |
| `observability.*` | `observability.*` | Unchanged |
| `security.*` | `security.*` | Unchanged |

---

## If you want to adopt v2 features

Follow this checklist to move a v1 config to an explicit v2 config:

- [ ] Choose a pattern explicitly:
  ```yaml
  pattern: react      # bounded ReAct tool-call loop
  # pattern: workflow     # deterministic state-machine
  # pattern: fanout       # parallel fan-out to N agents
  # pattern: orchestrator # LLM or rule-based supervisor dispatch
  # pattern: planner      # decompose-solve-validate-compose loop
  ```

- [ ] Pick an entry type (optional but recommended for clarity):
  ```yaml
  entry:
    type: intent_router   # LLM parses free text and routes by intent
  # type: passthrough       # caller supplies intent; LLM extracts inputs
  # type: direct            # structured params arrive; no LLM at entry
  ```

- [ ] Optionally add `kind:` to each tool explicitly:
  ```yaml
  tools:
    - kind: mcp
      name: my_tool
      mcp_resource: my_tool
    - kind: http
      name: external_api
      url: https://example.com/api/v1/endpoint
      method: POST
      auth_env_var: EXTERNAL_API_KEY
    - kind: agent
      name: downstream_service
      service_url: https://example.com/service/
      agent_key: target_agent
      auth_env_var: SERVICE_JWT
  ```

- [ ] Run `agentforge validate` to confirm the config is accepted.

---

## Flag cheatsheet cross-reference

For the non-interactive CLI flags that write these fields directly into
`project.yaml` without a wizard session, see `docs/flag_cheatsheet.md`.
