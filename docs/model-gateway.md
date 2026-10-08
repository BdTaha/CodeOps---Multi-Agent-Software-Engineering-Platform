# CodeOps model gateway

All five model-backed operations use the same global route: product planning,
coding planning, development, review, and semantic acceptance-evidence mapping.
The existing agents, approvals, workspace boundaries, tests, repair loops,
acceptance gates, previews, and explicit Git delivery remain unchanged.

## Contract and ownership

`domain/models.py` defines `ModelRequest`, `ModelMessage`, `ModelResponse`,
`ModelInvocation`, the `ModelProvider.generate(request)` protocol, and typed
provider errors. Requests contain purpose, messages, model, temperature,
max output tokens, optional context tokens, optional JSON schema, and a caller
timeout (bounded to 600 seconds). Responses contain text, provider, selected
model, latency, optional request ID, and optional reported token usage.
No usage or cost is invented. Missing usage remains null.

`infrastructure/model_gateway.py` selects exactly one primary and at most one
sequential Ollama fallback. Each adapter receives a deep copy of the equivalent
logical request; only the routed model changes. There is no provider racing,
load balancing, purpose-dependent routing, or automatic transport retry.

`infrastructure/structured_model.py` assembles bounded agent context, removes
the original host repository path, supplies the agent schema and instructions,
and delegates to the gateway. The `model_planner`, `model_product`,
`model_developer`, `model_reviewer`, and `model_evidence` modules retain the
existing prompts, schemas, parsing, and agent-specific validation. Old
`ollama*` modules remain import-compatible aliases; they now use the route too.

## NVIDIA NIM configuration

Backend `.env` example; replace the placeholder locally and never commit keys:

```dotenv
ASE_MODEL_PRIMARY_PROVIDER=nvidia
ASE_MODEL_PRIMARY_MODEL=moonshotai/kimi-k3
ASE_NVIDIA_API_KEY=your-key-here
ASE_NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
ASE_NVIDIA_STRUCTURED_MODE=prompt
ASE_MODEL_FALLBACK_ENABLED=true
ASE_MODEL_FALLBACK_PROVIDER=ollama
ASE_OLLAMA_MODEL=qwen2.5-coder:3b
ASE_OLLAMA_BASE_URL=http://127.0.0.1:11434
ASE_PLANNER_TIMEOUT_SECONDS=180
```

Optional `ASE_MODEL_FALLBACK_MODEL` overrides `ASE_OLLAMA_MODEL` for fallback.
Model IDs are configurable, nonblank, bounded to 200 characters, and reject
control characters. They are not constrained to an Ollama-style naming regex.
Ollama generation retains local model-tag/cloud-tag restrictions.

NVIDIA's hosted Kimi K3 reference (checked October 8, 2026) specifies the exact
catalog identifier `moonshotai/kimi-k3`, HTTPS
`POST /v1/chat/completions`, Bearer authentication, text messages,
`max_tokens`, `temperature`, and `reasoning_effort`. CodeOps sends non-streaming
requests and K3 `reasoning_effort=low` to reserve output budget for the result.
It reads final `choices[0].message.content`, requires `finish_reason=stop`, and
ignores reasoning content. It extracts usage and safe opaque request IDs when
reported. Pending 202 responses are polled at `/v1/status/{requestId}` using a
validated UUID and the remaining primary request deadline.

The hosted K3 endpoint reference does **not** document `response_format`.
CodeOps therefore defaults to schema-in-prompt generation with local validation;
it does not claim native constrained decoding for this hosted model. For other
compatible NVIDIA catalog models whose API supports these parameters, explicit
`ASE_NVIDIA_STRUCTURED_MODE=json_object` or `json_schema` sends the corresponding
OpenAI-style response format. A rejected parameter is surfaced as a bad request;
there is no silent mode downgrade or provider switch.

