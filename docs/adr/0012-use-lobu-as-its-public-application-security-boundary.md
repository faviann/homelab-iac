# Use Lobu as its public application security boundary

Lobu's native authentication and authorization are authoritative for every
non-signup path on its canonical public origin; Traefik must not wrap that
surface in Authentik ForwardAuth or restrict it with an edge-maintained endpoint
allowlist, because either choice can break Lobu's OAuth, connector approval, and
other authenticated flows as their paths evolve.

Traefik still owns TLS termination and intercepts `/api/auth/sign-up` with a
higher-priority router targeting the serverless `noop` service, while the
database's unique human-principal index independently enforces the one-human
account invariant for requests that bypass the public edge. This deliberately
trades an additional edge authentication boundary for protocol compatibility
without delegating signup policy to Lobu alone.
