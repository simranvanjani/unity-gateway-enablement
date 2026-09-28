# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Coding Agents — govern Claude Code / Cursor / Codex via `ug`
# MAGIC The **coding-agents track**: route developers' AI coding tools through Unity Gateway so every
# MAGIC LLM + MCP call is governed, attributed per developer, and cost-tracked — with **one** Databricks login.
# MAGIC
# MAGIC > The `ug` CLI runs on the **developer's laptop**, not in this notebook. Run the shell blocks in a
# MAGIC > local terminal. This notebook is the reference + the per-developer cost query.

# COMMAND ----------

# MAGIC %md ## 1. Install the `ug` CLI (laptop)
# MAGIC ```bash
# MAGIC uv tool install git+https://github.com/databricks/unity-gateway
# MAGIC ug --version
# MAGIC ```
# MAGIC If `cryptography` fails to build on a corporate network:
# MAGIC ```bash
# MAGIC uv venv ~/.local/share/ug-env --python python3.12
# MAGIC uv pip install --python ~/.local/share/ug-env/bin/python --only-binary cryptography \
# MAGIC   git+https://github.com/databricks/unity-gateway
# MAGIC ln -sf ~/.local/share/ug-env/bin/ug ~/.local/bin/ug
# MAGIC ```

# COMMAND ----------

# MAGIC %md ## 2. Point `ug` at the workspace + configure an agent
# MAGIC ```bash
# MAGIC ug configure --workspace https://adb-7405607317163570.10.azuredatabricks.net
# MAGIC ug configure --agents codex        # or: claude-code | cursor | copilot | gemini
# MAGIC ```
# MAGIC This writes the Databricks model-provider config into the agent's own config file
# MAGIC (e.g. `~/.codex/config.toml`). Launch the agent; it routes through Unity Gateway — look for the
# MAGIC **"Databricks AI Gateway"** indicator. One Databricks auth covers both LLM and MCP tool calls.

# COMMAND ----------

# MAGIC %md ## 3. Publish a central agent configuration (admin, once)
# MAGIC **AI Gateway → Governance → Agent Configuration → Edit.** One JSON governs which models + MCP
# MAGIC servers every developer's agents may use:
# MAGIC ```json
# MAGIC {
# MAGIC   "default_agent": "CODING_AGENT_CODEX",
# MAGIC   "enabled_agents": [{
# MAGIC     "agent": "CODING_AGENT_CODEX",
# MAGIC     "config": {
# MAGIC       "models": {"model_services": ["system.ai.gpt-5-5", "sv_unity_gw.ai_services.demo_llm"]},
# MAGIC       "default_models": {"default_model": "system.ai.gpt-5-5"},
# MAGIC       "tracing": {"enabled": true}
# MAGIC     }
# MAGIC   }],
# MAGIC   "mcp_servers": {"names": ["system.ai.github", "system.ai.microsoft_365"]}
# MAGIC }
# MAGIC ```

# COMMAND ----------

# MAGIC %md ## 4. Per-developer cost & usage (run here, after some agent activity)
# MAGIC Every agent call is attributed to the developer's identity in `system.ai_gateway.usage`.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT requester,
# MAGIC        count(*)                      AS calls,
# MAGIC        sum(coalesce(total_tokens,0)) AS total_tokens,
# MAGIC        collect_set(destination_model) AS models_used
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE (destination_model LIKE '%gpt%' OR user_agent ILIKE '%codex%' OR user_agent ILIKE '%cursor%'
# MAGIC        OR user_agent ILIKE '%claude%')
# MAGIC   AND event_time >= current_date() - INTERVAL 7 DAYS
# MAGIC GROUP BY requester ORDER BY total_tokens DESC LIMIT 50;

# COMMAND ----------

# MAGIC %md
# MAGIC **The pitch:** developers keep their favorite agent; the org gets governed models, governed MCP
# MAGIC tools, per-developer cost, and central policy — enforced at the gateway, not by trust.
# MAGIC Supported agents: Claude Code, Cursor, Codex, GitHub Copilot, Google Gemini.
