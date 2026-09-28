# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Setup & Prerequisites
# MAGIC Creates the demo schemas and verifies the Unity Gateway surface is present.
# MAGIC Run this first. Verified on an Azure workspace (Sep 2026).

# COMMAND ----------

# MAGIC %md ## Config (edit the widgets, or accept defaults)

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")
dbutils.widgets.text("model_service", "demo_llm", "Model service name")
dbutils.widgets.text("fmapi_model", "databricks-claude-sonnet-4-6", "FMAPI model (system.ai.*)")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
SVC = dbutils.widgets.get("model_service")
FMAPI = dbutils.widgets.get("fmapi_model")
FQN = f"{CATALOG}.{SCHEMA}.{SVC}"
print("Model service FQN:", FQN, "| backend:", f"system.ai.{FMAPI}")

# COMMAND ----------

# MAGIC %md ## Host + token from the notebook context (no PAT needed)

# COMMAND ----------

import requests, json
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get()
TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
print("Workspace:", HOST)

# COMMAND ----------

# MAGIC %md ## Create the demo schemas

# COMMAND ----------

for sch in ["ai_services", "ai_policies", "ai_inference"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{sch} COMMENT 'Unity Gateway demo'")
print("Schemas ready under", CATALOG)
display(spark.sql(f"SHOW SCHEMAS IN {CATALOG}"))

# COMMAND ----------

# MAGIC %md ## Verify the Unity Gateway surface
# MAGIC `system.ai_gateway.usage` must exist. Every governed call lands here (~5-30 min lag).

# COMMAND ----------

display(spark.sql("SELECT count(*) AS gw_usage_rows FROM system.ai_gateway.usage"))
display(spark.sql("SHOW TABLES IN system.ai_gateway"))

# COMMAND ----------

# MAGIC %md ## List available FMAPI chat models (routing targets)

# COMMAND ----------

r = requests.get(f"{HOST}/api/2.0/serving-endpoints", headers=H)
eps = r.json().get("endpoints", [])
chat_models = sorted(e["name"] for e in eps if "chat" in str(e.get("task", "")))
print("Chat FMAPIs available:")
for m in chat_models:
    print("  ", m)

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ Setup complete. Next: **`01_model_service_and_invoke`**.
