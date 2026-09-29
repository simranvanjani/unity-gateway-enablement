# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · MCP Services — govern tools (agents track)
# MAGIC Unity Gateway governs **MCP tool servers** the same way it governs models: as UC securables with
# MAGIC access grants, **tool restrictions**, and observability. This covers the "agents" ask.

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")

import requests, json
CATALOG = dbutils.widgets.get("catalog"); SCHEMA = dbutils.widgets.get("schema")
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# COMMAND ----------

# MAGIC %md ## Built-in MCP services (available now, no registration)
# MAGIC Every workspace ships governed MCP services under `system.ai.*` (Slack, GitHub, Gmail,
# MAGIC Google Drive/Calendar, Microsoft 365, Atlassian, web_search, sandbox).

# COMMAND ----------

r = requests.get(f"{HOST}/api/2.1/unity-catalog/mcp-services",
                 headers=H, params={"parent": "schemas/system.ai", "view": "FULL"})
for s in r.json().get("mcp_services", []):
    print(s.get("name"), "|", json.dumps(s.get("config", {}))[:120])

# COMMAND ----------

# MAGIC %md ## Register your own external MCP server (3 steps)
# MAGIC An MCP service wraps a UC **HTTP connection** to an external server. (Databricks Apps / Genie
# MAGIC cannot be registered as MCP services — external URLs only.)
# MAGIC
# MAGIC **Step 1 — UC HTTP connection** to the MCP server:
# MAGIC ```sql
# MAGIC CREATE CONNECTION IF NOT EXISTS demo_mcp_conn
# MAGIC   TYPE HTTP
# MAGIC   OPTIONS (host 'https://your-mcp-server.example.com', port '443', base_path '/');
# MAGIC ```
# MAGIC (Add `bearer_token secret('scope','key')` if the server needs auth.)

# COMMAND ----------

# MAGIC %md
# MAGIC **Step 2 — Create the MCP service** referencing that connection, with tool restrictions.
# MAGIC Created via the `ai-gateway` API/CLI (SQL DDL for MCP services is not supported).

# COMMAND ----------

def create_mcp_service(catalog, schema, name, connection_fqn, include=None, exclude=None):
    body = {"config": {"source_connection": {"name": f"connections/{connection_fqn}"}}}
    # Tool restrictions: prefix rules evaluated in order (first match wins). Field name may vary by
    # workspace version — confirm via `databricks ai-gateway create-mcp-service --help` / the UI.
    if include or exclude:
        body["config"]["tool_restrictions"] = (
            [{"include": p} for p in (include or [])] + [{"exclude": p} for p in (exclude or [])])
    r = requests.post(f"{HOST}/api/2.1/unity-catalog/mcp-services",
                      headers=H, params={"parent": f"schemas/{catalog}.{schema}", "mcp_service_id": name},
                      json=body)
    return r.status_code, r.text

# Example (uncomment once your connection exists):
# code, resp = create_mcp_service(CATALOG, SCHEMA, "demo_mcp",
#     f"{CATALOG}.{SCHEMA}.demo_mcp_conn", include=["get_*", "search"], exclude=["*"])
# print(code, resp[:400])
print("See commented example above. Also creatable in the UI: AI Gateway -> Create MCP Service.")

# COMMAND ----------

# MAGIC %md
# MAGIC **Step 3 — Grant access** (same RBAC chain as models):
# MAGIC ```sql
# MAGIC GRANT EXECUTE ON MCP SERVICE sv_unity_gw.ai_services.demo_mcp TO `data-scientists`;
# MAGIC ```
# MAGIC Tool restrictions live on the **service**, not the client — a client cannot call an excluded tool.

# COMMAND ----------

# MAGIC %md ## Observe MCP tool calls
# MAGIC MCP traffic is logged in the same usage table, tagged in `mcp_metadata`.
# MAGIC (`tool_name` is populated only on `tools/call`; each session also logs `initialize` + `tools/list`.)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT event_time, requester,
# MAGIC        mcp_metadata.json_rpc_method AS method,
# MAGIC        mcp_metadata.tool_name       AS tool,
# MAGIC        mcp_metadata.server_type     AS server_type,
# MAGIC        status_code
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE mcp_metadata.json_rpc_method = 'tools/call'
# MAGIC   AND event_time >= current_date() - INTERVAL 7 DAYS
# MAGIC ORDER BY event_time DESC LIMIT 50;

# COMMAND ----------

# MAGIC %md ## Federation per user group
# MAGIC Grant different MCP services to different groups, and (for desktop/coding agents) publish a central
# MAGIC **Agent Configuration** naming the allowed MCP servers. Each group gets its own governed tool set —
# MAGIC "MCP federation per user group" — with every tool call attributed to the caller in the usage table.
# MAGIC ```sql
# MAGIC GRANT EXECUTE ON MCP SERVICE sv_unity_gw.ai_services.demo_mcp    TO `platform-eng`;
# MAGIC GRANT EXECUTE ON MCP SERVICE system.ai.github                    TO `developers`;
# MAGIC -- a group only sees the tools on the services it can EXECUTE
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ Same governance model for tools as for models. Next: **`07_coding_agents`** /
# MAGIC **`08_claude_cowork_and_desktop`**.
