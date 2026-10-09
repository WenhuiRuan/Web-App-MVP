"""One bounded run loop using public transcripts, pure arbitration and atomic writes."""
import asyncio
import time
from functools import partial

from pydantic import ValidationError

from .contracts import ModelRequest
from .model_gateway import InvalidModelResult,validate_result
from .scheduling import choose_speaker


class RunDeadline(Exception):
    pass


class ModelCallFailure(Exception):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


class DiscussionEngine:
    def __init__(self,supervisor):
        self.supervisor=supervisor
        self.repository=supervisor.repository
        self.db=supervisor._db_call
        self.deadline=0.0

    async def call_model(self,request):
        for attempt in range(self.supervisor.settings.model_max_attempts):
            remaining=self.deadline-time.monotonic()
            if remaining<=0: raise RunDeadline()
            budget_timeout=asyncio.timeout(remaining)
            call_timeout=None
            budget_limited=False
            try:
                # Queue time counts against the run budget; model timeout starts at actual IO.
                async with budget_timeout:
                    async with self.supervisor.semaphore:
                        available=self.deadline-time.monotonic()
                        if available<=0: raise RunDeadline()
                        budget_limited=available<=self.supervisor.settings.model_timeout_seconds
                        call_timeout=asyncio.timeout(min(available,self.supervisor.settings.model_timeout_seconds))
                        async with call_timeout:
                            raw=await self.supervisor.gateway_getter().generate(request)
                        if self.supervisor.closing or asyncio.current_task().cancelling():
                            raise asyncio.CancelledError()
                        if budget_timeout.expired() or (call_timeout.expired() and budget_limited) or time.monotonic()>=self.deadline:
                            raise RunDeadline()
                        if call_timeout.expired(): raise ModelCallFailure('MODEL_TIMEOUT')
                        return validate_result(request,raw)
            except asyncio.CancelledError:
                raise
            except RunDeadline:
                raise
            except TimeoutError:
                if budget_timeout.expired() or (call_timeout is not None and call_timeout.expired() and budget_limited): raise RunDeadline() from None
                code='MODEL_TIMEOUT'
            except ModelCallFailure as exc:
                code=exc.code
            except (InvalidModelResult,ValidationError):
                code='MODEL_RESULT_INVALID'
            except Exception:
                code='TASK_FAILED'
            if attempt+1==self.supervisor.settings.model_max_attempts:
                raise ModelCallFailure(code) from None
            await asyncio.sleep(0)  # Yield; retry budget is finite and cannot extend the run deadline.

    def context_request(self,context,task,actor):
        snapshot=context.snapshot; d=snapshot.discussion
        return ModelRequest(task=task,discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,roster_revision=d.roster_revision,actor_id=actor,participants=snapshot.participants,messages=snapshot.messages,cycle=context.cycle)

    async def collect_intents(self,context):
        experts=[p for p in context.snapshot.participants if p.kind=='EXPERT']
        async def assess(person):
            return await self.call_model(self.context_request(context,'intent',person.id))
        results=await asyncio.gather(*(assess(p) for p in experts),return_exceptions=True)
        for result in results:
            if isinstance(result,(RunDeadline,asyncio.CancelledError)): raise result
        valid={p.id:r for p,r in zip(experts,results) if not isinstance(r,BaseException)}
        if not valid:
            failure=next((r for r in results if isinstance(r,ModelCallFailure)),None)
            raise failure or ModelCallFailure('TASK_FAILED')
        return valid

    async def speak(self,context,actor,**task):
        claim=await self.db(partial(self.repository.prepare_turn,context,actor,**task))
        if claim is None or not await self.db(self.repository.mark_speaking,context,claim.id): return False
        output=await self.call_model(claim.request)
        committed=await self.db(self.repository.commit_turn,context,claim.id,output)
        if committed and (len(context.snapshot.messages)+1)%2==0:
            from .synthesis import SynthesisEngine
            await SynthesisEngine(self.supervisor).extract(context.snapshot.discussion.id,context.snapshot.discussion.run_id)
        return committed

    async def run(self,did,rid):
        first=True
        while not self.supervisor.closing:
            context=await self.db(self.repository.begin_cycle,did,rid)
            if context is None: return
            if first:
                self.deadline=time.monotonic()+context.remaining_seconds
                first=False
            snapshot=context.snapshot
            host=next(p for p in snapshot.participants if p.kind=='HOST')
            if not snapshot.messages:
                if not await self.speak(context,host.id,host_task='opening',public_focus='说明议题与讨论范围'): return
                continue
            control=await self.call_model(self.context_request(context,'host_control',host.id))
            if control.action=='end':
                await self.db(self.repository.finish_run,did,rid,'host_end')
                return
            candidates=await self.collect_intents(context)
            if not await self.db(self.repository.record_intents,context,candidates): return
            actor=choose_speaker(snapshot,candidates)
            last=snapshot.messages[-1]
            last_expert=any(p.id==last.participant_id and p.kind=='EXPERT' for p in snapshot.participants)
            if control.action=='linking' and last_expert:
                success=await self.speak(context,host.id,host_task='linking',public_focus=control.public_focus)
            elif actor is None:
                success=await self.speak(context,host.id,host_task='followup',public_focus=control.public_focus)
            else:
                intent=candidates[actor]
                success=await self.speak(context,actor,participation_kind=intent.kind,target_message_id=intent.target_message_id,public_focus=intent.public_focus)
            if not success: return
