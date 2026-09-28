# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Governed FM API — Model Service + Invoke
# MAGIC **Proof point 1:** create a governed model service and call it through the gateway → **HTTP 200**,
# MAGIC with tokens tracked. This is the CHOICE + observability foundation.

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")
dbutils.widgets.text("model_service", "demo_llm", "Model service name")
dbutils.widgets.text("fmapi_model", "databricks-claude-sonnet-4-6", "FMAPI model (system.ai.*)")

import requests, json
CATALOG = dbutils.widgets.get("catalog"); SCHEMA = dbutils.widgets.get("schema")
SVC = dbutils.widgets.get("model_service"); FMAPI = dbutils.widgets.get("fmapi_model")
FQN = f"{CATALOG}.{SCHEMA}.{SVC}"
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# COMMAND ----------

# MAGIC %md ## Create the governed model service
# MAGIC A model service is a **Unity Catalog securable** that routes to a foundation model.
# MAGIC Created via REST (no SQL DDL for model services). Idempotent-ish: re-running errors if it exists.

# COMMAND ----------

def create_model_service(fqn, fmapi_model):
    cat, sch, svc = fqn.split(".")
    body = {"config": {"routing": {"destinations": [{
        "destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL",
        "name": "primary", "traffic_percentage": 100,
        "pay_per_token_config": {"model": f"models/system.ai.{fmapi_model}"}}]}}}
    r = requests.post(f"{HOST}/api/2.1/unity-catalog/model-services",
                      headers=H, params={"parent": f"schemas/{cat}.{sch}", "model_service_id": svc},
                      json=body)
    return r.status_code, r.json()

code, resp = create_model_service(FQN, FMAPI)
if code == 200:
    print("Created", resp["name"], "| supported:", resp.get("supported_api_types"))
else:
    print(f"[{code}] (already exists is fine):", json.dumps(resp)[:300])

# COMMAND ----------

# MAGIC %md ## Invoke it through the gateway
# MAGIC Route: `POST /ai-gateway/mlflow/v1/chat/completions`, with the **model-service FQN** in `model`.

# COMMAND ----------

def chat(fqn, content, max_tokens=128):
    r = requests.post(f"{HOST}/ai-gateway/mlflow/v1/chat/completions", headers=H,
                      json={"model": fqn, "messages": [{"role": "user", "content": content}],
                            "max_tokens": max_tokens})
    return r.status_code, r.json()

code, out = chat(FQN, "In one sentence, what is Unity Gateway?")
print("HTTP", code)
print(json.dumps(out, indent=2)[:900])

# COMMAND ----------

# MAGIC %md
# MAGIC Note the response `usage` block (prompt / completion / total tokens) — that is what Unity Gateway
# MAGIC records per call in `system.ai_gateway.usage`. Every call is **attributed to your identity**.

# COMMAND ----------

if code == 200:
    u = out.get("usage", {})
    print("routed_to:", out.get("model"))
    print("tokens  in:", u.get("prompt_tokens"), " out:", u.get("completion_tokens"), " total:", u.get("total_tokens"))

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ Governed FM API call works. Next: **`02_rate_limits_429`** to enforce a budget.
