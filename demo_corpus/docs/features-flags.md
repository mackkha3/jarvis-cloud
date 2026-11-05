# Feature flags

JARVIS gates optional capabilities behind environment-variable feature flags
read once at startup through a small helper. Each flag maps a name such as
retrieval, voice, or briefings to an environment variable, and `is_enabled`
returns whether it is on. Code paths check the flag rather than assuming a
capability is present.

This keeps the bring-your-own-infrastructure model honest: an operator who has
not configured a subsystem simply leaves its flag off, and the corresponding
code never runs, never imports its heavy dependencies, and never errors. The
retrieval layer is behind its own flag, so a deployment can run JARVIS with no
corpus and no index at all, and the assistant behaves exactly as it did before
retrieval existed.

Flags also make rollout reversible. Turning a capability off is a configuration
change and a restart, not a code change, which pairs well with the versioned
index design: if something about retrieval misbehaves in production, it can be
switched off immediately while the cause is investigated.
