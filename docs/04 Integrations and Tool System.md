# `/docs/04 Integrations and Tool System.md`

# Ray — Integrations and Tool System

## Purpose

This document defines how Ray connects with external tools, applications, and user data sources.

Ray should not exist as an isolated chatbot. Its value comes from understanding the user's existing digital environment and taking action across connected services.

Ray should function as a central interface between the user and their tools.

---

# Integration Philosophy

Ray should integrate with existing platforms rather than replacing them.

Examples:

Instead of creating a new calendar:

* connect to existing calendar systems.

Instead of creating a new code hosting platform:

* connect to GitHub repositories.

Instead of creating a new notes system:

* connect to existing knowledge management tools such as Notion or Obsidian.

---

# Core Integrations

## 1. Calendar Integration

## Purpose

Allow Ray to understand and manage the user's schedule.

---

## Capabilities

Ray should be able to:

* view calendar events
* create events
* edit events
* remove events
* identify schedule conflicts
* suggest time allocations

---

## Example

User:

> "I need to finish my Processing game before moving to Waterloo."

Ray should:

1. Check existing commitments.
2. Review project status.
3. Determine available time.
4. Create a realistic plan.
5. Add scheduled blocks if approved.

---

## Preferred Implementation

Use free calendar APIs where possible.

Priority:

1. Existing user calendar integrations.
2. Free API tiers.
3. Local calendar storage as fallback.

---

# 2. Notion Integration

## Purpose

Allow Ray to access and organize structured personal information.

Potential uses:

* task databases
* notes
* project documentation
* university information
* personal planning

---

## Capabilities

Ray should be able to:

* read Notion pages
* search databases
* create entries
* update entries
* organize information

---

## Example

User:

> "Add my Waterloo preparation checklist."

Ray should:

* locate appropriate Notion database
* create tasks
* assign categories
* update progress

---

# 3. Obsidian Integration

## Purpose

Support personal knowledge management.

Obsidian may be used as a local knowledge base for Ray's long-term memory.

---

## Capabilities

Ray should be able to:

* read notes
* create notes
* link related concepts
* organize knowledge

---

## Possible Use

Ray could maintain:

* learning notes
* research
* project documentation
* ideas

---

# 4. GitHub Integration

## Purpose

Allow Ray to understand and assist with software projects.

---

## Capabilities

Ray should be able to:

* view repositories
* understand project structure
* read code
* track issues
* review changes
* suggest improvements
* assist with documentation

---

## Example

User:

> "What should I work on next in my Processing game?"

Ray should:

1. Inspect repository.
2. Understand current implementation.
3. Review completed features.
4. Identify next logical feature.
5. Explain the reasoning.

---

# 5. File System Integration

## Purpose

Allow Ray to interact with local files.

---

## Capabilities

Potential capabilities:

* read documents
* organize files
* summarize content
* analyze project folders

---

## Security Requirement

Ray must never access files without user permission.

---

# 6. Development Environment Integration

## Purpose

Allow Ray to assist with coding workflows.

Possible integrations:

* GitHub
* VS Code
* local development environments

---

## Capabilities

Future:

* analyze code
* explain errors
* suggest fixes
* track development progress
* generate documentation

---

# Tool Architecture

Integrations should not be directly embedded into agents.

Instead:

```id="f8t4s9"
Agent

↓

Tool Manager

↓

Integration

↓

External Service
```

Example:

Coding Agent

↓

GitHub Tool

↓

Repository

---

# Tool Manager

The layering is four levels, not three (ADR-0010):

```
Agent  →  Tool Manager  →  Adapter (interface)  →  Integration (concrete client)
```

An **adapter** is a capability interface (e.g. `CalendarAdapter`); an **integration** is
one implementation of it (`LocalCalendar`, `GoogleCalendar`, `ICSCalendar`). Swapping
providers is a configuration change and the agent never notices.

Adapters exist where multiple providers realistically compete — calendar and knowledge.
GitHub and the file system have a single implementation each and do not get a
speculative interface.

The Tool Manager controls:

* the tool registry and the JSON schemas agents see
* authentication and credential injection — secrets never enter an agent's context
* permissions and the approval gate for side-effecting tools (ADR-0014)
* timeouts, retries, and normalised typed errors
* activity logging for every call

---

# Self-Improvement System

Ray should be designed to improve through feedback.

The user should be able to say:

> "Ray, this workflow is annoying. Change it."

Ray should:

1. Understand the issue.
2. Identify the relevant component.
3. Suggest a change.
4. Create an improvement task.
5. Implement the change only after approval.

---

# Self-Repair Capability

Ray should be able to identify problems.

Examples:

* broken integrations
* failed API calls
* outdated information
* incorrect workflows

When a failure occurs:

Ray should:

1. Explain the problem.
2. Identify possible causes.
3. Suggest fixes.
4. Apply approved changes.

---

# Free Technology Requirement

All integrations should prioritize:

* free APIs
* open-source libraries
* local solutions
* free hosting tiers

Paid APIs or subscriptions should not be required for normal operation.

---

# Integration Priority

Integrations are **not equivalent** in cost, setup difficulty, or value. Build in this
order (ADR-0010):

## Version 1

1. **Internal database tools** — tasks, projects, calendar, memory
2. **GitHub** — read-only (repository tree, file contents, commits, issues). Free API,
   personal access token, no OAuth app required. Highest value for the Coding Agent.
   Write access is post-V1 and always requires per-call approval.
3. **Calendar** — `LocalCalendar` is the default with ICS import/export. Google Calendar
   is **opt-in** behind the same adapter because it requires a Google Cloud project and
   OAuth consent. Implemented via PKCE/loopback OAuth; events are read live, not
   bidirectionally synchronized. Create/update/delete require per-call approval.
4. **Knowledge — Obsidian first.** An Obsidian vault is a directory of markdown files:
   local, free, no API, no auth. Notion is a second implementation of the same adapter
   and is implemented but optional: token/shared pages, paginated search/read,
   approved create/append. See README and ADR-0021 for credentials and limitations.
5. **Local files** — read and summarise within explicitly allow-listed directories only.

---

## Future

6. Email
7. Browser tools
8. Mobile integrations
9. Additional productivity tools

---

# Design Goal

The final experience should feel like:

> "Ray understands my digital world and helps me operate it."

The user should not need to manually move information between applications.

Ray should connect existing tools into one intelligent assistant.
