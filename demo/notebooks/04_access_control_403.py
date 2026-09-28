# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Access Control — UC RBAC (→ HTTP 403)
# MAGIC **Proof point 3b (CONTROL):** who can call a model/MCP service is standard **Unity Catalog RBAC**.
# MAGIC
# MAGIC > This notebook **explains** the mechanism and shows the SQL + the 403 shape. It does **not** run a
# MAGIC > live denial (that needs a second identity without access; revoking your own owner grant would lock
# MAGIC > you out). To demo live, grant EXECUTE to a test group/service principal, then call as that identity.

# COMMAND ----------

# MAGIC %md ## The privilege chain — a caller needs ALL THREE
# MAGIC A model service is a UC securable. Access = the standard three-part chain:

# COMMAND ----------

# MAGIC %md
# MAGIC ```sql
# MAGIC GRANT USE CATALOG ON CATALOG sv_unity_gw                              TO `ds-team`;
# MAGIC GRANT USE SCHEMA  ON SCHEMA  sv_unity_gw.ai_services                  TO `ds-team`;
# MAGIC GRANT EXECUTE     ON MODEL SERVICE sv_unity_gw.ai_services.demo_llm   TO `ds-team`;
# MAGIC ```
# MAGIC Same pattern for MCP services: `GRANT EXECUTE ON MCP SERVICE ...`.

# COMMAND ----------

# MAGIC %md ## What a denied caller sees
# MAGIC If any link is missing, the gateway rejects the call **before** any model runs:
# MAGIC ```
# MAGIC HTTP 403: "Caller does not have EXECUTE privilege on MODEL SERVICE
# MAGIC            sv_unity_gw.ai_services.demo_llm"
# MAGIC ```
# MAGIC Deny-by-**absence** is the model: end users get nothing on `system.ai` unless granted. Prefer
# MAGIC scoping a dedicated catalog/schema to a group over relying on REVOKE.

# COMMAND ----------

# MAGIC %md ## Inspect current grants on the demo service

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW GRANTS ON MODEL SERVICE sv_unity_gw.ai_services.demo_llm;

# COMMAND ----------

# MAGIC %md ## To demo the 403 live (optional, needs a 2nd identity)
# MAGIC 1. Create/choose a service principal or group **without** EXECUTE on the service.
# MAGIC 2. Get a token for it (SP OAuth) and call `/ai-gateway/mlflow/v1/chat/completions` with the service FQN.
# MAGIC 3. Observe **HTTP 403**. Then `GRANT EXECUTE`, retry → **200**. Then `REVOKE` → 403 again.
# MAGIC
# MAGIC Every grant/revoke is captured in UC audit logs. Next: **`05_observability`** or **`06_mcp_services`**.
