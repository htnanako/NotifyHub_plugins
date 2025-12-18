"""
可复用的工具函数（私聊/群组模式共用）
"""
import asyncio
import logging
import re
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import config

logger = logging.getLogger(__name__)


def is_manager(chat_id: int) -> bool:
    """判断是否管理员"""
    try:
        manager_chatid = config.manager_chatid
        if not manager_chatid:
            return False
        return str(chat_id) == str(manager_chatid)
    except Exception as e:
        logger.error("检查管理员身份失败: %s", e, exc_info=True)
        return False


def contains_block_keywords(text: str) -> bool:
    """是否包含封禁关键词"""
    try:
        if not text:
            return False
        block_keywords = config.block_keywords
        if not block_keywords:
            return False
        lower = text.lower()
        return any(k.lower() in lower for k in block_keywords)
    except Exception as e:
        logger.error("检查关键词失败: %s", e, exc_info=True)
        return False


def delete_message_after_delay(message: Message, delay: int = 10):
    """延迟删除消息"""
    async def delete_after_delay():
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception as e:
            logger.error("自动删除消息失败: %s", e, exc_info=True)
    asyncio.create_task(delete_after_delay())


def extract_user_id_from_message(message_text: str) -> Optional[int]:
    """从消息文本提取用户ID"""
    try:
        pattern = r"用户ID:\s*(\d+)"
        match = re.search(pattern, message_text)
        if match:
            return int(match.group(1))
        return None
    except Exception as e:
        logger.error("提取用户ID失败: %s", e, exc_info=True)
        return None


def extract_user_name_from_message(message_text: str) -> Optional[str]:
    """从消息文本提取用户名/姓名"""
    try:
        name_pattern = r"姓名:\s*([^\n]+)"
        name_match = re.search(name_pattern, message_text)
        if name_match:
            name = name_match.group(1).strip()
            if name:
                return name
        
        username_pattern = r"用户名:\s*@?([^\n]+)"
        username_match = re.search(username_pattern, message_text)
        if username_match:
            username = username_match.group(1).strip()
            if username:
                return f"@{username}"
        return None
    except Exception as e:
        logger.error("提取用户名失败: %s", e, exc_info=True)
        return None


