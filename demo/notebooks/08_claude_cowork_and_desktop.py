# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Claude Cowork / Desktop through the gateway (Developer Mode)
# MAGIC Beyond the `ug` CLI (notebook 07), desktop agents like **Claude Cowork** and **Claude Desktop**
# MAGIC route through Unity Gateway via their **Developer Mode** third-party-inference settings — so an org
# MAGIC can adopt them on its Databricks commit (governance + cost) instead of separate provider seats.
# MAGIC
# MAGIC > Generic capability walkthrough. The `/ai-gateway/anthropic` route below is verified on this workspace.

# COMMAND ----------

import requests, json
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# COMMAND ----------

# MAGIC %md ## Developer Mode setup (what you enter in the app)
# MAGIC In Claude Cowork / Desktop → **Developer Mode → Configure third-party inference → Gateway**:
# MAGIC
# MAGIC | Field | Value |
# MAGIC |-------|-------|
# MAGIC | Create a token | Databricks **PAT** (Settings → Developer → Access tokens); use a **service principal OAuth** token for production |
# MAGIC | Credential kind | **Static API key** |
# MAGIC | Gateway auth scheme | **bearer** |
# MAGIC | Gateway API key | paste the PAT |
# MAGIC | **Gateway base URL** | `https://<workspace-host>/ai-gateway/anthropic` |
# MAGIC | **Model ID** | a UC model-service name, e.g. `system.ai.claude-sonnet-5` (or your own `catalog.schema.service`) |
# MAGIC | Then | **Test connection** → **restart** the client into gateway mode |
# MAGIC
# MAGIC Confirm inference lands **in the workspace** (`system.ai_gateway.usage`), not on the provider backend.

# COMMAND ----------

# MAGIC %md ## Model discovery — what the app's model picker calls
# MAGIC `GET /ai-gateway/anthropic/v1/models` returns the governed Claude models available to route to.

# COMMAND ----------

r = requests.get(f"{HOST}/ai-gateway/anthropic/v1/models", headers=H)
print("HTTP", r.status_code)
for m in r.json().get("data", []):
    print("  ", m.get("id"), "|", m.get("display_name"))

# COMMAND ----------

# MAGIC %md ## The exact call the desktop app makes (Anthropic message shape)
# MAGIC `POST /ai-gateway/anthropic/v1/messages` — same route the client uses once configured.

# COMMAND ----------

MODEL = "system.ai.claude-sonnet-5"   # or a model-service FQN like sv_unity_gw.ai_services.demo_llm
r = requests.post(f"{HOST}/ai-gateway/anthropic/v1/messages", headers=H,
                  json={"model": MODEL, "max_tokens": 64,
                        "messages": [{"role": "user", "content": "Reply in one line: routed through Unity Gateway."}]})
print("HTTP", r.status_code)
print(json.dumps(r.json(), indent=2)[:600])

# COMMAND ----------

# MAGIC %md ## Trade-off to set expectations: project sharing
# MAGIC A key thing to say out loud in a session:
# MAGIC - **Gateway mode** — memory and context are **private per user**; the app sends *inference only* to
# MAGIC   Databricks. You get governance, cost visibility, and no separate provider seats.
# MAGIC - **Provider account-level inference** — shared projects / shared instructions are a provider
# MAGIC   **account-level** feature that runs on their backend; that sharing does **not** carry over in gateway mode.
# MAGIC
# MAGIC So gateway mode changes **where inference goes**, not where projects live. Frame it as a deliberate
# MAGIC trade-off: centralized governance + cost in exchange for provider-side shared projects.

# COMMAND ----------

# MAGIC %md ## MCP federation per user group
# MAGIC Publish a central **Agent Configuration** (AI Gateway → Governance → Agent Configuration) that lists the
# MAGIC MCP servers each group may use, and enforce it with UC `GRANT EXECUTE ON MCP SERVICE ... TO <group>`.
# MAGIC Different user groups get different tool sets — **federation per user group** — all logged in
# MAGIC `system.ai_gateway.usage` under each developer's identity. (See notebook 06 for MCP services.)

# COMMAND ----------

# MAGIC %md ## For shared, cloud-based agent sessions: Omnigent (exploratory)
# MAGIC When teams want to **collaborate on shared agent context** (not just private per-user sessions),
# MAGIC point them to **Omnigent** — an open-source Databricks project that sits above coding agents
# MAGIC (Claude Code, Codex, others):
# MAGIC - Runs agent sessions inside a **Databricks-managed sandbox** (work persists in the cloud, survives
# MAGIC   closing the laptop).
# MAGIC - Sessions **shareable via URL** (viewer experience is read-only today — "review & follow along").
# MAGIC - Actively developed, ~weekly releases.
# MAGIC
# MAGIC **Position carefully:** early-stage / exploratory, **not** a production drop-in replacement — good for
# MAGIC dev/experimentation. Docs: `learn.microsoft.com/azure/databricks/omnigent` · `omnigent.ai`.

# COMMAND ----------

# MAGIC %md ## Per-developer cost & usage (after some agent activity)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT requester, count(*) AS calls, sum(coalesce(total_tokens,0)) AS total_tokens,
# MAGIC        collect_set(destination_model) AS models_used
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE api_type ILIKE '%anthropic%' AND event_time >= current_date() - INTERVAL 7 DAYS
# MAGIC GROUP BY requester ORDER BY total_tokens DESC LIMIT 50;
