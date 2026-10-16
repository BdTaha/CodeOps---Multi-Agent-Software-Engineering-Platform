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

OpenAI-compatible services can choose `max_tokens` or `max_completion_tokens`
and omit temperature for models that reject it. Prompt-based JSON instructions
are the default. Compatible OpenAI/NVIDIA models can explicitly opt into
`json_object` or `json_schema`; unsupported parameters fail visibly rather than
silently changing the request. Anthropic and Gemini currently use JSON prompt
instructions and the existing local result validation.

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

Fallback remains limited to connection, timeout, rate-limit, and availability/
not-configured failures. A semantically invalid response such as
`INVALID_DEVELOPMENT` does not trigger another provider. Test & load models checks
the catalog, not the latency or correctness of a generated implementation.

Protocol references: [OpenAI chat completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create),
[Gemini generateContent](https://ai.google.dev/api/generate-content).
