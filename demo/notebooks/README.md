# Unity Gateway — Hands-on Demo (Installable)

A runnable, top-to-bottom demo of **Unity Gateway** governance for the SSE team, built for a
technical deep-dive. Each notebook stands alone and ends in a **governance proof point**.

> Verified live on an **Azure** Databricks workspace (Sep 2026). Syntax is real, not from docs —
> where the public docs differ (they are AWS-era), these notebooks use what actually works.

## What it demonstrates

| Notebook | Track / pillar | Proof point |
|----------|-------|-------------|
| `00_setup` | — | Prereqs, create catalog schemas, verify AI Gateway surface |
| `01_model_service_and_invoke` | FM API | Create a governed model service, call it → **HTTP 200**, tokens tracked |
| `02_rate_limits_429` | COST | Per-user rate limit → **HTTP 429** |
| `03_guardrails_beta` | CONTROL | Attach a service policy (PII/competitor) → **policy block** *(Beta — run live)* |
| `04_access_control_403` | CONTROL | UC `GRANT`/`REVOKE EXECUTE` → **HTTP 403** *(explained; not executed)* |
| `05_observability` | — | `system.ai_gateway.usage` SQL cookbook — every call, per user, cost |
| `06_mcp_services` | Agents | Register an MCP service + tool restrictions + **federation per user group** |
| `07_coding_agents` | Coding agents | `ug` CLI: govern Claude Code / Cursor / Codex / Copilot / Gemini |
| `08_claude_cowork_and_desktop` | Coding agents | Cowork/Desktop **Developer Mode** via `/ai-gateway/anthropic`; project-sharing trade-off; **Omnigent** |
| `09_traffic_routing_and_budgets` | CHOICE + COST | Traffic split 70/30, automatic **fallback**, **token budget** cap |
| `10_external_providers` | CHOICE | OpenAI / Anthropic / **Bedrock** / Foundry / Gemini as provider services *(reference; needs creds)* |

**Capability coverage:** model services (FMAPIs), external providers, traffic splitting + fallback,
rate limits + token budgets, guardrails/service policies (Beta), UC RBAC access control, MCP services +
tool restrictions + federation, coding agents (`ug`) and desktop agents (Cowork/Desktop Developer Mode),
observability (usage + inference tables + external spend), and the Omnigent (exploratory) pointer for
shared agent sessions.

## Install

1. **Clone into Databricks**: Workspace → Repos → *Add Repo* → this git URL (or import the folder).
2. **Attach** any notebook to **Serverless** compute (or a UC-enabled cluster).
3. **Set the widgets** at the top of `00_setup` (catalog / schema / model). Defaults:
   `catalog=sv_unity_gw`, `schema=ai_services`, `model_service=demo_llm`,
   `fmapi_model=databricks-claude-sonnet-4-6`.
4. **Run `00_setup` first**, then `01`…`07` in order.

## Prerequisites (see `../../FACTPACK.md` §10)

- Unity Catalog enabled; you can `CREATE` in the target catalog (default `sv_unity_gw`).
- Unity Gateway present: `system.ai_gateway.usage` exists (checked in `00_setup`).
- A SQL warehouse for `05_observability` (the demo uses `unity-gateway-demo`).
- **`03_guardrails`**: service policies are **Beta** — enable in the account console → Previews first.
- **`07_coding_agents`**: run on your laptop (the `ug` CLI is local), not in the workspace.

## How calls work on this workspace (verified)

- **Invoke**: `POST {host}/ai-gateway/mlflow/v1/chat/completions` with body
  `{"model": "<catalog.schema.service>", "messages": [...], "max_tokens": N}`.
- **Create** a model service: `POST /api/2.1/unity-catalog/model-services?parent=schemas/{cat}.{sch}&model_service_id={svc}`.
- Inside a notebook, host + token come from the notebook context (no PAT needed).

Full delivery context and the deck: `../../FACTPACK.md`, and the delivery-model Google Slides deck.
