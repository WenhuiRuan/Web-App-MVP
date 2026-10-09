"""Finite synthesis IO; insight failures preserve previously committed results."""
import asyncio
import logging
import time

from .engine import DiscussionEngine, ModelCallFailure, RunDeadline
from .lifecycle import RepositoryUnavailable

logger=logging.getLogger('panel')


class SynthesisEngine(DiscussionEngine):
    async def extract(self,did,rid):
        claim=None
        try:
            claim=await self.db(self.repository.claim_insights,did,rid)
            if claim is None: return
            self.deadline=time.monotonic()+self.supervisor.settings.insight_max_seconds
            output=await self.call_model(claim.request)
            await self.db(self.repository.complete_insights,claim,output)
            return
        except asyncio.CancelledError: raise
        except RunDeadline: code='MODEL_TIMEOUT'
        except ModelCallFailure as exc: code=exc.code
        except RepositoryUnavailable: code='DATABASE_UNAVAILABLE'
        except Exception: code='TASK_FAILED'
        if claim is not None:
            try: await self.db(self.repository.fail_insights,claim,code)
            except RepositoryUnavailable: logger.error('insight_failure_requires_restart_recovery')

    async def summarize(self,did,rid,claim=None):
        try:
            claim=claim or await self.db(self.repository.claim_summary,did,rid)
            if claim is None: return
            self.deadline=time.monotonic()+self.supervisor.settings.summary_max_seconds
            output=await self.call_model(claim.request)
            await self.db(self.repository.complete_summary,claim,output)
            return
        except asyncio.CancelledError: raise
        except RunDeadline: code='MODEL_TIMEOUT'
        except ModelCallFailure as exc: code=exc.code
        except RepositoryUnavailable: code='DATABASE_UNAVAILABLE'
        except Exception: code='TASK_FAILED'
        if claim is not None:
            try: await self.db(self.repository.fail_summary,claim,code)
            except RepositoryUnavailable: logger.error('summary_failure_requires_restart_recovery')
