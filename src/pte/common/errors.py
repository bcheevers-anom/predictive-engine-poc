class PTEError(Exception):
    pass

class AuthError(PTEError):
    def __init__(self, backend: str):
        super().__init__(
            f"No valid {backend} session. "
            "Run: aws sso login --profile staging"
        )
        self.backend = backend

class RateLimitError(PTEError):
    def __init__(self, backend: str, retry_after: float = 0.0):
        super().__init__(f"Rate limit hit on {backend}; retry after {retry_after}s")
        self.backend = backend
        self.retry_after = retry_after

class SnapshotError(PTEError):
    pass

class CursorDriftError(PTEError):
    pass

class ParseError(PTEError):
    pass

class ValidationError(PTEError):
    pass

class LLMError(PTEError):
    pass
