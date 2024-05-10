import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, Dict, List

from nonebot import get_bots, logger
from nonebot.adapters import Bot as BaseBot
from nonebot.matcher import current_bot

from nonebot_plugin_apscheduler import scheduler

from ..config import config
from ..statistics import (
    bot_connect_time,
    bot_info_cache,
    recv_num,
    send_num,
)
from ..util import format_timedelta, use_redis_client
from . import normal_collector, periodic_collector

try:
    from nonebot.adapters.onebot.v11 import Bot as OBV11Bot
except ImportError:
    OBV11Bot = None


@dataclass
class BotStatus:
    self_id: str
    adapter: str
    nick: str
    bot_connected: str
    msg_rec: str
    msg_sent: str


async def get_ob11_msg_num(bot: BaseBot) -> Tuple[Optional[int], Optional[int]]:
    if not (config.ps_ob_v11_use_get_status and OBV11Bot and isinstance(bot, OBV11Bot)):
        return None, None

    try:
        bot_stat = (await bot.get_status()).get("stat")
    except Exception as e:
        logger.warning(
            f"Error when getting bot status: {e.__class__.__name__}: {e}",
        )
        return None, None
    if not bot_stat:
        return None, None

    msg_rec = bot_stat.get("message_received") or bot_stat.get(
        "MessageReceived",
    )
    msg_sent = bot_stat.get("message_sent") or bot_stat.get("MessageSent")
    return msg_rec, msg_sent


async def get_bot_status(bot: BaseBot, now_time: datetime) -> BotStatus:
    nick = (
        ((info := bot_info_cache[bot.self_id]).user_displayname or info.user_name)
        if (not config.ps_use_env_nick) and (bot.self_id in bot_info_cache)
        else next(iter(config.nickname), None)
    ) or "Bot"
    bot_connected = (
        format_timedelta(now_time - t)
        if (t := bot_connect_time.get(bot.self_id))
        else "未知"
    )

    msg_rec, msg_sent = await get_ob11_msg_num(bot)
    if msg_rec is None:
        msg_rec = recv_num.get(bot.self_id)
    if msg_sent is None:
        msg_sent = send_num.get(bot.self_id)
    msg_rec = "未知" if (msg_rec is None) else str(msg_rec)
    msg_sent = "未知" if (msg_sent is None) else str(msg_sent)

    return BotStatus(
        self_id=bot.self_id,
        adapter=bot.adapter.get_name(),
        nick=nick,
        bot_connected=bot_connected,
        msg_rec=msg_rec,
        msg_sent=msg_sent,
    )

async def cache_bot_status(bot: BaseBot, now_time: datetime) -> BotStatus:
    nick = (
        ((info := bot_info_cache[bot.self_id]).user_displayname or info.user_name)
        if (not config.ps_use_env_nick) and (bot.self_id in bot_info_cache)
        else next(iter(config.nickname), None)
    ) or "Bot"
    bot_connected = (
        format_timedelta(now_time - t)
        if (t := bot_connect_time.get(bot.self_id))
        else "未知"
    )

    msg_rec, msg_sent = await get_ob11_msg_num(bot)
    if msg_rec is None:
        msg_rec = recv_num.get(bot.self_id)
    if msg_sent is None:
        msg_sent = send_num.get(bot.self_id)
    msg_rec = "未知" if (msg_rec is None) else str(msg_rec)
    msg_sent = "未知" if (msg_sent is None) else str(msg_sent)

    return {
        'self_id': bot.self_id,
        'adapter': bot.adapter.get_name(),
        'nick': nick,
        'bot_connected': bot_connected,
        'msg_rec': msg_rec,
        'msg_sent': msg_sent,
    }

@scheduler.scheduled_job("interval", seconds=30, misfire_grace_time=30)
async def cache_bot_to_redis():
    now_time = datetime.now().astimezone()
    bots_status = await asyncio.gather(
        *(cache_bot_status(bot, now_time) for bot in get_bots().values()),
    )
    async with use_redis_client() as client:
        await client.delete(f'picstatus_bot:{config.port}')
        if len(bots_status):
            await client.lpush(f'picstatus_bot:{config.port}', *[json.dumps(b) for b in bots_status])
        return True

@normal_collector()
async def bots():
    if config.ps_show_current_bot_only:
        return {str(config.port): [await get_bot_status(current_bot.get(), datetime.now().astimezone())]}
    else:
        async with use_redis_client() as client:
            port_keys = sorted(await client.keys('picstatus_bot*'))
            port_bots_status: Dict[str, List[BotStatus]] = {}
            for port_key in port_keys:
                bots_status_redis = await client.lrange(port_key, 0, -1)
                bots_status = [json.loads(bot_status_redis) for bot_status_redis in bots_status_redis]
                port_bots_status[port_key.split(':')[1]] = [
                   BotStatus(
                       self_id=bot_status['self_id'],
                       adapter=bot_status['adapter'],
                       nick=bot_status['nick'],
                       bot_connected=bot_status['bot_connected'],
                       msg_rec=bot_status['msg_rec'],
                       msg_sent=bot_status['msg_sent']
                   ) for bot_status in bots_status
                ]
            return port_bots_status
                