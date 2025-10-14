from notifyhub.controller.schedule import register_cron_job
from notifyhub.plugins.common import after_setup

from .event import reminder_job
from .config import list_configs


@after_setup("reminder", "reminder 插件初始化")
def start_reminder():
    if list_configs():
        register_cron_job(
            cron_expr="* * * * *",
            desc="reminder 定时提醒",
            func=reminder_job.run
        )