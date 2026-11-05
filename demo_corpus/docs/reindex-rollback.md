# Versioned indexes and safe rollback

Re-indexing is the riskiest operation a retrieval system runs: a bad corpus
change or an embedding regression can quietly make every answer worse. JARVIS
makes that operation safe with versioned collections.

Each index build writes a brand-new collection, identified by its own index id,
and leaves it inactive. Nothing serves from it yet. The build then runs the
retrieval evaluation against the new collection, and only if the metrics pass
does it flip a single active pointer to make the new collection live. The
previous collection is left in place, untouched.

Because the switch is one pointer and the old data is still there, rollback is
instant: point back at the previous collection and the system is exactly as it
was. There is no destructive overwrite, no partial state, and no window where a
half-built index is serving traffic. Promotion is gated on evals; demotion is a
single step. This is the operational discipline that lets re-indexing happen
often and without fear.
