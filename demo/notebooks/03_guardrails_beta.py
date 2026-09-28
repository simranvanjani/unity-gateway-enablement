# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Guardrails — Service Policies (BETA)  →  policy block
# MAGIC **Proof point 3a (CONTROL):** attach a content policy so the gateway blocks PII / competitor
# MAGIC mentions **before** the model is called (fail-closed).
# MAGIC
# MAGIC > ⚠️ **Beta.** Service policies (ALLOW / ASK / DENY) must be enabled in the **account console →
# MAGIC > Previews**. The attach path is not exposed in the `ai-gateway` update mask on all workspaces —
# MAGIC > if the REST attach below 404s, attach via the UI: **AI Gateway → your service → Governance →
# MAGIC > add service policy**. Confirm exact fields against your enabled version. Built for you to run live.

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")
dbutils.widgets.text("policy_schema", "ai_policies", "Schema for policy UDFs")
dbutils.widgets.text("model_service", "demo_llm", "Model service name")

import requests, json
CATALOG = dbutils.widgets.get("catalog"); SCHEMA = dbutils.widgets.get("schema")
PSCHEMA = dbutils.widgets.get("policy_schema"); SVC = dbutils.widgets.get("model_service")
FQN = f"{CATALOG}.{SCHEMA}.{SVC}"; NAME = f"model-services/{FQN}"
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def chat(fqn, content, max_tokens=64):
    r = requests.post(f"{HOST}/ai-gateway/mlflow/v1/chat/completions", headers=H,
                      json={"model": fqn, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens})
    return r.status_code, r.text

# COMMAND ----------

# MAGIC %md ## Option A — Built-in guardrail (PII)
# MAGIC Databricks ships built-in policies: `block_pii`, `block_jailbreak`, `block_unsafe_content`,
# MAGIC `block_hallucination`. Attach `block_pii` ON CALL + ON RESULT.

# COMMAND ----------

def attach_service_policy(name, policy):
    # Best-known REST attach (confirm on your Beta-enabled workspace; else use the UI).
    body = {"config": {"service_policies": [policy]}}
    r = requests.patch(f"{HOST}/api/2.1/unity-catalog/{name}",
                       headers=H, params={"update_mask": "config.service_policies"}, json=body)
    return r.status_code, r.text

code, resp = attach_service_policy(NAME, {
    "name": "pii_guard",
    "policy_type": "POLICY_TYPE_BUILTIN",
    "handler": "functions/system.ai.block_pii",
    "options": {"phases": "pre_call,post_call"}})
print("attach HTTP", code)
print(resp[:400])

# COMMAND ----------

# MAGIC %md ## Test it — a request containing PII should be blocked (policy error, not the LLM)

# COMMAND ----------

code, body = chat(FQN, "My SSN is 123-45-6789, summarize my account.")
print("HTTP", code, "(expect a policy block / 400 when the guard is active)")
print(body[:300])

# COMMAND ----------

# MAGIC %md ## Option B — Custom guardrail (block competitor mentions)
# MAGIC A UC SQL/Python UDF returning `{"result":"ALLOW"|"DENY"|"ASK", ...}`. The gateway reads `result`.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{PSCHEMA}.block_competitors(event STRING)
RETURNS STRING
LANGUAGE PYTHON
AS $$
import json
content = str(event).lower()
if any(c in content for c in ["snowflake", "redshift", "bigquery"]):
    return json.dumps({{"result": "DENY", "message": "Competitor references not allowed."}})
return json.dumps({{"result": "ALLOW"}})
$$
""")
print("Custom policy UDF created:", f"{CATALOG}.{PSCHEMA}.block_competitors")

# COMMAND ----------

code, resp = attach_service_policy(NAME, {
    "name": "competitor_guard",
    "policy_type": "POLICY_TYPE_CUSTOM",
    "handler": f"functions/{CATALOG}.{PSCHEMA}.block_competitors",
    "options": {"phases": "pre_call"}})
print("attach HTTP", code, resp[:300])
code, body = chat(FQN, "What is Snowflake's advantage over Databricks?")
print("HTTP", code, "(expect DENY)"); print(body[:300])

# COMMAND ----------

# MAGIC %md
# MAGIC **Key points for the room:** policies are ranked (first DENY wins), evaluated ON CALL and/or
# MAGIC ON RESULT, and **fail-closed** (a UDF error → DENY). Payload *mutation* is not supported (block/pass
# MAGIC only). This is **Beta** — position it as such. Next: **`04_access_control_403`**.
