# Dojo LLM gateway

Creating `/data/litellm/` on the main node enables the `litellm` Compose
profile. The directory must contain `config.yaml` and `env`.

For example, `env` can contain:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
LITELLM_MASTER_KEY=sk-...
LITELLM_SALT_KEY=sk-...
LITELLM_USER_KEY_SECRET=...
LITELLM_USER_BUDGET_LIMITS=[{"max_budget":50,"budget_duration":"1h"},{"max_budget":250,"budget_duration":"1d"},{"max_budget":500,"budget_duration":"30d"}]
```

Generate independent random values for the master key, salt key, and user-key
secret and keep them stable. Other provider credentials can be added to the
same file and referenced from `config.yaml` with LiteLLM's
`os.environ/NAME` syntax.

An OpenRouter configuration for `config.yaml` looks like this:

```yaml
model_list:
  - model_name: z-ai/glm-5.3
    litellm_params:
      model: openrouter/z-ai/glm-5.3
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.00000175
      output_cost_per_token: 0.0000055
      cache_read_input_token_cost: 0.000000325
      cache_creation_input_token_cost: 0.00000175
  - model_name: z-ai/glm-5.3-flash
    litellm_params:
      model: openrouter/z-ai/glm-5.3-flash
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.00000009375
      output_cost_per_token: 0.0000003125
      cache_read_input_token_cost: 0.00000001875
      cache_creation_input_token_cost: 0.00000009375
  - model_name: moonshotai/kimi-k3
    litellm_params:
      model: openrouter/moonshotai/kimi-k3
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.00000375
      output_cost_per_token: 0.00001875
      cache_read_input_token_cost: 0.000000375
      cache_creation_input_token_cost: 0.00000375
  - model_name: openai/gpt-5.6-sol
    litellm_params:
      model: openrouter/openai/gpt-5.6-sol
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.0000025
      output_cost_per_token: 0.0000125
      cache_read_input_token_cost: 0.00000025
      cache_creation_input_token_cost: 0.000003125
  - model_name: openai/gpt-5.6-terra
    litellm_params:
      model: openrouter/openai/gpt-5.6-terra
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.0000025
      output_cost_per_token: 0.000015
      cache_read_input_token_cost: 0.00000025
      cache_creation_input_token_cost: 0.000003125
  - model_name: openai/gpt-5.6-luna
    litellm_params:
      model: openrouter/openai/gpt-5.6-luna
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.00000025
      output_cost_per_token: 0.0000015
      cache_read_input_token_cost: 0.000000025
      cache_creation_input_token_cost: 0.0000003125
  - model_name: anthropic/claude-opus-5
    litellm_params:
      model: openrouter/anthropic/claude-opus-5
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.00000625
      output_cost_per_token: 0.00003125
      cache_read_input_token_cost: 0.000000625
      cache_creation_input_token_cost: 0.0000078125
  - model_name: anthropic/claude-sonnet-5
    litellm_params:
      model: openrouter/anthropic/claude-sonnet-5
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      input_cost_per_token: 0.0000025
      output_cost_per_token: 0.0000125
      cache_read_input_token_cost: 0.00000025
      cache_creation_input_token_cost: 0.000003125

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  coordination_redis:
    url: os.environ/REDIS_URL
  global_max_parallel_requests: 100
  fail_closed_budget_enforcement: true

litellm_settings:
  default_key_generate_params:
    max_budget: 500
    models:
      - all-proxy-models
    rpm_limit: 60
    tpm_limit: 200000
    max_parallel_requests: 4
  drop_params: true
  enable_redis_auth_cache: true
  telemetry: false
```

After creating both files, run `dojo up`. Removing the directory disables the
profile on the next `dojo up`.

The image is pinned to `v1.99.1`. The existing PostgreSQL initialization files
create a separate `litellm` database, and Redis database 1 coordinates
authentication, concurrency, rate limits, and budget state.

## Upgrade migration

Existing installations have already initialized `/data/postgres`, so adding
`db/init/01_litellm.sql` does not execute it automatically. Include this manual
migration in the PR notes and run it inside the outer Dojo container before
enabling LiteLLM:

```console
dojo db --dbname postgres --file /docker-entrypoint-initdb.d/01_litellm.sql
```

The command is idempotent and is unnecessary for fresh installations.

LiteLLM response and semantic caching are disabled. Provider prompt caching
remains available when the selected model and provider support it.

The example prices are deliberately 25% above the OpenRouter catalog values
used when this example was written. The pinned LiteLLM image's OpenRouter
Responses adapter does not request or preserve OpenRouter's returned cost, so
leaving a model unpriced can record zero spend on the path used by Codex.
Recheck the prices when changing models, providers, or the LiteLLM image.

## Access and budgets

CTFd provisions credentials automatically when the user's active challenge
belongs to a dojo with the internal `llm` permission. Each learner gets one
stable `user_12345` identity and virtual key. The key can use every model exposed
by the proxy, including models added later, and all spend is aggregated across
those models.

The example's native `litellm_settings.default_key_generate_params` sets a $500
lifetime budget, 60 requests/minute, 200,000 tokens/minute, and four concurrent
requests. CTFd adds the concurrent key-level budget windows from
`LITELLM_USER_BUDGET_LIMITS` when it creates the key. The example applies
$50/hour, $250/day, and $500/30 days at the same time, aggregated across every
exposed model. LiteLLM owns enforcement and spend accounting. The first model
returned by LiteLLM is the clients' initial model.

Changing `default_key_generate_params.max_budget` or
`LITELLM_USER_BUDGET_LIMITS` affects newly created keys. Update existing keys
through LiteLLM's administration API or UI when changing this policy;
restarting the services does not rewrite persisted key limits.

LiteLLM's standard administration API and UI at `/llm/ui/` can inspect, update,
or reset virtual keys; the Dojo does not add a second key-management interface.
Learners can run `dojo llm-usage` in a workspace to see their lifetime spend,
token and prompt-cache usage, request counts, and per-model totals.

## Workspace clients

The workspace Nix profile installs wrapped `codex`, `claude`, and `opencode`
commands. A wrapper preserves an existing client login. Otherwise, it asks the
authenticated CTFd endpoint for managed credentials and configures that process
transparently. If the active dojo lacks the `llm` permission, the unmodified
client runs and offers its normal login flow.

Set `DOJO_LLM_DISABLE=1` to bypass automatic credentials for one invocation.
Authentication-management commands such as `codex login`, `claude auth`, and
`opencode auth` always bypass the wrapper. OpenCode credentials saved by
`opencode auth login` are detected automatically; use `DOJO_LLM_DISABLE=1` for
an environment-only custom provider setup.

The GLM route is best-effort Claude Code compatibility, not an
Anthropic-supported non-Claude configuration. Configure a Claude model when
Claude-specific semantics matter. Add or replace model entries in
`/data/litellm/config.yaml` to move away from OpenRouter or use local backends;
the learner key entitlement and aggregate budgets do not need to change.

Nginx only terminates and forwards `/llm/` traffic. It does not add another
request-rate bucket or response cache. Per-key RPM, TPM, concurrency, budgets,
and the gateway-wide concurrency cap are enforced by LiteLLM.
