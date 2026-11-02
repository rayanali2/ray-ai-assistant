# `/docs/09 UI and UX Specification.md`

# Ray — UI and UX Specification

## Purpose

This document defines the user interface and experience requirements for Ray.

Ray should feel like a personal AI assistant, not a traditional productivity application.

The interface should combine:

* AI conversation
* personal dashboard
* project management
* memory visibility
* task organization
* futuristic Jarvis-inspired design

---

# Design Goal

The user should feel like they are interacting with an intelligent system.

The interface should communicate:

* awareness
* organization
* intelligence
* personalization

The design should be visually impressive while remaining practical and fast.

---

# Overall Layout

The primary dashboard should contain several connected areas.

High-level structure:

```
-------------------------------------------------
| Ray Status | User Context | System Information |
-------------------------------------------------
|                                               |
|              Main Conversation                |
|                                               |
-------------------------------------------------
| Tasks | Projects | Calendar | Memory | Agents |
-------------------------------------------------
```

---

# Main Dashboard

The dashboard is the primary screen.

It should display:

## Conversation Area

The central interaction point.

Features:

* text chat
* voice controls
* conversation history
* streaming responses
* markdown support
* code formatting

### As implemented in Phase 2

* Tokens render as they arrive, with a caret while the turn is open. Markdown is
  parsed **incrementally**, so an unterminated code fence renders as code rather
  than as backticks that reflow when the fence closes.
* Markdown is rendered by a small in-house parser covering fenced code, inline
  code, bold, headings, and lists. It never emits raw HTML, so there is no
  injection surface to sanitise. Swap in a full parser when Ray needs tables.
* Auto-scroll follows the stream **only when the user is already at the bottom**;
  scrolling up to read must not be fought by every token.
* Voice and text converge on one `send`, differing only in modality, so a spoken
  turn and a typed turn are the same turn to everything downstream.
* Failure is a rendered state, never a blank screen: an unreachable backend, a
  mismatched token, and a mid-stream provider error each have their own message,
  and a retryable error offers a retry.
* `+ New` starts a fresh conversation; omitting `conversation_id` is what makes
  it new, so no separate endpoint is needed.
* Retrying a failed turn **replaces** it rather than stacking an identical question
  above it, and every turn carries a unique id so a slow or superseded stream cannot
  write into the turn after it.
* The most recent conversation is restored on load, fetched on the server, so a
  reload continues where Ray left off. Browsing *older* conversations needs a
  switcher, which is a later phase; `GET /chat/history` already backs it.
* Browser capability (speech recognition, speech synthesis) is detected **after**
  hydration, never during render: the server cannot know it, and disagreeing with the
  client is a hydration mismatch.

---

## Ray Status Area

Displays:

* current activity
* active agent
* current task
* system state

Examples:

```
Ray is analyzing your GitHub repository.

Active Agent:
Coding Agent

Using:
Project Memory
GitHub Integration
```

---

## Personal Overview Area

Displays:

* today's priorities
* upcoming events
* active projects
* important reminders

Example:

```
Today's Focus

1. Complete enemy AI system
2. Review Waterloo preparation tasks
3. Gym at 7 PM
```

---

# Jarvis-Inspired Visual Design

The interface should take inspiration from AI assistant interfaces.

Important characteristics:

## Futuristic Feel

Use:

* clean dark interface
* glowing elements
* smooth transitions
* subtle animations
* system-style panels
* data visualization

Avoid:

* excessive decoration
* distracting animations
* difficult navigation

---

# Voice Interface

**Voice is a primary interaction method, not a secondary one (ADR-0009).** The target
experience is: the user says "Ray", Ray activates, the user speaks, Ray answers aloud.
The interface is designed around that from the start, even while the underlying voice
implementation is still improving.

The interface should include:

## Voice Button

Allows:

* start listening
* stop listening
* indicate processing

---

## Voice State Indicators

Examples:

```
Idle (wake word armed)

Listening...

Processing...

Responding...
```

When wake-word detection is armed the interface must show a persistent, unmistakable
microphone indicator, and turning it off must always be one click away (`docs/12`).

The states are the pipeline's real states, not animation names:

```
idle → armed → listening → thinking → speaking → armed
```

`thinking` is driven by the request, not the microphone, so the indicator stays
truthful while the model is being waited on. Phase 2 fills these states with the
browser speech APIs behind one hook; replacing them with faster-whisper, Piper, and
openWakeWord changes nothing above the hook (ADR-0009).

