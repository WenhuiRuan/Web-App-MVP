"""Durable event tails; every poll releases SQLite before yielding or waiting."""
import asyncio
import json
import time
from uuid import UUID

from .lifecycle import LifecycleError

TERMINAL = {'COMPLETED', 'FAILED', 'INTERRUPTED'}


def cursor_for(discussion_id, after, last_event_id):
    if last_event_id is None:
        return after
    try:
        scope, sequence = last_event_id.split(':')
        if UUID(scope) != discussion_id or not sequence.isascii() or not sequence.isdecimal():
            raise ValueError()
        return int(sequence)
    except (ValueError, TypeError):
        raise LifecycleError('CURSOR_INVALID', '事件游标不属于本场讨论或格式无效，请重新读取快照。') from None


async def event_stream(request, repository, discussion_id, after, *, poll_seconds=.25, heartbeat_seconds=15):
    cursor = after
    last_heartbeat = time.monotonic()
    yield 'retry: 2000\n\n'
    while not await request.is_disconnected():
        events, high_water, state = await asyncio.to_thread(repository.event_page, discussion_id, cursor)
        for event in events:
            if await request.is_disconnected(): return
            cursor = event.seq
            yield f'id: {discussion_id}:{cursor}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n'
        if cursor >= high_water and state in TERMINAL:
            return
        if time.monotonic() - last_heartbeat >= heartbeat_seconds:
            last_heartbeat = time.monotonic()
            yield ': heartbeat\n\n'
        if not events:
            await asyncio.sleep(poll_seconds)
