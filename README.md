# Unity Gateway — Team Enablement Bundle

Enablement materials for the SSE team learning session on **Unity Gateway** (Databricks' unified
governance layer for AI — models, MCP tools, and coding agents; GA Aug 2026).

## Contents

| # | Deliverable | Where |
|---|-------------|-------|
| 1 | **Delivery-model deck** (Google Slides, 19 slides) | https://docs.google.com/presentation/d/1MKQjtXHVN784VjQ-TsTj156tWuCgOlq88f27Z0tbrzQ/edit |
| 2 | **Installable hands-on demo** (8 notebooks) | [`demo/notebooks/`](demo/notebooks/) — also imported to workspace at `/Users/simran.vanjani@databricks.com/unity-gateway-demo` |
| 3 | **Live-demo runbook** (presenter guide) | [`runbook/RUNBOOK.md`](runbook/RUNBOOK.md) |
| — | Source fact pack (cited) | [`FACTPACK.md`](FACTPACK.md) |
| — | Verified workspace specifics | [`demo/WORKING_NOTES.md`](demo/WORKING_NOTES.md) |

## Live resources created on workspace `DEFAULT` (Azure)
- Catalog/schemas: `sv_unity_gw.{ai_services, ai_policies, ai_inference}`
- Governed model service: `sv_unity_gw.ai_services.demo_llm` → Claude Sonnet 4-6
- Serverless SQL warehouse: `unity-gateway-demo` (id `599bb5fa4485eb2b`)

## Verified live
- Governed FM API call → **HTTP 200** · Rate limit → **HTTP 429**.
- Guardrails (Beta), MCP tool governance, and coding-agents (`ug`) steps are authored and ready to run.

See `runbook/RUNBOOK.md` to present it, and `demo/notebooks/README.md` to install it.
