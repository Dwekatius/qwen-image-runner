# Qwen Image Runner — v2.0: External APIs and AI control

**Deferred release · 2026-09-21 · Starts after v1.0 is usable**

[PLAN.md](PLAN.md) defines the image UI. v2.0 lets scripts and AI tools, including pi, operate that working app. Reuse its runtime, queue, storage, and UI. None of these dependencies, endpoints, or setup screens belong in v1.0.

## 1. Scope

- Versioned external REST for generation, edits, inputs, jobs, and images.
- Explicit OpenAI-compatible image subset, verified with actual SDK calls.
- MCP tools with asynchronous jobs and readable image delivery.
- One tested pi integration: maintained MCP adapter or direct REST extension.
- Headless start/attach, shared client ownership, settings, and documentation.

Other model families, remote/LAN hosting, accounts, and full A1111 compatibility are separate decisions. Model licenses continue to apply to agent-submitted work.

## 2. External contract

Use an external namespace such as /api/v1/, separate from private browser routes. Define health/capabilities/models, bounded input upload returning asset IDs, generation/edit submission returning HTTP 202 plus job ID, job polling/listing/cancellation, and image metadata/bytes. Add reconnectable events only where useful.

Finalize schemas, authentication, structured errors/status codes, pagination, limits, timeouts, request IDs, idempotency keys, and retention before building wrappers. All entry points use one application service and authoritative queue.

Return IDs promptly. Disconnect is not cancellation; idempotent retries cannot duplicate work. Completion requires durable output/gallery state. Use managed asset IDs rather than arbitrary server paths. Ordinary generation credentials cannot delete models, change arbitrary settings, or restart the engine.

## 3. OpenAI compatibility

Translate /v1/images/generations, /v1/images/edits, and /v1/models through the shared job service; do not blindly proxy around storage/validation.

Document and test local model IDs, prompt/n/size, base64/URL modes, multipart references, output encoding, success/error shapes, unsupported fields, synchronous waiting, timeouts, and retries. Reject unknown models rather than silently substituting.

OpenAI masks use transparent pixels for editable areas. Test conversion to the engine's mask channels/polarity, resizing, and first-reference association. Endpoint names alone do not establish compatibility. [A1][A2]

Streaming partial images and Responses API tools are not implied; add them only for a concrete client requirement with separate tests.

## 4. MCP and pi

| Tool | Returns |
|---|---|
| generate_image / edit_image | Job ID and submission status |
| get_job | State, real available progress, result IDs, errors |
| cancel_job | Actual cancellation/conflict outcome |
| list_models / engine_status | Validated capabilities/readiness |
| list_gallery | Bounded metadata |
| get_image | Readable image content/resource plus metadata |

A filename alone does not deliver an image to an AI client. Define image/resource retrieval, MIME types, payload bounds, and thumbnail/full-resolution choices. Local paths are optional supplementary data for trusted same-machine clients.

Start with stdio MCP; add Streamable HTTP only if the chosen client/agreed scope requires it. Pin a tested SDK; keep logs out of protocol stdout. Recheck SDK/client capabilities when implementation begins. [A3]

Choose one pi route: prefer a maintained MCP adapter if it passes the full job/image workflow; otherwise build a direct REST extension. Do not build both by default. Record tested versions and setup rather than assuming today's package maintenance or implementation time.

The original engine pin cannot cooperatively cancel running inference. Report that honestly; forced shared-engine shutdown is a separate privileged operation.

## 5. Headless lifecycle and protection

- Serialize concurrent startup with the existing instance lock and identity/readiness handshake; reuse the same app/engine.
- Auto-start is configurable and assumes installation/license/model setup is complete. It cannot silently accept terms or download large weights.
- Closing a UI/MCP client does not destroy other clients' work. Distinguish disconnect, idle unload, service shutdown, and forced engine stop.
- Preserve durable recovery, bounded restarts, model-switch rules, and client ownership of jobs.
- Authenticate external HTTP, validate Host/Origin, bind locally, and retain browser session/CSRF controls and SDK localhost protections. [A3][A4]
- Protect the engine port too; wrappers cannot secure bypass requests. Bound images/paths/queues/retention and omit secrets from logs/examples.

## 6. Phases and acceptance

| Phase | Exit condition |
|---|---|
| 0. Contracts and client proof | Chosen route proves jobs, auth, and image delivery |
| 1. External REST | Scripts generate/edit and retrieve durable results |
| 2. Compatibility | Actual SDK success/error/mask/timeout tests pass |
| 3. MCP and pi | Real pi session generates and edits inspectable images |
| 4. Headless/settings | Browser and agents coexist without duplicate engines/lost work |
| 5. Verify/release | Integration checks and v1 regressions pass; v2.0.0 ready |

Required acceptance:

1. All v1 browser workflows still work without an agent.
2. External/UI work shares the queue, gallery, IDs, and effective settings.
3. Actual SDK and every shipped MCP transport pass generation/edit/result/cancellation tests.
4. Pi retrieves an image, edits it, and leaves matching history in the UI.
5. Concurrent starts create one service; disconnect does not cancel another client's work.
6. Retries, crashes, saturation, and partial saves recover deterministically without duplication.
7. Unauthorized/cross-origin/oversized/out-of-root requests fail before side effects.
8. Clean client setup works with pinned dependencies and accurate licensing.

## References and status

Recheck sources and chosen engine/client versions when v2 begins.

[A1]: https://developers.openai.com/api/reference/python/resources/images/methods/generate
[A2]: https://developers.openai.com/api/reference/python/resources/images/methods/edit
[A3]: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
[A4]: https://py.sdk.modelcontextprotocol.io/run/deploy/

**Status: deferred until v1.0 works and v2.0 implementation is requested.**
