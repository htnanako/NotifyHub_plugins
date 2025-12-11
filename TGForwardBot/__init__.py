"""TG双向私聊/群组话题机器人插件"""
import logging
import asyncio

from notifyhub.plugins.common import after_setup

from .bot import start_bot, stop_bot, get_bot
from .group import start_group_bot, stop_group_bot, get_group_bot
from .config import config

logger = logging.getLogger(__name__)

PLUGIN_ID = "TGForwardBot"


def _get_forward_mode() -> str:
    """获取转发模式（private/group），非法值回退为 private"""
    try:
        mode = (config.forward_mode or "private").lower().strip()
        if mode not in {"private", "group"}:
            logger.warning(f"[{PLUGIN_ID}] 未知转发模式 {mode}，回退为 private")
            return "private"
        return mode
    except Exception:
        return "private"


@after_setup(PLUGIN_ID, "初始化TG转发机器人")
async def init_tg_bot():
    """根据配置模式启动私聊模式或群组话题模式"""
    try:
        mode = _get_forward_mode()
        
        if mode == "group":
            if not config.is_group_mode_valid():
                logger.error(f"[{PLUGIN_ID}] 群组模式配置无效，未启动")
                return
            from .group import init_group_bot  # 延迟导入以避免未使用时加载
            init_success = await init_group_bot()
            if not init_success:
                logger.error(f"[{PLUGIN_ID}] 群组模式初始化失败")
                return
            
            async def run_background():
                try:
                    logger.info(f"[{PLUGIN_ID}] 正在后台启动群组话题模式...")
                    await start_group_bot()
                except Exception as e:
                    logger.error(f"[{PLUGIN_ID}] 群组模式运行出错: {e}", exc_info=True)
        else:
            if not config.is_valid():
                return
            from .bot import init_bot  # 延迟导入
            init_success = await init_bot()
            if not init_success:
                logger.error(f"[{PLUGIN_ID}] 私聊模式初始化失败")
                return
            
            async def run_background():
                try:
                    logger.info(f"[{PLUGIN_ID}] 正在后台启动私聊模式...")
                    await start_bot()
                except Exception as e:
                    logger.error(f"[{PLUGIN_ID}] 私聊模式运行出错: {e}", exc_info=True)
        
        # 创建后台任务启动对应模式
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(run_background())
        except RuntimeError:
            asyncio.create_task(run_background())
        
    except Exception as e:
        logger.error(f"[{PLUGIN_ID}] 初始化Telegram机器人失败: {e}", exc_info=True)


# 导出主要接口
__all__ = [
    "get_bot",
    "get_group_bot",
    "config",
    "start_bot",
    "stop_bot",
    "start_group_bot",
    "stop_group_bot",
]

