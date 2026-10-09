"""Application-owned roster task registry, bounded model IO and safe failures."""
import asyncio
import logging

from pydantic import ValidationError

from .lifecycle import LifecycleError, RepositoryUnavailable
from .model_gateway import InvalidModelResult, validate_result

logger = logging.getLogger('panel')


class TaskSupervisor:
    def __init__(self, repository, settings, gateway_getter):
        self.repository, self.settings, self.gateway_getter = repository, settings, gateway_getter
        self.tasks: dict[str, asyncio.Task] = {}
        self.run_tasks: dict[str, asyncio.Task] = {}
        self.scheduled_runs: set[str] = set()
        self.admissions: set[asyncio.Task] = set()
        self.database_workers: set[asyncio.Task] = set()
        self.semaphore = asyncio.Semaphore(settings.model_max_concurrency)
        self.closing = False

    async def generate(self, discussion_id, key):
        return await self._command(self._admit_generation, discussion_id, key)

    async def start(self, discussion_id, body, key):
        return await self._command(self._admit_start, discussion_id, body, key)

    async def _admit_start(self, discussion_id, body, key):
        response=await self._db_call(self.repository.start,discussion_id,body,key,self.settings)
        rid=response.body['run_id']
        snapshot=await self._db_call(self.repository.snapshot,discussion_id)
        if not self.closing and snapshot.discussion.state=='RUNNING' and rid not in self.scheduled_runs:
            self.scheduled_runs.add(rid)
            task=asyncio.create_task(self._run_discussion(discussion_id,rid),name=f'discussion:{discussion_id}:{rid}')
            self.run_tasks[rid]=task
            task.add_done_callback(lambda finished:self._run_finished(rid,finished))
        return response

    def _run_finished(self,rid,task):
        self.run_tasks.pop(rid,None)
        if not task.cancelled() and task.exception() is not None:
            logger.error('discussion_task_requires_restart_recovery')

    async def _run_discussion(self,did,rid):
        from .engine import DiscussionEngine,ModelCallFailure,RunDeadline
        try:
            await DiscussionEngine(self).run(did,rid)
            from .synthesis import SynthesisEngine
            await SynthesisEngine(self).extract(did,rid)
            return
        except asyncio.CancelledError:
            raise
        except RunDeadline:
            try:
                await self._db_call(self.repository.finish_run,did,rid,'time_limit')
                from .synthesis import SynthesisEngine
                await SynthesisEngine(self).extract(did,rid)
                return
            except RepositoryUnavailable:
                code='DATABASE_UNAVAILABLE'
        except ModelCallFailure as exc:
            code=exc.code
        except (InvalidModelResult,ValidationError):
            code='MODEL_RESULT_INVALID'
        except RepositoryUnavailable:
            code='DATABASE_UNAVAILABLE'
        except Exception:
            code='TASK_FAILED'
        try:
            await self._db_call(self.repository.fail_run,did,rid,code)
        except RepositoryUnavailable:
            logger.error('discussion_failure_requires_restart_recovery')

    async def _command(self, function, *args):
        if self.closing:
            raise LifecycleError('SERVICE_SHUTTING_DOWN', '服务正在关闭，请稍后重试。')
        # A disconnected HTTP caller does not orphan an already committed admission.
        command = asyncio.create_task(function(*args))
        self.admissions.add(command)
        command.add_done_callback(self._command_finished)
        return await asyncio.shield(command)

    def _command_finished(self, command):
        self.admissions.discard(command)
        if not command.cancelled():
            command.exception()  # Consume errors even if the HTTP caller disconnected.

    async def _db_call(self, function, *args):
        # Cancelling to_thread does not cancel SQLite; drain it before recovery.
        worker = asyncio.create_task(asyncio.to_thread(function, *args))
        self.database_workers.add(worker)
        worker.add_done_callback(self.database_workers.discard)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.gather(worker, return_exceptions=True))
            raise

    async def _admit_generation(self, discussion_id, key):
        response, needs_task = await self._db_call(self.repository.admit_generation, discussion_id, key, self.settings.discussion_max_active, self.gateway_getter() is not None)
        if self.closing:
            raise LifecycleError('SERVICE_SHUTTING_DOWN', '服务正在关闭，请稍后重试。')
        op_id = response.body['operation_id']
        if needs_task and op_id not in self.tasks:
            task = asyncio.create_task(self._run_roster(op_id), name=f'roster:{discussion_id}:{op_id}')
            self.tasks[op_id] = task
            task.add_done_callback(lambda finished: self._finished(op_id, finished))
        return response

    def _finished(self, op_id, task):
        self.tasks.pop(op_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error('roster_task_unhandled_failure')

    async def _run_roster(self, op_id):
        try:
            async with self.semaphore:
                request = await self._db_call(self.repository.claim_generation, op_id)
                if request is None:
                    return
                raw = await asyncio.wait_for(self.gateway_getter().generate(request), timeout=self.settings.model_timeout_seconds)
                result = validate_result(request, raw)
                await self._db_call(self.repository.complete_generation, op_id, request, result)
        except asyncio.CancelledError:
            raise
        except (InvalidModelResult, ValidationError):
            await self._failure(op_id, 'MODEL_RESULT_INVALID', '嘉宾结果不符合契约，话题已保留，可以重试。')
        except TimeoutError:
            await self._failure(op_id, 'MODEL_TIMEOUT', '嘉宾生成超时，话题已保留，可以重试。')
        except RepositoryUnavailable:
            await self._failure(op_id, 'DATABASE_UNAVAILABLE', '阵容保存失败，已回滚，可以重试。')
        except Exception:
            await self._failure(op_id, 'TASK_FAILED', '嘉宾任务失败，话题已保留，可以重试。')

    async def _failure(self, op_id, code, message):
        try:
            await self._db_call(self.repository.fail_generation, op_id, code, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error('roster_failure_requires_restart_recovery')

    async def close(self):
        self.closing = True
        tasks = [*self.admissions, *self.tasks.values(), *self.run_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.database_workers:
            await asyncio.gather(*self.database_workers, return_exceptions=True)
        try:
            await self._db_call(self.repository.recover_unfinished)
        except RepositoryUnavailable:
            logger.error('shutdown_recovery_requires_writable_database_on_restart')
        self.tasks.clear()
        self.run_tasks.clear()
        self.scheduled_runs.clear()
        self.admissions.clear()
