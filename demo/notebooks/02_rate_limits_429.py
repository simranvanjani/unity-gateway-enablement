# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Rate Limits — enforce a budget (→ HTTP 429)
# MAGIC **Proof point 2 (COST):** set a per-user requests-per-minute limit, then exceed it and watch the
# MAGIC gateway return **HTTP 429 `REQUEST_LIMIT_EXCEEDED`** — no code change on the client.

# COMMAND ----------

dbutils.widgets.text("catalog", "sv_unity_gw", "Catalog")
dbutils.widgets.text("schema", "ai_services", "Schema for services")
dbutils.widgets.text("model_service", "demo_llm", "Model service name")
dbutils.widgets.text("rpm", "2", "Requests per minute (low, to force 429)")

import requests, json, time
CATALOG = dbutils.widgets.get("catalog"); SCHEMA = dbutils.widgets.get("schema")
SVC = dbutils.widgets.get("model_service"); RPM = int(dbutils.widgets.get("rpm"))
FQN = f"{CATALOG}.{SCHEMA}.{SVC}"
NAME = f"model-services/{FQN}"
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
HOST = ctx.apiUrl().get(); TOKEN = ctx.apiToken().get()
ME = ctx.userName().get() if hasattr(ctx, "userName") else spark.sql("SELECT current_user()").first()[0]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
print("Limiting", FQN, "to", RPM, "req/min for", ME)

# COMMAND ----------

# MAGIC %md ## Set a per-user rate limit
# MAGIC `rate_limits` is a list; per-user items need a `principal`. Proto-style enums (verified).

# COMMAND ----------

def set_rate_limit(name, principal, rpm):
    body = {"config": {"rate_limits": [{
        "key": "RATE_LIMIT_KEY_USER",
        "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE",
        "principal": principal, "requests": rpm}]}}
    r = requests.patch(f"{HOST}/api/2.1/unity-catalog/{name}",
                       headers=H, params={"update_mask": "config.rate_limits"}, json=body)
    return r.status_code, r.json()

code, resp = set_rate_limit(NAME, ME, RPM)
print("HTTP", code, "| rate_limits:", json.dumps(resp.get("config", {}).get("rate_limits")))

# COMMAND ----------

# MAGIC %md ## Exceed the limit — fire N+2 rapid calls

# COMMAND ----------

def chat(fqn, content, max_tokens=8):
    r = requests.post(f"{HOST}/ai-gateway/mlflow/v1/chat/completions", headers=H,
                      json={"model": fqn, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens})
    return r.status_code, r.text

for i in range(1, RPM + 3):
    code, body = chat(FQN, f"ping {i}")
    tag = "✅ OK" if code == 200 else ("⛔ RATE LIMITED" if code == 429 else "?")
    print(f"call {i:>2} -> HTTP {code}  {tag}")
    if code == 429:
        print("     ", body[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC The gateway enforced the budget **centrally** — the client did nothing special. Now reset the limit
# MAGIC so later notebooks aren't throttled.

# COMMAND ----------

r = requests.patch(f"{HOST}/api/2.1/unity-catalog/{NAME}",
                   headers=H, params={"update_mask": "config.rate_limits"},
                   json={"config": {"rate_limits": []}})
print("Reset:", r.status_code, "| rate_limits:", r.json().get("config", {}).get("rate_limits"))

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ Rate limiting enforced (429). Also configurable: service-wide limits and token-per-minute (TPM).
# MAGIC Next: **`03_guardrails_beta`** (content policy) or **`05_observability`** (see the calls logged).
