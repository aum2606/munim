class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code


class Unauthorized(DomainError):
    def __init__(self) -> None:
        super().__init__("Invalid or expired credentials", 401)


class NotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("Resource not found", 404)
