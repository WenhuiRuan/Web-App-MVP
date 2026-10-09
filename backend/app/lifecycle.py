"""Framework-independent lifecycle errors; domain transition rules grow by TDD."""
class LifecycleError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(code)


class RepositoryUnavailable(Exception):
    def __init__(self):
        super().__init__('DATABASE_UNAVAILABLE')
