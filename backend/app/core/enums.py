from enum import StrEnum


class AgentRunStatus(StrEnum):
    SUCCESS = "success"
    INVALID = "invalid"
    ERROR = "error"