Sources: [NVIDIA Kimi K3 example](https://build.nvidia.com/moonshotai/kimi-k3),
[endpoint reference](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer),
[pending status reference](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-statuspolling).
Self-hosted NIM/Dynamo identifiers and structured-generation capabilities can
differ; arbitrary custom endpoints are intentionally unsupported in this phase.

## Configuration precedence and startup

1. If primary provider or primary model is explicitly set, use that route.
   An omitted provider in an explicit model route means NVIDIA. NVIDIA's omitted
   model defaults to `moonshotai/kimi-k3`; Ollama's to `ASE_OLLAMA_MODEL`.
2. Otherwise, a nonblank NVIDIA key selects NVIDIA/Kimi K3.
3. Otherwise, an existing `ASE_OLLAMA_MODEL` selects Ollama-only compatibility
   mode. No extra cloud configuration is required and no fallback runs.
4. Otherwise, show the intended NVIDIA route as not configured. Startup still
   works. Model work reports no provider configured unless a configured local
   fallback is available.

Explicit NVIDIA without a key may fall back to a configured Ollama model when
fallback is enabled; it records `not_configured`. An invalid/nonworking key is
an authentication failure and **never** concealed with fallback.
Fallback is disabled when Ollama is primary; only Ollama is supported as the
fallback provider. Routing is environment-only, with no database preferences.
Restart the API and engineering worker after changing it; the preview worker
does not invoke models. Existing product data needs no schema migration.

## Fallback and validation matrix

| Primary outcome | Fallback |
| --- | --- |
| Connection/DNS/HTTP connection failure | Yes, if enabled and local model configured |
| Provider timeout | Yes |
| HTTP 429 | Yes (`rate_limited`) |
| HTTP 500, 502, 503, 504 | Yes (`unavailable`) |
| Missing NVIDIA key | Yes (`not_configured`), visibly recorded |
| HTTP 401/403 or malformed key | No: authentication/configuration error |
| Other HTTP errors, including 400/422, redirects, model/parameter errors | No |
| Malformed envelope, incomplete/truncated response | No |
| Invalid JSON/Pydantic output or agent semantic validation | No |
| Dependency cycle, invalid edit, rejected review, invalid evidence association | No |

There is exactly one fallback attempt. If it also fails, the error reports both
provider failures, without their raw bodies. Transport attempts and agent
semantic retries remain separate. Product planning retains its two attempts
with validation feedback; reviewer evidence rechecks retain their own bounds.
Each request has a bounded caller timeout, using existing per-operation output
limits; fallback has its own timeout. There is no infinite provider retry chain.

Provider schema handling never replaces local checks. Developer approved-path,
edit-kind, no-op, hash and diff validation still runs. Review findings still
require actual artifact evidence. Semantic evidence mapping can only create
**support** associations; it cannot independently mark a requirement verified.

## Status and observability

`GET /system/models` and **Settings · Models** show safe primary/fallback model
configuration, compatibility mode, and policy. Settings are read-only, with no
browser credential field. Backend key detection is a boolean, never a key value.
Ollama status uses only local `GET /api/tags`, cached for 15 seconds with a
three-second timeout; it checks the selected model, without generation or pull.

NVIDIA configuration is distinguished from confirmed availability. This page
does not issue cloud inference or claim connected status merely because a key
exists. Hosted availability is observed on real invocations. No documented
model-specific lightweight authenticated readiness contract is assumed here.

Every transport attempt yields purpose, actual provider/model, outcome,
fallback flag/reason, latency, optional request ID, and optional token usage.
Engineering snapshots carry `model_invocations` per operation, including failed
attempts; normal checkpoints append them to existing durable trace events once.
Product planning and evidence mapping append the same events to the existing
event table. Product plan records expose their invocation list. Advanced
engineering details, task execution timeline, and planning model log display
this metadata. Historical snapshots without these fields remain valid.
Transport success with invalid business data remains a successful *invocation*
paired with the existing failed *agent operation*; this distinction is deliberate.

## Security and limits

Keys use backend `SecretStr` and never appear in settings responses, model
events, browser configuration, or exception messages. Raw provider HTTP bodies,
headers, prompts, and reasoning are not logged or persisted by the gateway.
HTTP errors are replaced with safe typed messages and suppressed exception
context. Transport bypasses inherited proxies and refuses redirects. NVIDIA
uses only the exact official HTTPS endpoint; Ollama retains loopback HTTP only.
Requests are limited to 192 KiB and responses to 256 KiB.

Preview runtime behavior is unchanged. It does not inherit backend environment,
does not receive keys, and its explicit environment validator rejects `ASE_*`
and API-key names including `NVIDIA_API_KEY`. No new secret or model dependency
enters a preview container. Sending model-backed source/context to NVIDIA is an
intentional consequence of enabling the cloud route; legacy local mode stays local.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_gateway.py -q
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

Normal tests use mocked NVIDIA HTTP transports and local Ollama HTTP fixtures;
they require no NVIDIA key or cloud usage. Existing Docker/PostgreSQL integration
opt-ins continue to apply. No real NVIDIA inference test runs automatically.
Per-agent settings, cost estimates, other cloud providers, automatic model
downloads, benchmarking, deployment, and automatic task dispatch are outside
this phase.
