"""Provider-neutral request/response types."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskKind(str, Enum):
    """What an LLM call is for. Models are selected per task kind."""

    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    PLANNING = "planning"
    IMPACT = "impact"
    ROOT_CAUSE = "root_cause"
    CLASSIFICATION = "classification"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class ChatRequest(BaseModel):
    messages: list[Message]
    max_output_tokens: int = Field(default=4096, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    json_schema: dict | None = None  # request native structured output when supported


class ChatResponse(BaseModel):
    text: str
    usage: Usage = Field(default_factory=Usage)
    model: str
    provider: str


class ProviderError(Exception):
    """Base provider failure. `retryable` drives retry/fallback policy."""

    retryable = False


class RateLimitError(ProviderError):
    retryable = True

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderAuthError(ProviderError):
    retryable = False


class StructuredOutputError(ProviderError):
    """Model output could not be validated against the requested schema."""

    retryable = False


class NoEligibleModel(Exception):
    """No configured model satisfies the task's requirements."""


class BudgetExceeded(Exception):
    """Token or cost budget would be exceeded. Never retried."""
