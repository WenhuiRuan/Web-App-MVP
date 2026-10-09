"""Framework-independent lifecycle errors; domain transition rules grow by TDD."""
class LifecycleError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(code)


class RepositoryUnavailable(Exception):
    def __init__(self):
        super().__init__('DATABASE_UNAVAILABLE')


def generation_revision(state: str, failure_stage: str | None, current_revision: int) -> int:
    if state == 'DRAFT' or (state in ('FAILED', 'INTERRUPTED') and failure_stage == 'roster'):
        return current_revision + 1
    raise LifecycleError('INVALID_STATE', '当前状态不能生成嘉宾阵容。')


def require_capacity(active_count: int, max_active: int) -> None:
    if active_count >= max_active:
        raise LifecycleError('CAPACITY_EXCEEDED', '当前运行任务已达到容量上限，请稍后重试。')


def should_create_run(state: str, current_revision: int, requested_revision: int, has_run: bool) -> bool:
    if current_revision == 0:
        raise LifecycleError('INVALID_STATE', '阵容尚未就绪，不能开始讨论。')
    if current_revision != requested_revision:
        raise LifecycleError('ROSTER_VERSION_CONFLICT', '阵容版本已变更，请刷新后确认。')
    if has_run:
        return False
    if state != 'READY':
        raise LifecycleError('INVALID_STATE', '当前状态不能确认阵容。')
    return True
