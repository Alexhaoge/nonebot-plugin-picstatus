import re
import redis
from functools import partial
from typing import TYPE_CHECKING, List, Optional
import contextvars
from contextlib import asynccontextmanager

from cookit import auto_convert_byte, format_timedelta

from .config import config

if TYPE_CHECKING:
    from .collectors.cpu import CpuFreq

format_time_delta_ps = partial(format_timedelta, day_divider=" ", day_suffix="天")

_redis_current_connection_pool = contextvars.ContextVar("redis_current_connection_pool")
_redis_current_client = contextvars.ContextVar("redis_current_client")

def match_list_regexp(reg_list: List[str], txt: str) -> Optional[re.Match]:
    return next((match for r in reg_list if (match := re.search(r, txt))), None)


def format_cpu_freq(freq: "CpuFreq") -> str:
    cu = partial(auto_convert_byte, suffix="Hz", unit_index=2, with_space=False)
    if not freq.current:
        return "主频未知"
    if not freq.max:
        return cu(value=freq.current)
    if freq.max == freq.current:
        return cu(value=freq.max)
    return f"{cu(value=freq.current)} / {cu(value=freq.max)}"

@asynccontextmanager
async def use_redis_client():
    """
    Helper function for getting Redis client.
    """
    try:
        yield _redis_current_client.get()
    except LookupError:
        redis_pool = redis.ConnectionPool.from_url(config.redis_url, decode_responses=True)
        redis_client = redis.Redis(connection_pool=redis_pool, decode_responses=True)
        token_pool = _redis_current_connection_pool.set(redis_pool)
        token_client = _redis_current_client.set(redis_client)

        try:
            yield redis_client
        finally:
            await redis_client.aclose()
            await redis_pool.aclose()
            _redis_current_connection_pool.reset(token_pool)
            _redis_current_client.reset(token_client)
