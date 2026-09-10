"""API-facing shapes.

These are the boundary between the database and everything else: services return
them, the API serialises them, and the frontend's types are generated from them.
Keeping them free of SQLAlchemy is what lets ``ray.api`` avoid importing
``ray.db.models`` (ADR-0012).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ray.domain.enums import (
    EventSource,
    IntegrationStatus,
    IntegrationType,
    InvocationStatus,
    MemoryCategory,
    MemorySource,
    Modality,
    PermissionMode,
    Proficiency,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    llm_provider: str
    voice: "VoiceCapabilities"
    diagnostics: dict[str, str] = Field(default_factory=dict)


class VoiceCapabilities(BaseModel):
    """What the client may offer right now.

    The frontend renders its voice controls from this rather than hardcoding a
    phase, so upgrading the backend from browser to local speech needs no frontend
    change (ADR-0009).
    """

    stt_backend: str
    tts_backend: str
    wake_word_enabled: bool
    wake_word_phrase: str = "Ray"
    wake_words: list[str] = ["ray", "jarvis"]
    local_ready: bool = False
    local_detail: str = ""


class UserRead(ORMModel):
    id: uuid.UUID
    name: str
    email: str | None
    preferences: dict[str, object]
    settings: dict[str, object]
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    preferences: dict[str, object] | None = None
    settings: dict[str, object] | None = None


class ProjectRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    status: ProjectStatus
    technology_stack: list[str]
    progress: int | None
    repo_url: str | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    technology_stack: list[str] = Field(default_factory=list)
    repo_url: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None
    technology_stack: list[str] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    repo_url: str | None = None


class TaskRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    category: str | None
    deadline: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    project_id: uuid.UUID | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    category: str | None = None
    deadline: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    project_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    category: str | None = None
    deadline: datetime | None = None


class CalendarEventRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str
    start_time: datetime
    end_time: datetime
    location: str | None
    source: EventSource
    external_id: str | None
    task_id: uuid.UUID | None


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start_time: datetime
    end_time: datetime
    description: str = ""
    location: str | None = None
    task_id: uuid.UUID | None = None


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    start_time: datetime | None = None
    end_time: datetime | None = None
    description: str | None = None
    location: str | None = None
    task_id: uuid.UUID | None = None


class LearningRecordRead(ORMModel):
    id: uuid.UUID
    topic: str
    category: str
    proficiency: Proficiency
    strengths: str | None
    weaknesses: str | None
    notes: str | None
    last_reviewed: datetime | None
    updated_at: datetime


class MemoryRead(ORMModel):
    id: uuid.UUID
    category: MemoryCategory
    content: str
    importance: int
    why: str
    hit_count: int
    project_id: uuid.UUID | None
    source: MemorySource
    source_message_id: uuid.UUID | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryScored(BaseModel):
    """A retrieval result with the numbers behind it, so a surprising memory can be
    explained rather than guessed at."""

    memory: MemoryRead
    similarity: float
    score: float


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4_000)
    category: MemoryCategory = MemoryCategory.USER
    importance: int = Field(default=3, ge=1, le=5)
    why: str = ""
    project_id: uuid.UUID | None = None


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4_000)
    category: MemoryCategory | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    why: str | None = None


class MemoryStats(BaseModel):
    total: int
    by_category: dict[str, int]
    superseded: int
    """Merged predecessors, kept for auditing (ADR-0013)."""
    unembedded: int
    """Live memories with no vector: invisible to retrieval until re-embedded."""
    disabled_categories: list[MemoryCategory]


class MemoryCategorySettings(BaseModel):
    """Which categories the user has switched off. Everything else is on."""

    disabled_categories: list[MemoryCategory] = Field(default_factory=list)


class MessageRead(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    speech_text: str | None
    agent_name: str | None
    trace: dict[str, object] | None
    input_modality: Modality
    created_at: datetime


class ChatRequest(BaseModel):
    """One turn. Modality is part of the request because a spoken answer is a
    different answer, not a different renderer (ADR-0009)."""

    message: str = Field(min_length=1, max_length=10_000)
    conversation_id: uuid.UUID | None = None
    input_modality: Modality = Modality.TEXT
    output_modality: Modality = Modality.TEXT
    project_id: uuid.UUID | None = None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    message_count: int
    created_at: datetime
    last_message_at: datetime | None


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    messages: list[MessageRead]


class ProviderStatus(BaseModel):
    """One link in the provider chain, and why it is or is not usable."""

    name: str
    model: str
    configured: bool
    detail: str = ""


class AgentRead(BaseModel):
    """An entry in the code-side agent registry, plus its runtime state."""

    name: str
    display_name: str
    description: str
    enabled: bool
    tools: list[str]


class ToolRead(BaseModel):
    """A registered tool and the standing decision the user has made about it."""

    name: str
    description: str
    side_effect: bool
    # False where "always allow" is not offered at all: anything writing outside
    # Ray's own database always asks (ADR-0014).
    standing_allow_eligible: bool
    mode: PermissionMode


class ToolPermissionRead(BaseModel):
    tool_name: str
    mode: PermissionMode


class ToolPermissionUpdate(BaseModel):
    mode: PermissionMode


class ToolInvocationRead(ORMModel):
    """One tool call. The approval card is rendered from ``payload`` (ADR-0014), so
    the user approves the action that will actually run."""

    id: uuid.UUID
    tool_name: str
    payload: dict[str, object]
    side_effect: bool
    status: InvocationStatus
    result: dict[str, object] | None
    error: str | None
    conversation_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    """``always_allow`` records a standing decision alongside this one approval, which
    is what keeps the gate from becoming click fatigue (ADR-0014)."""

    always_allow: bool = False


class ApprovalOutcome(BaseModel):
    invocation: ToolInvocationRead
    message: str
    """What Ray says about the outcome, ready to append to the conversation."""


class IntegrationRead(ORMModel):
    id: uuid.UUID
    type: IntegrationType
    provider: str
    enabled: bool
    status: IntegrationStatus
    # Reference to an env var or keyring entry, never the secret itself (docs/12).
    credentials_reference: str | None
    config: dict[str, object]
    last_sync: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class IntegrationCreate(BaseModel):
    type: IntegrationType
    provider: str = Field(min_length=1, max_length=50)
    enabled: bool = True
    # Name of an environment variable or keyring key that holds the secret.
    credentials_reference: str | None = Field(default=None, max_length=200)
    config: dict[str, object] = Field(default_factory=dict)


class IntegrationUpdate(BaseModel):
    enabled: bool | None = None
    credentials_reference: str | None = Field(default=None, max_length=200)
    config: dict[str, object] | None = None


class DiagnosticsResponse(BaseModel):
    """Detailed self-diagnosis for the UI /settings page and CLI."""

    overall: str
    checks: dict[str, str]
    suggestions: list[str]


class WorkflowRunRead(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    success: bool | None
    output: str
    error: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class WorkflowRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    agent: str
    prompt: str
    enabled: bool
    interval_minutes: int
    last_run_at: datetime | None
    next_run_at: datetime
    runs: list[WorkflowRunRead] = []
    created_at: datetime
    updated_at: datetime


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    agent: str = Field(default="executive", min_length=1, max_length=50)
    prompt: str = Field(min_length=1, max_length=4_000)
    enabled: bool = True
    interval_minutes: int = Field(default=60, ge=1)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    agent: str | None = Field(default=None, min_length=1, max_length=50)
    prompt: str | None = Field(default=None, min_length=1, max_length=4_000)
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    next_run_at: datetime | None = None


class WorkflowRunSummary(BaseModel):
    """Result of a manual or scheduled workflow run."""

    workflow_id: uuid.UUID
    run_id: uuid.UUID
    success: bool
    output: str
    error: str = ""


class ExportSnapshot(BaseModel):
    """A complete, user-owned data export (docs/12, docs/13)."""

    version: str
    exported_at: datetime
    user: UserRead
    memories: list[MemoryRead]
    projects: list[ProjectRead]
    tasks: list[TaskRead]
    events: list[CalendarEventRead]
    integrations: list[IntegrationRead]
    tool_permissions: list[ToolPermissionRead]
    conversations: list[ConversationRead]
    workflows: list[WorkflowRead] = []


class IntegrationCheck(BaseModel):
    ok: bool
    message: str


HealthResponse.model_rebuild()
