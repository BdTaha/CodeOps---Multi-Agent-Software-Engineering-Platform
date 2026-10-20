# User-configurable models

Open **Settings · Models → Add provider**. Select a preset, enter the API key
for a hosted service, and save the connection. Use **Test & load models** to
load available model IDs, or enter an exact model ID manually. Select the
primary connection and model, optionally select one fallback, and click
**Apply routing**. No API or worker restart is needed for settings edits.

Supported protocols:

| Preset / protocol | Requests | Catalog |
| --- | --- | --- |
| NVIDIA NIM | Chat completions, including bounded pending-result polling | `/models` |
| Local Ollama | Native `/api/chat`, local models only | `/api/tags` |
| OpenAI / OpenAI-compatible | `/chat/completions` | `/models` |
| Anthropic | `/messages` | `/models` |
| Google Gemini | `/models/{id}:generateContent` | `/models` |

Custom endpoints can use OpenAI-compatible chat, Anthropic Messages, or Gemini
protocols. They must accept the documented request/response envelope for that
protocol. This is not arbitrary support for unrelated APIs, image-only models,
or tool-only responses. Select a text model capable of following JSON schemas.
Catalog endpoints may be unavailable or paginated; manual model entry is always
available. A catalog test confirms catalog access, not generation compatibility
or model quality, and does not generate text or download Ollama models.

After selecting a connection and exact model ID, **Test selected model** optionally
sends one tiny JSON generation request to that model. It uses a fixed prompt with
no repository content, a 32-token output cap, and a 25-second request timeout.
It never tests the whole catalog, falls back to another model, or changes routing.
Catalog connectivity and selected-model generation results are shown separately.
Timeout/rejection/invalid responses are reported without exposing provider output,
prompts, reasoning text, or credentials. A passing tiny check does not establish
that a larger planning/development request will succeed. The test uses the saved
connection revision; refresh if another tab changed it.

OpenAI-compatible services can choose `max_tokens` or `max_completion_tokens`
and omit temperature for models that reject it. Prompt-based JSON instructions
are the default. Compatible OpenAI/NVIDIA models can explicitly opt into
`json_object` or `json_schema`; unsupported parameters fail visibly rather than
silently changing the request. Anthropic and Gemini currently use JSON prompt
instructions and the existing local result validation.

## NVIDIA reasoning compatibility

NVIDIA connection forms expose **Reasoning**: Provider default, Disabled, Enabled,
Low, Medium, and High. Reasoning can help complex tasks but materially
increase latency. Support is model-specific; this setting is not sent to other
protocols and does not belong to individual engineering tasks.

| Exact NVIDIA model ID | Provider default in CodeOps | Explicit supported controls |
| --- | --- | --- |
| `poolside/laguna-xs-2.1` | Structured requests send `chat_template_kwargs: {"enable_thinking": false}` | Disabled → false; Enabled → true in `chat_template_kwargs.enable_thinking`. Effort levels are rejected. |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | Structured requests send `chat_template_kwargs: {"enable_thinking": false}` | Disabled → false; Enabled → true. This CodeOps profile deliberately exposes only the boolean thinking control and rejects Low / Medium / High; it never sends `reasoning_effort`. |
| `moonshotai/kimi-k3` | Preserves legacy `reasoning_effort: "low"` | Low / High. NVIDIA's documented K3 values are low/high/max, so Medium and Disabled/Enabled are rejected rather than invented or remapped. Max is not exposed by this UI. |
| `openai/gpt-oss-20b`, `openai/gpt-oss-120b` | No override sent | Low / Medium / High → `reasoning_effort` with that value. |
| Other NVIDIA models | No override sent | Provider default until an exact documented profile is added. |

These are exact compatibility profiles, not substring matching. No request sends
both effort and chat-template controls. Unsupported route/model-policy combinations
are rejected with an explanation when applying a route, editing an active
connection, or testing/generating. An unselected connection can save a policy;
its validity is checked once a model is selected.

The stored default remains `provider_default`. It inherits the three compatibility
exceptions above; otherwise it leaves provider reasoning unchanged. Older JSON
connection rows without this field remain readable without a database reset,
credential rewrite, or schema migration. Encryption/DPAPI behavior is unchanged.
Environment routing supports `ASE_NVIDIA_REASONING_POLICY=provider_default` (or
another validated policy); a saved connection has its own policy.

Routing and active status expose Laguna's effective **Disabled · CodeOps Laguna
compatibility default** and Kimi's legacy Low behavior. Invocation metadata records
only the effective policy label, alongside existing outcome, latency, provider,
fallback, and usage information. No reasoning content is retained in those records.

