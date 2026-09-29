# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Traffic routing, fallback & budgets (reliability + COST)
# MAGIC Rounds out the GA capability set: a single governed endpoint can **split traffic** across models,
# MAGIC **fall back** automatically, and enforce a **token budget** — all with no client change.

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")
import requests, json
CATALOG = dbutils.widgets.get("catalog"); SCHEMA = dbutils.widgets.get("schema")
HA_FQN = f"{CATALOG}.{SCHEMA}.demo_llm_ha"
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
ME = spark.sql("SELECT current_user()").first()[0]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def chat(fqn, content, max_tokens=16):
    r = requests.post(f"{HOST}/ai-gateway/mlflow/v1/chat/completions", headers=H,
                      json={"model": fqn, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens})
    return r.status_code, r.json()

# COMMAND ----------

# MAGIC %md ## Traffic splitting — one endpoint, multiple backends
# MAGIC Create a service that routes **70% Sonnet / 30% Haiku** with a **Haiku fallback** (on 429/5xx).
# MAGIC Callers hit one FQN; the gateway picks the destination and records the choice in `routing_information`.

# COMMAND ----------

def create_split_service(fqn):
    cat, sch, svc = fqn.split(".")
    body = {"config": {"routing": {
        "destinations": [
            {"destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL", "name": "sonnet",
             "traffic_percentage": 70, "pay_per_token_config": {"model": "models/system.ai.databricks-claude-sonnet-4-6"}},
            {"destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL", "name": "haiku",
             "traffic_percentage": 30, "pay_per_token_config": {"model": "models/system.ai.databricks-claude-haiku-4-5"}}],
        "fallback": {"destinations": [
            {"destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL", "name": "fb_haiku",
             "pay_per_token_config": {"model": "models/system.ai.databricks-claude-haiku-4-5"}}]}}}}
    r = requests.post(f"{HOST}/api/2.1/unity-catalog/model-services",
                      headers=H, params={"parent": f"schemas/{cat}.{sch}", "model_service_id": svc}, json=body)
    return r.status_code, r.json()

code, resp = create_split_service(HA_FQN)
print(f"[{code}] (exists is fine):", resp.get("name") or json.dumps(resp)[:200])

# COMMAND ----------

# MAGIC %md ## Fire several calls — see which backend served each

# COMMAND ----------

from collections import Counter
seen = Counter()
for i in range(8):
    code, out = chat(HA_FQN, f"Say hi ({i})")
    if code == 200:
        seen[out.get("model")] += 1
print("HTTP 200 x", sum(seen.values()))
print("backends hit:", dict(seen), "(≈70/30 split over enough calls)")

# COMMAND ----------

# MAGIC %md
# MAGIC After the usage lag, `routing_information.attempts[]` shows the destination + any fallback per call
# MAGIC (see notebook 05, Query 5). Fallback fires automatically on a destination 429/5xx.

# COMMAND ----------

# MAGIC %md ## Budgets — token cap per user (alert or hard-block)
# MAGIC A rate-limit item takes **`requests`** (RPM) and/or **`tokens`** (token budget) per renewal period.
# MAGIC Set a small token budget and watch it bite.

# COMMAND ----------

NAME = f"model-services/{HA_FQN}"
def set_budget(name, principal, tokens=None, requests_per_min=None):
    item = {"key": "RATE_LIMIT_KEY_USER", "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE", "principal": principal}
    if tokens is not None: item["tokens"] = tokens
    if requests_per_min is not None: item["requests"] = requests_per_min
    r = requests.patch(f"{HOST}/api/2.1/unity-catalog/{name}", headers=H,
                       params={"update_mask": "config.rate_limits"}, json={"config": {"rate_limits": [item]}})
    return r.status_code, r.json()

code, resp = set_budget(NAME, ME, tokens=200)   # tiny token budget for the demo
print("set budget HTTP", code, "| rate_limits:", json.dumps(resp.get("config", {}).get("rate_limits")))
for i in range(6):
    code, out = chat(HA_FQN, "Write a two-sentence haiku about governance.", max_tokens=80)
    print(f"call {i+1} -> HTTP {code}", "OK" if code == 200 else "⛔ budget exceeded")

# COMMAND ----------

# MAGIC %md ## Reset the budget

# COMMAND ----------

r = requests.patch(f"{HOST}/api/2.1/unity-catalog/{NAME}", headers=H,
                   params={"update_mask": "config.rate_limits"}, json={"config": {"rate_limits": []}})
print("reset:", r.status_code)

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ One endpoint = model choice + reliability (split/fallback) + budget — governed centrally.
