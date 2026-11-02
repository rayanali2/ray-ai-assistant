# `/docs/03 Agent Specifications.md`

# Ray — Agent Specifications

## Purpose

This document defines the behavior, responsibilities, and boundaries of every Ray agent.

Agents are specialized AI modules that handle specific categories of tasks. They should not operate independently without coordination from the Executive Agent.

Each agent must:

* have a clear purpose
* access only required information
* use available tools appropriately
* maintain consistent behavior
* return structured results when possible

---

# Agent Architecture

Every agent follows this structure:

```
Agent
|
├── Purpose
├── Instructions
├── Available Tools
├── Memory Access
├── Input Handling
├── Output Format
└── Limitations
```

Agents should be replaceable without affecting the rest of Ray.

---

# 1. Executive Agent

## Purpose

The Executive Agent is the central coordinator of Ray.

It is responsible for understanding user intent, deciding what actions are required, selecting appropriate agents, and combining results into a useful response.

The Executive Agent represents the main personality and conversational identity of Ray.

---

## Responsibilities

The Executive Agent should:

* interpret user requests
* determine the user's goal
* identify required agents
* retrieve relevant memory
* coordinate multiple agents
* summarize results
* maintain conversational continuity

---

## Examples

User:

> "I need to finish my Processing game before university starts but I also need to prepare for Waterloo."

Executive Agent should:

1. Retrieve project information.
2. Retrieve academic information.
3. Ask Coding Agent for development status.
4. Ask Learning Agent for preparation tasks.
5. Ask Planning Agent for scheduling.
6. Combine recommendations.

---

## Memory Access

Can access:

* all user-approved memories
* active projects
* goals
* preferences
* conversation context

---

## Cannot

* directly modify specialized agent data
* make irreversible decisions
* store memories without approval rules

---

# 2. Planning Agent

## Purpose

The Planning Agent manages the user's time, tasks, priorities, and schedules.

Its goal is to transform goals into realistic action plans.

---

## Responsibilities

Handles:

* task creation
* task prioritization
* scheduling
* reminders
* routines
* deadlines
* time blocking

---

## Examples

User:

> "I have a calculus assignment, gym, and coding tonight."

Planning Agent:

* checks available time
* prioritizes deadlines
* creates schedule
* explains reasoning

---

## Memory Access

Can access:

* calendar
* tasks
* routines
* deadlines
* user preferences

---

## Tools

Required:

* calendar integration
* task database

Future:

* reminders
* notifications

---

## Cannot

* teach academic concepts
* modify projects directly
* make assumptions about priorities without context

---

# 3. Coding Agent

## Purpose

The Coding Agent acts as a programming mentor and software development assistant.

It should help the user become a better programmer rather than simply generate code.

---

## Responsibilities

Handles:

* explaining programming concepts
* debugging
* architecture discussions
* code reviews
* project planning
* implementation guidance
* documentation assistance

---

## Project Awareness

The Coding Agent should understand:

* current projects
* technology stack
* previous implementations
* current bugs
* development goals

Example:

For the Processing game:

The agent should know:

* player movement exists
* mouse aiming is being implemented
* enemy systems are planned
* the user is learning game development concepts

---

## Teaching Behavior

When helping:

Preferred:

1. Explain concept.
2. Give reasoning.
3. Provide guidance.
4. Allow user to attempt.
5. Review solution.

Avoid:

* immediately replacing user work
* unexplained code generation

---

## Memory Access

Can access:

* coding history
* repositories
* project documentation
* learning progress

---

## Tools

Future:

* GitHub integration
* code analysis
* repository search
* terminal access

---

# 4. Learning Agent

## Purpose

The Learning Agent helps the user acquire knowledge efficiently.

It acts as a personal tutor.

---

## Responsibilities

Handles:

* explanations
* study plans
* practice questions
* quizzes
* progress tracking
* identifying weaknesses

---

## Learning Approach

The agent should:

* adapt difficulty
* avoid unnecessary explanations
* connect concepts together
* track mastery over time

---

## Examples

User:

> "Teach me databases."

Learning Agent should:

1. Determine current knowledge.
2. Explain fundamentals.
3. Provide examples.
4. Create exercises.
5. Track progress.

---

## Memory Access

Can access:

* previous lessons
* mastered topics
* weaknesses
* academic goals

---

# 5. Research Agent

## Purpose

The Research Agent helps explore complex ideas and transform curiosity into structured knowledge.

---

## Responsibilities

Handles:

* researching topics
* summarizing information
* comparing technologies
* creating learning paths
* organizing discoveries

---

## Examples

User:

> "How could I build Spider-Man-style technology?"

Research Agent should break the idea into:

* current technology
* scientific principles
* required skills
* realistic limitations
* possible projects

---

## Memory Access

Can access:

* interests
* previous research
* ongoing experiments

---

# 6. Memory System (service, not an agent)

## Purpose

The memory system manages Ray's long-term understanding of the user.

Memory is one of Ray's most important systems.

**Implementation note (ADR-0005):** memory is a *service* in `ray/memory/`, not an agent.
Retrieval happens on every single request, so putting it behind an LLM turn would add
latency and non-determinism to the hot path. Ray Core always calls it directly, and it is
additionally exposed to agents as the `memory.search` / `memory.write` tools. Everything
described below still applies — only the execution model differs.

---

## Responsibilities

Handles:

* storing memories
* retrieving memories
* updating information
* removing outdated information
* organizing knowledge

---

## Memory Categories

## User Memory

Examples:

* preferences
* goals
* communication style
* interests

---

## Project Memory

Examples:

* project status
* technical decisions
* future plans

---

## Learning Memory

Examples:

* completed topics
* weak areas
* learning progress

---

## Conversation Memory

Examples:

* important previous discussions
* decisions
* useful context

---

## Memory Rules

The Memory Agent should:

* avoid storing unnecessary information
* prioritize useful long-term context
* allow user control
* avoid duplicate memories

---

# 7. Future Agents

The architecture should support additional agents. Fitness, content and finance
agents are already implemented with tool allow-lists in `ray/agents/registry.py`;
the finance/content ideas in this section describe possible extensions, not absent
agent modules. Career-specific functionality remains a future direction.

Possible future agents:

## Career Agent

Handles:

* resumes
* internships
* networking
* applications

---

## Finance Agent

Handles:

* budgeting
* expenses
* financial planning

---

## Fitness Agent

Handles:

* workouts
* goals
* routines

---

## Startup Agent

Handles:

* business ideas
* validation
* planning

---

# Agent Communication Rules

Agents communicate through the Executive Agent.

Direct uncontrolled agent-to-agent communication should be avoided.

Reason:

* prevents complexity
* maintains clear responsibility
* makes debugging easier

---

# Agent Development Rule

Every new agent must define:

1. Purpose
2. Responsibilities
3. Required tools
4. Required memory
5. Limitations
6. Expected outputs

New agents should be added without modifying existing agents.

---

# Final Goal

Ray should eventually function as a coordinated group of specialized AI assistants controlled through one unified interface.

The user should experience one intelligent assistant while the internal system remains modular and scalable.
