# Security Policy

Qwen Image Runner is a **local-only** application. It binds to `127.0.0.1` and is not designed to be
exposed to a network.

## Design notes (why this is safe to run)

- The web UI/API listens on `127.0.0.1:7878` only; the inference engine listens on `127.0.0.1:1235` only.
- Requests are validated: `Host`/`Origin` checks plus a CSRF token for every mutating request
  (`X-CSRF` header). The token is stored in `settings.json` (not committed) so open windows survive
  restarts.
- Mutating endpoints are localhost-only; the browser UI cannot be driven cross-origin.
- The app never uploads prompts or images anywhere. Network access happens only for explicit,
  user-initiated downloads (engine build, model weights) from pinned URLs, verified by SHA-256.
- The "Save as…" dialog is a native Windows dialog invoked by the local backend on your behalf.

## Things to be aware of

- Anything that can make HTTP requests from your machine can talk to the local API. Do not run this
  app on a shared/remote desktop while others are logged in.
- The engine downloads and executes a prebuilt binary from the stable-diffusion.cpp GitHub release
  (pinned + checksummed). Some antivirus products flag freshly downloaded executables; verify the
  SHA-256 in `engine.json` if in doubt.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** ("Report a vulnerability" under the Security
tab) rather than a public issue. Include reproduction steps and the version shown in the app title.

There is no bug-bounty program.
