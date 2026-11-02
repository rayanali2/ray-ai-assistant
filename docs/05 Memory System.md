# `/docs/05 Memory System.md`

# Ray — Memory System Specification

## Purpose

Memory is one of Ray's core capabilities.

Without memory, Ray is only a temporary chatbot.

With memory, Ray becomes a personalized assistant that understands the user's projects, goals, preferences, and history over time.

The memory system allows Ray to provide context-aware responses and improve usefulness through continued interaction.

---

# Memory Goals

Ray's memory system should:

* remember important user information
* understand ongoing projects
* track learning progress
* recall previous decisions
* avoid repeating questions
* provide relevant context automatically

---

> **Policy is specified in ADR-0013.** The write triggers, importance scale, dedupe and
> merge thresholds, retrieval scoring formula, and expiry rules referenced throughout
> this document are defined concretely there. This document states the intent; the ADR
> states the mechanism.

---

# Memory Principles

## 1. Useful Over Complete

Ray should not store every conversation.

Memory should contain information that improves future interactions.

Examples of useful memories:

* "User prefers learning through explanations before receiving code."
* "User is building a Processing game called Starfall Sprint."
* "User is starting Waterloo CS + BBA."

Examples of unnecessary memories:

* temporary conversation details
* random one-time questions
* irrelevant messages

---

## 2. User Control

The user must be able to:

* view stored memories
* edit memories
* delete memories
* disable memory categories

Ray should never permanently store sensitive information without appropriate user control.

---

## 3. Context Awareness

Ray should automatically retrieve relevant memories.

Example:

User:

> "What should I implement next?"

Ray should recognize the active project and retrieve:

* current project state
* previous progress
* unfinished tasks
* technical decisions

---

# Memory Categories

## 1. User Profile Memory

Stores long-term information about the user.

Examples:

* preferences
* goals
* interests
* learning style
* preferred communication style

---

## 2. Project Memory

Stores information about projects.

Examples:

```
Project:
Starfall Sprint

Technology:
Processing Java

Current Status:
Player movement complete

Next Goal:
Mouse aiming system

Important Decisions:
Use classes for entities
```

---

Project memory should track:

* project description
* goals
* roadmap
* technologies
* files
* progress
* decisions
* problems
* solutions

---

## 3. Learning Memory

Stores educational progress.

Examples:

```
Topic:
Object-Oriented Programming

Status:
Intermediate

Strength:
Classes and objects

Weakness:
Inheritance
```

---

Learning memory should allow Ray to:

* avoid reteaching mastered concepts
* focus on weaknesses
* create personalized learning plans

---

## 4. Goal Memory

Stores long-term objectives.

Examples:

* university goals
* career goals
* personal projects
* skill development

Ray should use goals when recommending actions.

---

## 5. Conversation Memory

Stores important previous discussions.

Examples:

* decisions made
* plans created
* unresolved problems

Temporary conversations should not automatically become permanent memories.

---

# Memory Architecture

Memory should use multiple layers.

```id="4x5qpn"
Conversation Context

(short term)

        ↓

Working Memory

(current tasks)

        ↓

Long-Term Memory

(user knowledge)

        ↓

Knowledge Base

(projects, notes, documents)
```

---

# Short-Term Memory

Purpose:

Maintain current conversation understanding.

Stores:

* recent messages
* current request
* current reasoning context

Lifetime:

Temporary.

---

# Working Memory

Purpose:

Handle active situations.

Examples:

* current coding session
* current planning task
* active research question

Lifetime:

Hours to days.

---

# Long-Term Memory

Purpose:

Permanent useful information.

Stores:

* preferences
* projects
* goals
* learned information

Lifetime:

Months to years.

---

# Memory Retrieval

When responding, Ray should:

1. Understand the user's request.
2. Identify relevant topics.
3. Search memory.
4. Retrieve useful context.
5. Include context in reasoning.
6. Generate response.

Example:

User:

> "Help me continue my game."

Ray should retrieve:

* game name
* previous progress
* code context
* current objective

---

# Memory Storage Process

Extraction runs **after** the response is produced, off the critical path, so it never
adds latency to a reply.

1. Identify information type (category).
2. Determine importance (1–5).
3. Check for duplicates by embedding similarity within the category:
   * ≥ 0.95 — discard as duplicate, refresh the existing memory
   * 0.85–0.95 — merge into the existing memory and supersede the old row
   * < 0.85 — insert as new
4. Store only if durable (true beyond this conversation) *and* actionable (it would
   change a future response).
5. Record provenance: source, source message, and a one-line `why`.

Structured data that already lives in `projects`, `tasks`, or `learning_records` is not
duplicated into prose memories.

The user can always force a write with "Ray, remember that…".

---

# Memory Database Requirements

The system should prioritize free technologies.

Preferred approach:

## Primary Storage

Relational database:

* PostgreSQL

Stores:

* users
* projects
* tasks
* memories
* conversations

---

## Semantic Search

**PostgreSQL with the `pgvector` extension** (ADR-0002) — the same database as everything
else, so a memory query can filter by category and project *and* rank by similarity in
one statement.

**Embeddings are generated locally** with `sentence-transformers`
(`all-MiniLM-L6-v2`, 384 dimensions) (ADR-0003). Storage and embedding computation
are local and consume no hosted embedding quota. Retrieved memories can still
leave the machine as context sent to the selected hosted/CLI chat provider.

Retrieval is hybrid, not pure similarity: similarity, importance, recency, and past
usage are combined, with a boost for memories scoped to the active project. See
ADR-0013.

**Two embedding backends exist** (ADR-0016). `sentence-transformers` is the default and
is the Settings default; automatic bootstrap and local/subscription presets select
`hashing`, which needs no torch install and no download, is what
CI runs, and is what a machine missing the optional install silently degrades to. The
backends occupy *different vector spaces*: switching `RAY_EMBEDDING_BACKEND` invalidates
existing embeddings and requires re-embedding. `GET /memory/stats` reports how many live
memories have no vector, because an unembedded memory is still listed and editable but
invisible to retrieval.

No paid memory services are used.

---

# Memory Security

Ray must:

* protect stored information
* avoid unnecessary collection
* allow deletion
* keep credentials secure

Personal information belongs to the user.

---

# Memory Interface

Shipped in Phase 3 at `/memory`, alongside the read-only Memory panel on the HUD.

Features:

* view memories
* search memories — substring for hunting a known memory, semantic (with the retrieval
  score shown) for understanding why Ray keeps using one
* edit memories — editing the content re-embeds it, so search follows the correction
* remove memories — a hard delete that takes effect on the next request
* see why a memory exists — the extraction reason, the source (`conversation`, `user`,
  or an integration), when it was created, and how often it has been used
* switch a category off — stops both retrieval and future writes in that category
  without deleting anything

Example:

```
Memory:

"User prefers learning through guidance first."

Created:
August 2026

Used for:
Coding Agent
Learning Agent
```

---

# Future Memory Improvements

Possible additions:

* automatic knowledge graph
* relationship mapping
* document understanding
* personalized recommendations
* memory importance scoring
* automatic project summaries

---

# Completion Criteria

The memory system is complete when:

* Ray remembers important user information
* Ray retrieves relevant context automatically
* Ray understands active projects
* Ray improves conversations over time
* users can control stored information
* memory works without paid services