For the exact Nemotron 3.5 Super ID above, routing and active status show
**Disabled · CodeOps Nemotron compatibility default**. NVIDIA documents optional
thinking through `chat_template_kwargs.enable_thinking`. CodeOps uses false for
bounded structured agent operations; operators can explicitly choose Enabled to
send true. This is a deliberately limited compatibility profile, not a claim that
NVIDIA's API has no additional controls. Final assistant content and `finish_reason`
validation, the 32-token/25-second probe, and availability-only fallback are unchanged.
Reasoning text is not used as final JSON or included in invocation records.

The operator's earlier Nemotron probe used provider_default and returned an invalid
or incomplete result in approximately 781 ms. This change does not establish why
that request failed or guarantee that all engineering requests will succeed.
Nemotron references checked October 20, 2026:
[NVIDIA boolean-control example](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b),
[NVIDIA model card](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b/modelcard).

The live observation reported by the operator was a tiny Playground JSON request
finishing in about 7.8 seconds with Laguna reasoning off, versus repeated CodeOps
structured planning requests timing out at the explicit 600-second setting without
a thinking override. These inputs and execution conditions differ: this identifies
a compatibility/latency concern, not proof that thinking alone caused every delay.
Deterministic tests verify the control payload and bounds, not hosted latency.

References checked October 16, 2026:
[Poolside optional thinking and disabling reasoning](https://huggingface.co/poolside/Laguna-XS-2.1#disabling-reasoning),
[NVIDIA Laguna model card](https://build.nvidia.com/poolside/laguna-xs-2.1/modelcard),
[NVIDIA Kimi effort values](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer),
[NVIDIA GPT-OSS 20B effort API](https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-20b-infer),
[NVIDIA GPT-OSS 120B model](https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-120b).

## Persistence and precedence

Connections and one global route are stored in the platform database in additive
`model_connections` and `model_route_settings` tables. Saved routing overrides
environment routing. **Use environment settings** resets the override and keeps
connections for future use. Existing Ollama-only environments continue to work
before a route is saved. `ASE_MODEL_SETTINGS_LOCKED=true` disables changes and
forces environment routing for administrator-managed deployments.

The API and engineering worker use the same database. A new model operation
reads a consistent snapshot of its route and selected connections. Changing
settings does not modify an in-flight operation. All five model-backed operations
share this route. There is one sequential fallback, only for availability,
connection, timeout, or rate-limit failures; authentication, truncation, malformed
results, semantic validation, and rejected reviews do not switch providers.
Trace records retain the selected connection's display name and protocol.

Updates use revision checks to reject stale settings edits. Active connections
cannot be deleted until routing no longer references them.

## Credentials and endpoints

API keys are encrypted using Fernet before database storage. Responses return
only `has_key`; neither keys nor encrypted values are returned. A blank edit
keeps the existing key; **Remove saved key** clears it. Credential forms do not
use browser local storage. Validation errors exclude submitted inputs. Keys are
sent only through protocol authentication headers, never URL query strings.

Without `ASE_MODEL_SETTINGS_ENCRYPTION_KEY`, a master key is generated under
the ignored `.workspaces/model-credentials` directory (or configured workspace
root). On Windows it is protected by DPAPI for the current account. On other
systems the key file is mode 0600. API and worker must share the same workspace
root, database URL, account, and encryption key. Back up the database and key
material together. Moving to another Windows account requires re-entering
provider credentials or using a shared deployment Fernet key. Keep a deployment
key in a secret manager/environment; never commit it. Changing it without
re-encrypting stored credentials requires re-entering provider keys.

Public API endpoints require HTTPS. Local services can use loopback HTTP.
Embedded credentials, URL queries/fragments, private-network destinations and
metadata services are rejected. DNS addresses are checked and pinned when
connecting, with TLS verification against the original hostname. Redirects
and environment proxies are disabled, requests/responses remain bounded, and
provider response bodies are never exposed in transport errors.

Mutation and catalog requests must originate from the local workspace. This
inherits CodeOps' trusted local deployment model, not multi-user authentication.
Preview containers receive neither saved credentials nor the encryption key.

## Request timeout and fallback latency

`ASE_PLANNER_TIMEOUT_SECONDS` sets the structured model request timeout, including
planning and development calls. Its default is 180 seconds; an explicit environment
or `.env` value takes precedence (up to 600 seconds). A primary call may wait for
that configured timeout before an eligible fallback starts, so a configured value
of 600 can explain a roughly ten-minute delay. The fallback request can add its
own latency. Model routing in the UI does not override this timeout; update the
operator configuration and restart the affected services if you intend to change it.
Models status shows the effective primary timeout beside routing. The optional
generation test has its own 25-second bound and never waits for that 600-second
operator timeout. Neither UI operation overwrites your explicit environment value.

Fallback remains limited to connection, timeout, rate-limit, and availability/
not-configured failures. A semantically invalid response such as
`INVALID_DEVELOPMENT` does not trigger another provider. Test & load models checks
the catalog, not the latency or correctness of a generated implementation.

Protocol references: [OpenAI chat completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create),
[Gemini generateContent](https://ai.google.dev/api/generate-content).
