# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Observability — every call, logged
# MAGIC One table, `system.ai_gateway.usage`, captures **every** gateway call: tokens, latency, requester,
# MAGIC model, routing, and MCP metadata. Only gateway-routed calls appear; ~5-30 min lag.
# MAGIC Run these against the demo SQL warehouse.

# COMMAND ----------

# MAGIC %md ## Your recent calls (from notebooks 01/02)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT event_time, requester, endpoint_name, destination_model,
# MAGIC        input_tokens, output_tokens, total_tokens, latency_ms, status_code
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE requester = current_user()
# MAGIC   AND event_time >= current_timestamp() - INTERVAL 2 HOURS
# MAGIC ORDER BY event_time DESC
# MAGIC LIMIT 50;

# COMMAND ----------

# MAGIC %md ## Query 1 — Traffic overview by model (last 7 days): calls, tokens, errors, latency

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT date_trunc('hour', event_time)                    AS hour,
# MAGIC        coalesce(endpoint_name, '(MCP/direct)')           AS endpoint,
# MAGIC        destination_model,
# MAGIC        count(*)                                          AS total_calls,
# MAGIC        count_if(status_code = 200)                       AS ok_calls,
# MAGIC        count_if(status_code >= 400)                      AS error_calls,
# MAGIC        round(100.0 * count_if(status_code >= 400)/count(*), 1) AS error_pct,
# MAGIC        sum(coalesce(input_tokens,0))                     AS in_tokens,
# MAGIC        sum(coalesce(output_tokens,0))                    AS out_tokens,
# MAGIC        round(avg(latency_ms))                            AS avg_ms,
# MAGIC        round(percentile_approx(latency_ms, 0.95))        AS p95_ms
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE event_time >= current_date() - INTERVAL 7 DAYS
# MAGIC GROUP BY 1,2,3 ORDER BY hour DESC, total_calls DESC LIMIT 100;

# COMMAND ----------

# MAGIC %md ## Query 2 — Per-user / per-service-principal usage today (cost attribution)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT coalesce(requester,'(anonymous)') AS requester, requester_type,
# MAGIC        count(*) AS calls,
# MAGIC        sum(coalesce(input_tokens,0)) AS in_tokens,
# MAGIC        sum(coalesce(output_tokens,0)) AS out_tokens,
# MAGIC        round(avg(latency_ms)) AS avg_ms,
# MAGIC        count_if(status_code >= 400) AS errors
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE event_time >= current_date()
# MAGIC GROUP BY 1,2 ORDER BY calls DESC LIMIT 100;

# COMMAND ----------

# MAGIC %md ## Query 3 — MCP method + tool frequency (for notebook 06)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT mcp_metadata.json_rpc_method AS method,
# MAGIC        mcp_metadata.tool_name       AS tool,
# MAGIC        mcp_metadata.server_type     AS server_type,
# MAGIC        count(*) AS calls,
# MAGIC        count_if(status_code = 200)  AS success,
# MAGIC        count_if(status_code >= 400) AS errors
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE mcp_metadata.json_rpc_method IS NOT NULL
# MAGIC   AND event_time >= current_date() - INTERVAL 7 DAYS
# MAGIC GROUP BY 1,2,3 ORDER BY calls DESC LIMIT 100;

# COMMAND ----------

# MAGIC %md ## Query 4 — Prompt-cache efficiency (Claude cache-read %)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT destination_model,
# MAGIC        sum(input_tokens) AS in_tokens,
# MAGIC        sum(coalesce(token_details.cache_read_input_tokens,0)) AS cache_read,
# MAGIC        round(100.0 * sum(coalesce(token_details.cache_read_input_tokens,0))
# MAGIC              / nullif(sum(input_tokens),0), 1) AS cache_hit_pct
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE event_time >= current_date() - INTERVAL 7 DAYS AND destination_model IS NOT NULL
# MAGIC GROUP BY 1 ORDER BY in_tokens DESC LIMIT 50;

# COMMAND ----------

# MAGIC %md ## External-provider spend (daily)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM system.ai_gateway.external_model_spend
# MAGIC ORDER BY 1 DESC LIMIT 50;

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ One governed control point = one place to see spend, usage, errors, and per-user attribution.
