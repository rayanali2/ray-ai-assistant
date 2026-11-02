# `/docs/02 Technical Architecture.md`

# Ray — Technical Architecture

## Purpose

This document defines the technical structure of Ray.

The architecture should support:

* AI conversations
* voice interaction
* persistent memory
* specialized agents
* tool integrations
* personal productivity features
* future expansion

The system should remain modular and easy to modify.

---

# High-Level Architecture

Ray follows a modular agent-based architecture.

```
User
 |
 | Voice / Text
 |
Frontend Dashboard
 |
Backend API
 |
Ray Core
 |
+----------------+
| Executive Agent|
+----------------+
 |
 +----------------+
 | Agent System   |
 +----------------+
 |
 +------------+-------------+-------------+
 |            |             |             |
Planning   Coding      Learning     Research
Agent      Agent       Agent        Agent
 |
Tools
 |
Memory System
 |
Database
```

---

# Core Components

## 1. Frontend Dashboard

Purpose:

Provide the primary Ray interface.

The dashboard should have a futuristic Jarvis-inspired design.

The interface should prioritize:

* clean visuals
* smooth animations
* information visibility
* conversational interaction

Required sections:

### Main Chat Interface

Features:

* text conversation
* voice controls
* AI responses
* conversation history

---

### System Dashboard

Displays:

* current tasks
* calendar events
* projects
* active goals
* memory highlights
* agent activity

---

### Project View

Displays:

* active projects
* progress
* tasks
* notes
* related conversations

---

### Memory View

Displays:

* stored information
* user preferences
* project knowledge
* editable memories

---

# Frontend Requirements

Preferred stack:

* React
* Next.js
* TypeScript

Reason:

* widely used
* strong ecosystem
* suitable for interactive dashboards
* good developer experience

Styling:

* modern component system
* responsive layout
* futuristic AI assistant aesthetic

Design inspiration:

* Jarvis-style interfaces
* HUD layouts
* AI command centers

Avoid:

* unnecessary complexity
* excessive animations that hurt performance

---

# 2. Backend System

Purpose:

Handle:

* AI communication
* authentication
* memory retrieval
* agent coordination
* tool execution
* data management

Preferred stack:

* Python
* FastAPI

Reason:

* strong AI ecosystem
* simple API development
* excellent integration with AI tools

---

# 3. Ray Core

Ray Core is the central intelligence layer.

Responsibilities:

* receive user requests
* understand intent
* retrieve relevant memory
* select appropriate agent
* execute tools
* generate responses

The core should not contain domain-specific logic.

Instead, it delegates.

---

# 4. Executive Agent

The Executive Agent is the main coordinator.

Responsibilities:

* interpret user requests
* determine required actions
* delegate tasks
* combine agent responses
* maintain conversation flow

Example:

User:

"Help me prepare for my Waterloo CS courses while finishing my Processing game."

Executive Agent:

1. Sends academic planning to Learning Agent.
2. Sends project planning to Coding Agent.
3. Combines results.
4. Creates a realistic schedule.

---

# 5. Specialized Agents

Agents are **code modules**, not database rows (ADR-0005). The database stores only
runtime state: whether an agent is enabled, user overrides, and an activity log.

Agents should follow a common structure.

Each agent should contain:

* purpose
* available tools
* instructions
* memory access rules
* response format

---

# Initial Agents

## Planning Agent

Handles:

* tasks
* calendars
* scheduling
* reminders
* routines

---

## Coding Agent

Handles:

* programming questions
* project understanding
* debugging
* code explanations
* development guidance

---

## Learning Agent

Handles:

* studying
* teaching
* quizzes
* learning plans
* progress tracking

---

## Research Agent

Handles:

* information gathering
* topic exploration
* structured research
* technical investigation

---

## Memory (service, not an agent)

Handles:

* saving memories
* retrieving context
* updating knowledge

Memory retrieval runs on **every** request and must be fast and deterministic, so it is
implemented as a service that Ray Core always calls rather than as an agent behind an
LLM turn. Agents can additionally call it as a tool (`memory.search`, `memory.write`)
when they need to look something up mid-reasoning (ADR-0005).

---

# 6. Memory Architecture

Memory is separated into multiple layers.

## Short-Term Memory

Purpose:

Current conversation context.

Stores:

* recent messages
* current task
* active reasoning context

---

## Long-Term Memory

Purpose:

Permanent user knowledge.

Stores:

* preferences
* goals
* projects
* important facts

---

## Project Memory

Purpose:

Maintain context for specific projects.

Example:

Processing Game:

Stores:

* implemented features
* bugs
* roadmap
* coding decisions

---

# Memory Storage

**Decided:** PostgreSQL 16 + `pgvector` as the single store for both relational data and
semantic memory (ADR-0002), with embeddings generated locally by
`sentence-transformers` (ADR-0003). No paid memory services, and the memory corpus never
leaves the machine.

---

# 7. Tool System

Ray should interact with external tools through a controlled tool layer.

Examples:

## Calendar Tool

Functions:

* create events
* view schedule
* edit events

---

## File Tool

Functions:

* read documents
* analyze files
* organize notes

---

## GitHub Tool

Implemented read-only capability (writes remain future work):

* inspect repositories
* track issues
* assist development

---

## Web Research Tool

Implemented utility tools cover web search, Wikipedia and news; richer research
automation remains future work:

* research topics
* gather information
* summarize findings

---

# 8. Voice System

**Ray is voice-first (ADR-0009).** The full pipeline is part of the architecture from
Phase 1, even though its implementation quality improves across phases:

```
Browser: Microphone → Web Speech/transcript wake filter → Ray Core → SpeechSynthesis
Local:   Microphone → MediaRecorder → ffmpeg/STT (local backend) → Ray Core → Piper
```

Consequences for the rest of the architecture:

* Ray Core takes an `input_modality` and an `output_modality`; text is a special case of
  the voice path, not the other way around.
* Agents produce a `speech_text` variant alongside their markdown output, because a good
  spoken answer is shorter and contains no code blocks.
* Browser wake filtering runs on transcripts; the browser speech service may receive
  audio before activation. The HUD's local `/voice/stream` path is push-to-talk.
  Backend wake detection exists for continuous-audio clients, but continuous local
  capture is not implemented in the HUD. See README and ADR-0018 for current setup.

Chosen components, all free and local: openWakeWord, `faster-whisper`, and Piper, with
browser Web Speech / SpeechSynthesis as zero-setup fallbacks.

The voice layer remains behind interfaces (`WakeWordDetector`, `SpeechToText`,
`TextToSpeech`) and is independent from the AI layer.

---

# 9. Data Flow Example

User says:

"Plan my week and make time for my game."

Flow:

1. Voice converts speech to text.
2. Frontend sends request.
3. Backend receives request.
4. Executive Agent analyzes intent.
5. Memory retrieves:

   * current schedule
   * project status
   * priorities
6. Planning Agent creates schedule.
7. Coding Agent provides project time requirements.
8. Ray combines results.
9. Dashboard updates.
10. Optional voice response is generated.

---

# Development Requirements

Ray should be built incrementally.

Each component should:

* have clear responsibilities
* have documentation
* have tests where appropriate
* avoid unnecessary dependencies
* use free technologies

---

# Future Expansion

Architecture should allow:

* new agents
* new tools
* new interfaces
* mobile clients
* external integrations
* automation workflows

without rebuilding the core system.
