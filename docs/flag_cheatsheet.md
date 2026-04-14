# AgentForge v2 CLI Flag Cheatsheet

All flags are passed to `agentforge init`. When any v2 flag is supplied the
interactive wizard is skipped and the config is produced directly from the
flags.

## Flag Reference

| Flag | `project.yaml` field |
|------|----------------------|
| `--withIntentRouter` | `entry.type: intent_router` |
| `--withPassthrough` | `entry.type: passthrough` |
| `--withDirectInput` | `entry.type: direct` |
| `--withReactAgent` | `pattern: react` |
| `--withWorkflow` | `pattern: workflow` |
| `--withFanout` | `pattern: fanout` |
| `--withOrchestrator` | `pattern: orchestrator` |
| `--withPlanner` | `pattern: planner` |
| `--orchestratorKind [llm\|rule]` | `orchestrator.kind: llm` or `orchestrator.kind: rule` |
| `--agents A,B,C` | `agents[].key` (class names derived automatically) |
| `--mcp NAME` | `agents[].tools[].kind: mcp` + `name: NAME` |
| `--http NAME` | `agents[].tools[].kind: http` + `name: NAME` |
| `--agent NAME` | `agents[].tools[].kind: agent` + `name: NAME` |

At most one entry flag and at most one pattern flag may be given per invocation.
`--orchestratorKind` is only meaningful with `--withOrchestrator`.
Tool flags (`--mcp`, `--http`, `--agent`) may be repeated to attach multiple
tools; they are added to every agent created by `--agents`.

## Invocation Examples

**Campaign Health Score** — rule-based orchestrator with an intent router,
four agents, MCP and HTTP tools:

```bash
agentforge init \
  --withIntentRouter \
  --withOrchestrator --orchestratorKind rule \
  --agents campaign_scorer,insight_enricher,synthesizer,output_formatter \
  --mcp fetch_campaign_metrics \
  --http get_audience_insights
```

Full fixture: `examples/campaign_health.yaml`

**Co-pilot** — ReAct loop with passthrough entry, MCP and agent-call tools:

```bash
agentforge init \
  --withPassthrough \
  --withReactAgent \
  --agents copilot \
  --mcp get_ui_context \
  --agent campaign_health_check
```

Full fixture: `examples/copilot.yaml`

**Research Planner** — planner pattern with passthrough entry, all tool kinds:

```bash
agentforge init \
  --withPassthrough \
  --withPlanner \
  --agents researcher \
  --mcp knowledge_base_search \
  --http web_search \
  --agent summarise_source
```

Full fixture: `examples/planner.yaml`

**Creative Analysis Fanout** — fanout pattern with direct entry, MCP and HTTP:

```bash
agentforge init \
  --withDirectInput \
  --withFanout \
  --agents budget_analyzer,audience_analyzer,creative_analyzer \
  --mcp get_spend_breakdown \
  --http get_attention_score
```

Full fixture: `examples/fanout.yaml`

**Campaign Approval Workflow** — deterministic workflow with direct entry:

```bash
agentforge init \
  --withDirectInput \
  --withWorkflow \
  --agents campaign_ops \
  --mcp verify_creative_approval \
  --http submit_campaign
```

Full fixture: `examples/workflow.yaml`

## See Also

- `docs/migration_v1_to_v2.md` — upgrading from v1 configs
- `agentforge validate` — confirm your generated `project.yaml` is valid
