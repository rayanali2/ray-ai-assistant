# ADR-0003 — Local sentence-transformers embeddings

## Status

Accepted.

Implementation clarification: local embedding does not mean all memory text stays
local. Retrieved memories are included in chat prompts and can reach the selected
hosted/CLI provider. Embedding/storage stay local; see current `docs/12` privacy rules.

## Context

Semantic memory retrieval needs embeddings. `docs/05` requires free, open-source
embeddings and forbids paid memory services. Embeddings are also the highest-volume
model call in the system: every stored memory and every user turn needs one.

## Decision

**Embed locally with `sentence-transformers` using `all-MiniLM-L6-v2` (384 dimensions).**

Reasons, in priority order:

1. **Privacy.** Memories are the most sensitive data Ray holds. Embedding locally means
   the memory corpus never leaves the machine even when the chat model is hosted.
2. **Cost and rate limits.** Embedding on every turn against a hosted free tier would
   be the first thing to hit a quota. Local embedding has no quota.
3. **Speed.** MiniLM embeds a short memory in single-digit milliseconds on CPU. No
   network round trip on the hot path of every message.
4. **Size.** 384 dimensions keeps the pgvector index small and fast, and the model
   itself is ~90 MB.

The embedding call sits behind `ray.memory.embeddings.Embedder` so the model can be
swapped (e.g. to `bge-small-en-v1.5` for better recall) without touching retrieval code.
The model name and dimension are configuration, and the dimension is asserted against
the database column at startup so a mismatch fails loudly rather than silently
corrupting search.

## Alternatives considered

* **Hosted embedding APIs (Gemini, OpenAI).** Better quality per vector, but sends the
  entire private memory corpus to a third party, consumes free-tier quota on the hot
  path, and adds latency. Rejected.
* **Larger local models (`bge-base`, `e5-large`).** Better recall, several times slower
  and larger. Not worth it at this corpus size; the retrieval quality bottleneck is the
  scoring policy (ADR-0013), not the embedding model.

## Consequences

* First backend start downloads the model (~90 MB) — must be documented in the README
  and pre-warmed in the Docker image later.
* `torch` is a heavy Python dependency; we install the CPU-only wheel to keep the
  environment small.
* Changing the embedding model requires re-embedding all stored memories. A
  `scripts/reembed.py` maintenance script is part of the memory phase.
