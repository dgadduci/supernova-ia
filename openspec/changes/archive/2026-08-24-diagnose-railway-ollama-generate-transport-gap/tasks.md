# Tasks

- [x] 1.1 Inspect the existing transport diagnostic and preserve its embed
  contract and default behavior.
- [x] 1.2 Add the minimal sanitized generate transport target using the same
  configured URL, loopback SOCKS proxy, timeout, and response-byte counting.
- [x] 1.3 Add focused tests for success, empty response, non-2xx, timeout,
  connection error, invalid proxy, response closure, and secret/payload
  non-exposure.
- [x] 1.4 Document the exact Railway command and safe Ollama correlation
  procedure without exposing endpoints, proxy values, credentials, or body
  content.
- [x] 1.5 Run focused pytest, Ruff, compileall, strict OpenSpec validation,
  and `git diff --check`; report all output and pre-existing failures.
- [x] 1.6 Stop after diagnosis. Do not modify worker, QueryLlm behavior,
  Tailscale, Railway variables, firewall, or Ollama configuration.
