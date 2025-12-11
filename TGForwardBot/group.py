"""
Telegram 群组话题转发模式
"""
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, BadRequest

from .config import config
from .utils import (
    contains_block_keywords,
    delete_message_after_delay,
    handle_help_command,
    handle_status_command,
    handle_block_list_command,
    show_block_list,
    is_manager,
    handle_callback_query_common,
)

logger = logging.getLogger(__name__)

PLUGIN_ID = "TGForwardBot"


class TGGroupBot:
    """群组话题双向转发机器人"""
    
    def __init__(self):
        self.application: Optional[Application] = None
        self.bot: Optional[Bot] = None
        self.group_chatid: Optional[int] = None
        self._running = False
        
        # user_id -> message_thread_id
        self._user_topic_map: Dict[int, int] = {}
        # message_thread_id -> user_id
        self._topic_user_map: Dict[int, int] = {}
        self._topic_map_file: Optional[Path] = None
    
    async def initialize(self) -> bool:
        """初始化群组模式机器人"""
        try:
            if not config.is_group_mode_valid():
                logger.error(f"[{PLUGIN_ID}] 群组模式配置无效，无法启动机器人")
                return False
            
            self.group_chatid = int(config.group_chatid)
            proxy_url = config.proxy
            
            builder = Application.builder().token(config.bot_token)
            if proxy_url:
                request = HTTPXRequest(proxy=proxy_url)
                builder = builder.request(request)
            
            self.application = builder.build()
            self.bot = self.application.bot
            
            self._init_topic_store()
            self._load_topic_map()
            self._register_handlers()
            return True
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 群组模式初始化失败: {e}", exc_info=True)
            return False
    
    def _init_topic_store(self):
        """初始化话题映射存储路径"""
        try:
            conf_dir = config.conf_dir
            if not conf_dir:
                workdir = Path.cwd()
                conf_dir = workdir / "conf" / PLUGIN_ID
                conf_dir.mkdir(parents=True, exist_ok=True)
            self._topic_map_file = Path(conf_dir) / "group_topics.json"
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 初始化话题存储失败: {e}", exc_info=True)
            self._topic_map_file = None
    
    def _load_topic_map(self):
        """从文件加载话题映射"""
        if not self._topic_map_file or not self._topic_map_file.exists():
            self._user_topic_map = {}
            self._topic_user_map = {}
            return
        try:
            with open(self._topic_map_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._user_topic_map = {int(k): int(v) for k, v in data.get("user_to_topic", {}).items()}
                    self._topic_user_map = {int(k): int(v) for k, v in data.get("topic_to_user", {}).items()}
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 加载话题映射失败: {e}", exc_info=True)
            self._user_topic_map = {}
            self._topic_user_map = {}
    
    def _save_topic_map(self):
        """保存话题映射到文件"""
        if not self._topic_map_file:
            return
        try:
            payload = {
                "user_to_topic": self._user_topic_map,
                "topic_to_user": self._topic_user_map,
            }
            with open(self._topic_map_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 保存话题映射失败: {e}", exc_info=True)
    
    def _register_handlers(self):
        """注册消息处理器"""
        if not self.application:
            return
        
        # /start 仅用于提示用户
        self.application.add_handler(
            CommandHandler("start", self._handle_start, filters=filters.ChatType.PRIVATE)
        )
        # 管理员命令（仅私聊可用）
        cmd_filter = filters.ChatType.PRIVATE
        self.application.add_handler(
            CommandHandler("help", self._handle_help, filters=cmd_filter)
        )
        self.application.add_handler(
            CommandHandler("status", self._handle_status, filters=cmd_filter)
        )
        self.application.add_handler(
            CommandHandler("block_list", self._handle_block_list, filters=cmd_filter)
        )
        
        # 私聊用户消息
        self.application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, self._handle_user_text)
        )
        
        media_filter = (
            filters.PHOTO
            | filters.Document.ALL
            | filters.VIDEO
            | filters.AUDIO
            | filters.VOICE
        )
        self.application.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & media_filter, self._handle_user_media)
        )
        
        # 群组内管理员回复（包含话题消息）
        group_filter = filters.Chat(self.group_chatid) & (filters.TEXT | media_filter)
        self.application.add_handler(
            MessageHandler(group_filter, self._handle_group_message)
        )
        
        # 内联回调（封禁/封禁列表）
        self.application.add_handler(
            CallbackQueryHandler(self._handle_callback_query)
        )
    
    def _is_manager(self, chat_id: int) -> bool:
        """
        检查是否是管理员
        
        Args:
            chat_id: 聊天ID
            
        Returns:
            bool: 是否是管理员
        """
        return is_manager(chat_id)
    
    def _contains_block_keywords(self, text: str) -> bool:
        """
        检查文本是否包含封禁关键词
        
        Args:
            text: 要检查的文本
            
        Returns:
            bool: 如果包含关键词返回True，否则返回False
        """
        return contains_block_keywords(text)
    
    def _delete_message_after_delay(self, message: Message, delay: int = 10):
        """
        在指定延迟后删除消息
        
        Args:
            message: 要删除的消息对象
            delay: 延迟时间（秒），默认10秒
        """
        delete_message_after_delay(message, delay=delay)
    
    def _user_display_name(self, user) -> str:
        """生成用户展示名称"""
        if not user:
            return "未知用户"
        parts = []
        if user.first_name:
            parts.append(user.first_name)
        if user.last_name:
            parts.append(user.last_name)
        if parts:
            return " ".join(parts)
        if user.username:
            return f"@{user.username}"
        return f"用户 {user.id}"
    
    def _build_user_info(self, chat_id: int, user) -> str:
        """构造用户信息段落"""
        info = "\n\n" + "=" * 25 + f"\n用户ID: {chat_id}"
        if user and (user.first_name or user.last_name):
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            info += f"\n姓名: {full_name}"
        if user and user.username:
            info += f"\n用户名: @{user.username}"
        return info
    
    async def _ensure_topic(self, user) -> Optional[int]:
        """获取或创建对应用户的话题，并返回 message_thread_id"""
        try:
            user_id = user.id
            if user_id in self._user_topic_map:
                return self._user_topic_map[user_id]
            
            topic_title = self._user_display_name(user)[:50]  # 避免超长
            result = await self.bot.create_forum_topic(
                chat_id=self.group_chatid,
                name=topic_title
            )
            thread_id = result.message_thread_id
            self._user_topic_map[user_id] = thread_id
            self._topic_user_map[thread_id] = user_id
            self._save_topic_map()
            return thread_id
        except TelegramError as e:
            logger.error(f"[{PLUGIN_ID}] 创建话题失败: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 创建话题时发生未知错误: {e}", exc_info=True)
            return None
    
    async def _handle_user_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理私聊文本消息并转发到群组话题"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            text = update.message.text
            
            if config.is_blocked(chat_id) or self._contains_block_keywords(text):
                return
            
            thread_id = await self._ensure_topic(user)
            if not thread_id:
                await update.message.reply_text("创建话题失败，请稍后重试。")
                return
            
            user_info = self._build_user_info(chat_id, user)
            forward_text = text + user_info
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="🚫 封禁用户", callback_data=f"block_user:{chat_id}")]
            ])
            
            await self.bot.send_message(
                chat_id=self.group_chatid,
                text=forward_text,
                message_thread_id=thread_id,
                reply_markup=keyboard
            )
            
            confirm = await update.message.reply_text("消息已转发至管理员话题。(10s后自动销毁)")
            self._delete_message_after_delay(confirm, delay=10)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理用户文本失败: {e}", exc_info=True)
            try:
                await update.message.reply_text("处理消息时发生错误，请稍后再试。")
            except:
                pass
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """管理员 /help"""
        logger.info(f"[{PLUGIN_ID}] 处理 /help 命令")
        await handle_help_command(update, context)
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """管理员 /status"""
        await handle_status_command(update, context, mode_label="群组话题")
    
    async def _handle_block_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """管理员 /block_list"""
        await handle_block_list_command(update, context)
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            
            welcome_msg = (
                f"欢迎使用 Telegram 双向私聊机器人！\n\n"
                f"你的用户ID: {chat_id}\n"
                f"用户名: @{user.username if user.username else '未设置'}\n\n"
                f"直接发送消息即可与管理员通信"
            )
            
            reply_markup = None
            if is_manager(chat_id):
                keyboard = [
                    [InlineKeyboardButton(
                        text="📖 查看帮助",
                        callback_data="show_help"
                    )]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
            
            if not self._is_manager(chat_id):
                await self._notify_manager(f"新用户启动机器人:\n用户ID: {chat_id}\n用户名: {user.username or '未设置'}")
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理 /start 命令失败: {e}", exc_info=True)
    
    async def _handle_user_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理私聊媒体消息并转发到群组话题"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            caption = message.caption or ""
            if config.is_blocked(chat_id) or self._contains_block_keywords(caption):
                return
            
            thread_id = await self._ensure_topic(user)
            if not thread_id:
                await message.reply_text("创建话题失败，请稍后重试。")
                return
            
            user_info = self._build_user_info(chat_id, user)
            caption_to_send = caption + user_info if caption else f"收到媒体消息{user_info}"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="🚫 封禁用户", callback_data=f"block_user:{chat_id}")]
            ])
            
            await self._forward_media_to_group(
                message=message,
                caption=caption_to_send,
                thread_id=thread_id,
                reply_markup=keyboard
            )
            
            confirm = await message.reply_text("媒体已转发至管理员话题。(10s后自动销毁)")
            self._delete_message_after_delay(confirm, delay=10)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理用户媒体失败: {e}", exc_info=True)
    
    async def _forward_media_to_group(
        self,
        message: Message,
        caption: str,
        thread_id: int,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ):
        """将媒体转发到群组话题"""
        try:
            if message.photo:
                await self.bot.send_photo(
                    chat_id=self.group_chatid,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    message_thread_id=thread_id,
                    reply_markup=reply_markup
                )
            elif message.document:
                await self.bot.send_document(
                    chat_id=self.group_chatid,
                    document=message.document.file_id,
                    caption=caption,
                    message_thread_id=thread_id,
                    reply_markup=reply_markup
                )
            elif message.video:
                await self.bot.send_video(
                    chat_id=self.group_chatid,
                    video=message.video.file_id,
                    caption=caption,
                    message_thread_id=thread_id,
                    reply_markup=reply_markup
                )
            elif message.audio:
                await self.bot.send_audio(
                    chat_id=self.group_chatid,
                    audio=message.audio.file_id,
                    caption=caption,
                    message_thread_id=thread_id,
                    reply_markup=reply_markup
                )
            elif message.voice:
                await self.bot.send_voice(
                    chat_id=self.group_chatid,
                    voice=message.voice.file_id,
                    caption=caption,
                    message_thread_id=thread_id,
                    reply_markup=reply_markup
                )
        except BadRequest as e:
            # 部分媒体可能触发隐私限制，直接记录错误
            logger.error(f"[{PLUGIN_ID}] 发送媒体到群组失败: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 发送媒体到群组出现异常: {e}", exc_info=True)
    
    async def _handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理群组话题中的管理员消息并转发给对应用户"""
        try:
            message = update.message
            if not message or message.chat_id != self.group_chatid:
                return
            
            # 群内命令在 CommandHandler 中处理，这里再次防止命令被转发
            if message.text and message.text.startswith("/"):
                return
            
            thread_id = message.message_thread_id
            if not thread_id:
                return  # 不是话题消息，忽略
            
            user_id = self._topic_user_map.get(thread_id)
            if not user_id:
                return  # 非机器人创建的话题
            
            # 管理员 -> 用户
            text = message.text or message.caption or ""
            sent = False
            if message.photo or message.document or message.video or message.audio or message.voice:
                sent = await self._forward_media_to_user(message, user_id, caption=text if text else None)
            elif text:
                sent = await self.send_message(user_id, text)
            
            if not sent:
                await message.reply_text("转发失败，用户可能已屏蔽机器人。")
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理群组消息失败: {e}", exc_info=True)
    
    async def _forward_media_to_user(
        self,
        message: Message,
        user_id: int,
        caption: Optional[str] = None
    ) -> bool:
        """将群组中的媒体转发给用户"""
        try:
            if message.photo:
                await self.bot.send_photo(chat_id=user_id, photo=message.photo[-1].file_id, caption=caption)
                return True
            if message.document:
                await self.bot.send_document(chat_id=user_id, document=message.document.file_id, caption=caption)
                return True
            if message.video:
                await self.bot.send_video(chat_id=user_id, video=message.video.file_id, caption=caption)
                return True
            if message.audio:
                await self.bot.send_audio(chat_id=user_id, audio=message.audio.file_id, caption=caption)
                return True
            if message.voice:
                await self.bot.send_voice(chat_id=user_id, voice=message.voice.file_id, caption=caption)
                return True
            return False
        except TelegramError as e:
            logger.error(f"[{PLUGIN_ID}] 向用户转发媒体失败: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 向用户转发媒体出现未知错误: {e}", exc_info=True)
            return False
    
    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理内联键盘回调（封禁/封禁列表）"""
        await handle_callback_query_common(update, context)
    
    async def send_message(self, chat_id: int, message: str) -> bool:
        """发送文本消息到指定用户"""
        try:
            await self.bot.send_message(chat_id=chat_id, text=message)
            return True
        except TelegramError as e:
            logger.error(f"[{PLUGIN_ID}] 发送消息失败: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 发送消息出现未知错误: {e}", exc_info=True)
            return False
    
    async def start(self):
        """启动群组模式"""
        if self._running:
            return
        if not self.application:
            if not await self.initialize():
                return
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            self._running = True
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 群组模式启动失败: {e}", exc_info=True)
            self._running = False
            raise
    
    async def stop(self):
        """停止群组模式"""
        if not self._running:
            return
        try:
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            self._running = False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 群组模式停止失败: {e}", exc_info=True)


# 全局实例
group_bot_instance: Optional[TGGroupBot] = None


def get_group_bot() -> Optional[TGGroupBot]:
    """获取群组模式机器人实例"""
    return group_bot_instance


async def init_group_bot() -> bool:
    """初始化群组模式机器人实例"""
    global group_bot_instance
    if group_bot_instance is None:
        group_bot_instance = TGGroupBot()
    return await group_bot_instance.initialize()


async def start_group_bot():
    """启动群组模式机器人"""
    global group_bot_instance
    if group_bot_instance is None:
        group_bot_instance = TGGroupBot()
    await group_bot_instance.start()


async def stop_group_bot():
    """停止群组模式机器人"""
    global group_bot_instance
    if group_bot_instance:
        await group_bot_instance.stop()

