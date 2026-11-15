"""Domain errors. Raised anywhere; mapped to HTTP responses centrally in app.main."""


class DomainError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.__name__
        super().__init__(self.message)


class UnauthorizedError(DomainError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class LLMOutputError(DomainError):
    """The model kept returning output that does not match the schema."""

    status_code = 502
    code = "llm_invalid_output"


class LLMUnavailableError(DomainError):
    """Every provider in the fallback chain failed."""

    status_code = 503
    code = "llm_unavailable"
