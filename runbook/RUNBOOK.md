# Unity Gateway — Live Demo Runbook (presenter guide)

How to show Unity Gateway governing **FM APIs**, **agents/MCP tools**, and **coding agents** on your
own workspace. Pairs with the notebook repo (`../demo/notebooks/`) and the delivery-model deck.

- **Workspace:** `https://adb-7405607317163570.10.azuredatabricks.net` (profile `DEFAULT`, Azure)
- **Catalog/schemas:** `sv_unity_gw.{ai_services, ai_policies, ai_inference}`
- **Model service:** `sv_unity_gw.ai_services.demo_llm` → Claude Sonnet 4-6 (already created)
- **SQL warehouse:** `unity-gateway-demo` (id `599bb5fa4485eb2b`, serverless, auto-stop 5m)

## Pre-flight (5 min before)
1. Warehouse `unity-gateway-demo` is running (first query auto-starts it).
2. Open the notebooks (imported under your workspace); attach to Serverless.
3. If demoing guardrails (Act 2b): confirm **service policies are enabled** (account console → Previews).
4. Have the deck open for the architecture slide (slide 6) and the 3-dimensions table (slide 9).

## The story (3 pillars): CHOICE · COST · CONTROL
Every AI call — model, MCP tool, or coding agent — goes through **one governed control point** in
Unity Catalog. Say that once up front, then prove it three times.

---

## Act 1 — FM APIs (governed model serving)  · notebook `01`, then `02`, then `05`
**Show:** a governed endpoint, a real call, then a budget stopping abuse — with zero client changes.

1. **`01_model_service_and_invoke`** — run top to bottom.
   - Point out the model service is a **UC securable** (`sv_unity_gw.ai_services.demo_llm`), created via API.
   - The call returns **HTTP 200**; highlight the `usage` block (tokens). *"That token count is now governed data."*
2. **`02_rate_limits_429`** — set 2 req/min, fire 4 calls.
   - Calls 1-3 → 200, call 4 → **HTTP 429 `REQUEST_LIMIT_EXCEEDED`**. *"COST pillar: the gateway enforced a budget, not the app."*
   - It auto-resets the limit at the end.
3. **`05_observability`** — run "your recent calls" + Query 2 (per-user).
   - *"One table, `system.ai_gateway.usage`, every call, attributed to me. This is how you see and control AI spend."*
   - Note ~5-30 min lag — run early calls before the session, or narrate the pre-loaded rows.

**Proof points landed:** 200 (governed) · 429 (budget) · usage row (observability).

---

## Act 2 — Agents & tools (MCP + guardrails)  · notebooks `06`, `03`, `04`
**Show:** the same governance applies to tools and content, not just models.

1. **`06_mcp_services`** — list the built-in `system.ai.*` MCP services (Slack, GitHub, web_search…).
   - Explain: register an external MCP server as a UC securable with **tool restrictions** (allow `get_*`,
     deny the rest) and `GRANT EXECUTE`. Show the `mcp_metadata` observability query.
2. **`03_guardrails_beta`** *(Beta — you run it live)* — attach `block_pii` and a custom
   "block competitors" UDF; send a PII / "Snowflake vs Databricks" prompt → **policy block** before the model.
   - *"CONTROL pillar: content policy, fail-closed, ranked (first DENY wins)."* Call out it's Beta.
3. **`04_access_control_403`** — walk the slide/SQL: the UC privilege chain (USE CATALOG → USE SCHEMA →
   EXECUTE) and the **403** a denied caller gets. (Explained, not run live — needs a 2nd identity.)

**Proof points landed:** tool governance + observability · policy block · RBAC/403.

---

## Act 1b (optional) — reliability + budgets  · notebook `09`
Show one endpoint doing **traffic split 70/30 + automatic fallback** and a **token budget** that blocks
overspend — reinforcing CHOICE + COST without any client change.

## Act 3 — Coding & desktop agents  · notebooks `07` (laptop), `08`, then `05`
**Show:** developers' own tools, governed, with per-developer cost — two on-ramps.

1. **CLI agents (`07`)** — on your laptop: `ug configure --workspace <this workspace>` then
   `ug configure --agents codex` (or claude-code / cursor / copilot / gemini). Launch the agent; show the
   **"Databricks AI Gateway"** indicator.
2. **Desktop agents (`08`)** — Claude Cowork / Desktop **Developer Mode**: static API key (bearer PAT),
   gateway base URL `…/ai-gateway/anthropic`, model ID `system.ai.claude-sonnet-5`, Test connection.
   Run the notebook's model-discovery + messages cells to prove the route live.
   - **Set the project-sharing expectation:** gateway mode keeps memory/context **private per user**; the
     provider's account-level shared projects don't carry over. It changes *where inference goes*, not
     where projects live.
   - **For shared agent sessions**, mention **Omnigent** (exploratory, open-source; sandboxed cloud
     sessions, shareable read-only URL) — position as dev/experimentation, not a production drop-in.
3. In **`05`** run the per-developer usage query — agent calls show under **each developer's identity**.
   Mention the central **Agent Configuration** (allowed models + MCP servers) → **MCP federation per user group**.

**Proof point landed:** governed-by-default coding + desktop agents, per-developer cost, federated tools.

## Also available (mention or show as time allows)
- **External providers (`10`)** — OpenAI / Anthropic / Bedrock / Foundry / Gemini governed the same way
  (provider services). CHOICE pillar, provider-agnostic.
- **Inference logging** — enable per-service to capture full request/response payloads to a Delta table.

---

## Close
Tie back to the **2-session STS delivery model** (deck slide 14): Session 1 stands up this governance
foundation once; Session 2 applies it to the customer's chosen track (FM serving **or** coding agents).
Scope to **GA**; track the roadmap (Smart routing, OmniAgent, Skills). Service policies = **Beta**.

## Gotchas (this workspace / Azure)
- **Invocation route** is `/ai-gateway/mlflow/v1/chat/completions` with the service FQN in `model` —
  **not** `/model-services/{fqn}/invocations` (that AWS-era path 400s here).
- Model services: **no SQL DDL** — REST/CLI/UI only. MCP services: same.
- **Guardrails** need Beta enablement; the REST attach path may 404 → use the UI.
- **403** demo needs a second principal without EXECUTE (don't revoke your own owner grant).
- Usage table lag ~5-30 min — pre-warm before a live audience.

## Teardown (optional)
```bash
# delete demo model service
databricks ai-gateway delete-model-service model-services/sv_unity_gw.ai_services.demo_llm --profile DEFAULT
# stop/delete the warehouse
databricks warehouses delete 599bb5fa4485eb2b --profile DEFAULT
# drop schemas (careful): DROP SCHEMA sv_unity_gw.ai_services CASCADE; ...
```