async def show_block_list(
    message: Message,
    page: int = 0,
    user_id: Optional[int] = None,
):
    """显示封禁列表或用户详情"""
    try:
        blocklist = config.get_blocklist()
        
        if user_id is not None:
            user_info = None
            for item in blocklist:
                if item["user_id"] == user_id:
                    user_info = item
                    break
            if not user_info:
                await message.reply_text("用户不存在于封禁列表中")
                return
            
            detail_msg = (
                "封禁用户详情\n\n"
                f"用户ID: {user_info['user_id']}\n"
                f"姓名: {user_info['name'] if user_info['name'] else '未设置'}\n\n"
                "点击「✅ 确认解除封禁」按钮即可解除封禁"
            )
            keyboard = [
                [
                    InlineKeyboardButton(
                        text="⬅️ 返回列表",
                        callback_data=f"block_list:page:{page}"
                    ),
                    InlineKeyboardButton(
                        text="✅ 确认解除封禁",
                        callback_data=f"unblock_user:{user_id}:page:{page}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ 关闭",
                        callback_data="close_block_list"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await message.edit_text(detail_msg, reply_markup=reply_markup)
            except Exception:
                await message.reply_text(detail_msg, reply_markup=reply_markup)
            return
        
        if not blocklist:
            help_msg = (
                "📋 封禁用户管理\n\n"
                "当前没有封禁用户\n\n"
                "操作方法：\n"
                "• 在用户消息中点击「🚫 封禁用户」按钮可封禁用户\n"
                "• 使用 /block_list 查看所有封禁用户"
            )
            await message.reply_text(help_msg)
            return
        
        items_per_page = 8
        total_pages = (len(blocklist) + items_per_page - 1) // items_per_page
        page = max(0, min(page, total_pages - 1))
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(blocklist))
        page_items = blocklist[start_idx:end_idx]
        
        help_msg = (
            "📋 封禁用户管理\n\n"
            f"共 {len(blocklist)} 个封禁用户（第 {page + 1}/{total_pages} 页）\n\n"
            "操作方法：\n"
            "• 点击下方用户按钮查看详情\n"
            "• 在详情页面可以解除封禁\n"
            "• 在用户消息中点击「🚫 封禁用户」按钮可封禁用户"
        )
        
        keyboard = []
        for item in page_items:
            user_name = item["name"] if item["name"] else f"用户 {item['user_id']}"
            keyboard.append([
                InlineKeyboardButton(
                    text=user_name,
                    callback_data=f"block_list:user:{item['user_id']}:page:{page}"
                )
            ])
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="⬅️ 上一页",
                        callback_data=f"block_list:page:{page - 1}"
                    )
                )
            if page < total_pages - 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="下一页 ➡️",
                        callback_data=f"block_list:page:{page + 1}"
                    )
                )
            if nav_buttons:
                keyboard.append(nav_buttons)
        keyboard.append([
            InlineKeyboardButton(
                text="❌ 关闭",
                callback_data="close_block_list"
            )
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await message.edit_text(help_msg, reply_markup=reply_markup)
        except Exception:
            await message.reply_text(help_msg, reply_markup=reply_markup)
    except Exception as e:
        logger.error("显示封禁列表失败: %s", e, exc_info=True)


async def handle_help_command(update, context):
    """管理员 /help"""
    try:
        chat_id = update.effective_chat.id
        if not is_manager(chat_id):
            return
        help_msg = (
            "可用命令：\n"
            "/start - 启动机器人\n"
            "/help - 显示帮助信息\n"
            "/status - 查看机器人状态\n"
            "/block_list - 查看封禁用户列表\n\n"
            "直接发送消息即可与管理员通信"
        )
        try:
            await update.message.reply_text(help_msg)
        except Exception as e:
            logger.warning("reply_text help 失败，改用 send_message: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text=help_msg,
            )
    except Exception as e:
        logger.error("处理 /help 命令失败: %s", e, exc_info=True)


async def handle_status_command(
    update,
    context,
    mode_label: str = "私聊",
):
    """管理员 /status"""
    try:
        chat_id = update.effective_chat.id
        if not is_manager(chat_id):
            return
        status_msg = (
            f"机器人状态：运行中 ✓\n"
            f"你的用户ID: {chat_id}\n"
            f"管理员ID: {config.manager_chatid}"
        )
        if mode_label:
            status_msg += f"\n模式: {mode_label}"
        try:
            await update.message.reply_text(status_msg)
        except Exception as e:
            logger.warning("reply_text status 失败，改用 send_message: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text=status_msg,
            )
    except Exception as e:
        logger.error("处理 /status 命令失败: %s", e, exc_info=True)


async def handle_block_list_command(update, context):
    """管理员 /block_list"""
    try:
        chat_id = update.effective_chat.id
        if not is_manager(chat_id):
            return
        try:
            await show_block_list(update.message, page=0)
        except Exception as e:
            logger.warning("显示封禁列表失败，尝试直接发送: %s", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text="封禁列表加载失败，请稍后重试。",
            )
    except Exception as e:
        logger.error("处理 /block_list 命令失败: %s", e, exc_info=True)


async def handle_callback_query_common(update, context):
    """处理内联回调（封禁/封禁列表/帮助），管理员限定"""
    try:
        query = update.callback_query
        if not query:
            return
        callback_data = query.data or ""
        
        # 管理员权限
        if not is_manager(query.from_user.id):
            await query.answer("此操作仅限管理员使用", show_alert=True)
            return
        
        # 处理不需要管理员权限的回调
        if callback_data == "already_blocked":
            await query.answer("该用户已被封禁", show_alert=True)
            return
        
        await query.answer()
        
        if callback_data.startswith("block_user:"):
            user_id_str = callback_data.split(":", 1)[1]
            try:
                user_id = int(user_id_str)
                if config.is_blocked(user_id):
                    await query.answer("该用户已被封禁", show_alert=True)
                    return
                user_name = ""
                original_message = query.message
                if original_message:
                    message_text = original_message.text or original_message.caption or ""
                    if message_text:
                        name_match = re.search(r'姓名:\s*([^\n]+)', message_text)
                        if name_match:
                            user_name = name_match.group(1).strip()
                        else:
                            username_match = re.search(r'用户名:\s*@?([^\n]+)', message_text)
                            if username_match:
                                user_name = f"@{username_match.group(1).strip()}"
                success = config.add_to_blocklist(user_id, user_name)
                if success:
                    await query.answer("✓ 用户已封禁", show_alert=True)
                    
                    # 更新按钮状态
                    try:
                        original_message = query.message
                        if original_message and original_message.reply_markup:
                            keyboard = original_message.reply_markup.inline_keyboard
                            new_keyboard = []
                            for row in keyboard:
                                new_row = []
                                for button in row:
                                    if button.callback_data == callback_data:
                                        new_row.append(
                                            InlineKeyboardButton(
                                                text="✅ 已封禁",
                                                callback_data="already_blocked"
                                            )
                                        )
                                    else:
                                        new_row.append(button)
                                new_keyboard.append(new_row)
                            
                            new_reply_markup = InlineKeyboardMarkup(new_keyboard)
                            await original_message.edit_reply_markup(reply_markup=new_reply_markup)
                    except Exception as e:
                        logger.error("更新按钮状态失败: %s", e, exc_info=True)
                else:
                    await query.answer("✗ 封禁失败，请稍后重试", show_alert=True)
            except ValueError:
                await query.answer("无效的用户ID", show_alert=True)
            except Exception as e:
                logger.error("处理封禁回调失败: %s", e, exc_info=True)
                await query.answer("处理失败，请稍后重试", show_alert=True)
        
        elif callback_data == "show_help":
            help_msg = (
                "可用命令：\n"
                "/start - 启动机器人\n"
                "/help - 显示帮助信息\n"
                "/status - 查看机器人状态\n"
                "/block_list - 查看封禁用户列表\n\n"
                "直接发送消息即可与管理员通信"
            )
            await query.message.reply_text(help_msg)
        
        elif callback_data.startswith("block_list:"):
            parts = callback_data.split(":")
            if len(parts) >= 3 and parts[1] == "page":
                page = int(parts[2])
                await show_block_list(query.message, page=page)
            elif len(parts) >= 5 and parts[1] == "user":
                user_id = int(parts[2])
                page = int(parts[4]) if len(parts) > 4 else 0
                await show_block_list(
                    query.message,
                    page=page,
                    user_id=user_id,
                )
        
        elif callback_data.startswith("unblock_user:"):
            parts = callback_data.split(":")
            if len(parts) >= 4:
                user_id = int(parts[1])
                page = int(parts[3])
                success = config.remove_from_blocklist(user_id)
                if success:
                    await query.answer("✓ 用户已解除封禁", show_alert=True)
                    await show_block_list(query.message, page=page)
                else:
                    await query.answer("✗ 解除封禁失败", show_alert=True)
        
        elif callback_data == "close_block_list":
            try:
                await query.message.delete()
            except Exception as e:
                logger.error("删除消息失败: %s", e, exc_info=True)
                await query.answer("删除消息失败", show_alert=True)
    except Exception as e:
        logger.error("处理回调查询失败: %s", e, exc_info=True)