Current behavior: local STT/TTS is implemented through `/voice/stream`, with ffmpeg
decoding for browser containers. The local HUD path is push-to-talk; continuous
local wake capture is not implemented. Browser wake mode is not a local-audio privacy
boundary because speech recognition may upload audio before the transcript filter.

Two constraints that are easy to get wrong:

* **Arming requires a user gesture.** Browsers only grant microphone permission from
  one, so Ray can never auto-arm on load even when the backend reports the wake word as
  enabled — that setting only makes the affordance primary.
* **The active STT backend must be named in the UI**, not implied by a microphone icon.
  `browser` recognition sends audio to Google (`docs/12`); a user who thinks "in the
  browser" means "on my machine" has been misled by the interface.

Push-to-talk is a peer of the wake word, not a fallback for broken wake-word detection:
it is the right input when speaking a long request or when the wake word would be
disruptive. Spoken replies are opt-in and off by default, and they speak `speech_text` —
a variant written to be *said*, not the markdown with the syntax stripped out.

---

# Agent Visualization

Ray should make its internal systems understandable.

Display:

* current agent
* tools being used
* completed actions

Example:

```
Executive Agent

↓

Coding Agent

↓

GitHub Tool

↓

Project Analysis Complete
```

This makes Ray feel intelligent while remaining transparent.

---

# Project View

Each project should have its own dashboard.

Example:

## Processing Game

Display:

```
Project Status

Progress: 65%

Current Goal:
Implement mouse aiming

Completed:
✓ Player movement
✓ Enemy spawning

Next:
Collision system
```

---

# Memory View

Users should be able to see and manage memories. Shipped in Phase 3 at `/memory`,
reachable from the HUD's Memory panel; the panel stays read-only so the HUD remains a
glance surface rather than an editor.

Features:

* search memories — substring by default, semantic when the query reads like a question,
  with the retrieval score shown so a surprising result can be explained
* view categories, with live counts, and switch any category off
* edit memories — content, importance, and category
* delete memories
* see provenance on every row: why Ray believes it, where it came from, and how often it
  has been used

Example:

```
Memory

Category:
Coding Preference

Content:
User prefers explanations before code.

Used By:
Coding Agent
Learning Agent
```

---

# Task View

Features:

* create tasks
* organize priorities
* mark completion
* connect tasks to projects

Example:

```
Ray Project

High Priority

Implement memory database

Due:
August 15
```

---

# Calendar View

Features:

* daily schedule
* weekly schedule
* upcoming events
* time blocks

Should integrate with external calendars where possible.

---

# Learning View

Displays:

* current topics
* progress
* recommended next steps

Example:

```
Learning Path

React

██████░░░░ 60%

Next:
State Management
```

---

# Responsive Design

The interface should work on:

* desktop first
* tablet
* mobile in future versions

Stack: Next.js 15 + React 19 + TypeScript, Tailwind CSS v4, shadcn/ui primitives,
TanStack Query, and Framer Motion used sparingly (ADR-0011). Streaming is consumed from
the SSE chat endpoint (ADR-0007).

The first version should prioritize desktop because development and usage will primarily occur there.

---

# Frontend Requirements

Preferred technologies:

* React
* Next.js
* TypeScript

Reason:

* strong ecosystem
* suitable for dynamic interfaces
* commonly used professionally

---

# UI Component Requirements

Components should be reusable.

Examples:

* ChatPanel
* TaskPanel
* CalendarPanel
* AgentStatus
* AgentTrace — renders the executive → agent → tool chain for a response
* ApprovalCard — shows the exact payload of a side-effecting tool call with
  Approve / Reject, and an "always allow" option where permitted (ADR-0014)
* MemoryCard — including provenance ("why does Ray believe this?")
* ProjectCard
* VoiceControl — wake-word state, listening state, push-to-talk, spoken-reply toggle,
  and the name of the active STT backend

Avoid creating duplicate UI logic.

---

# User Experience Rules

Ray should:

* provide clear feedback
* explain actions
* avoid silent failures
* keep important information visible
* minimize unnecessary clicks

---

# Future UI Improvements

Possible additions:

* holographic-style visualizations
* customizable dashboard layouts
* desktop application
* mobile application
* custom themes
* animated AI avatar

---

# Completion Criteria

The UI system is complete when:

* user can interact with Ray through the dashboard
* text conversations work
* voice interaction works
* tasks/projects/calendar are visible
* memory is accessible
* agents and actions are understandable
* interface has a polished Jarvis-inspired appearance
