
"""
Telegram Task Manager Bot
/add          — добавить задачу (бот спросит текст, приоритет, исполнителя, дедлайн)
/list         — поп-ап список открытых задач с кнопками
/tasks        — открытые задачи  |  /tasks high/medium/low — фильтр по приоритету
/alltasks     — все задачи одним сообщением
/mytasks      — мои задачи
/comment <id> <текст>  — добавить комментарий к задаче
/edit <id> <текст>     — изменить текст задачи
/todo <id>  /inprogress <id>  /done <id>  /cancel <id>  /del <id>
"""

import json
import asyncio
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ConversationHandler
)

# ─── Настройки ───────────────────────────────────────────────────────────────
TOKEN = "8626014332:AAE3XlAiPAkcXc911Bp430pdHljQiZOezHs"   # ← вставь токен от @BotFather
DATA_FILE = "tasks.json"
REMINDER_CHAT_ID = -1003893762530       # ← например: -1001234567890
AUTO_DELETE_SECONDS = 60
REMINDER_MINUTES = [60, 30, 15, 5, 0]

# ─── Состояния диалога ───────────────────────────────────────────────────────
WAITING_TASK_TEXT  = 1
WAITING_PRIORITY   = 2
WAITING_ASSIGNEE   = 3
WAITING_DEADLINE   = 4

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Статусы ─────────────────────────────────────────────────────────────────
STATUS_TODO       = "todo"
STATUS_INPROGRESS = "inprogress"
STATUS_DONE       = "done"
STATUS_CANCELLED  = "cancelled"

STATUS_EMOJI = {
    STATUS_TODO:       "📋 To Do",
    STATUS_INPROGRESS: "🔄 In Progress",
    STATUS_DONE:       "✅ Done",
    STATUS_CANCELLED:  "❌ Cancelled",
}

OPEN_STATUSES = {STATUS_TODO, STATUS_INPROGRESS}

# ─── Приоритеты ──────────────────────────────────────────────────────────────
PRIORITY_HIGH   = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW    = "low"

PRIORITY_EMOJI = {
    PRIORITY_HIGH:   "🔴 Высокий",
    PRIORITY_MEDIUM: "🟡 Средний",
    PRIORITY_LOW:    "🟢 Низкий",
}

# ─── Хранилище ───────────────────────────────────────────────────────────────
def load_tasks():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tasks": [], "next_id": 1}

def save_tasks(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_data():
    return load_tasks()

def add_task(text, author_id, author_name, deadline=None, priority=PRIORITY_MEDIUM, assignee=None):
    data = get_data()
    task = {
        "id": data["next_id"],
        "text": text,
        "status": STATUS_TODO,
        "priority": priority,
        "author_id": author_id,
        "author_name": author_name,
        "assignee": assignee,           # имя исполнителя (строка или None)
        "deadline": deadline,
        "comments": [],                 # список комментариев
        "reminders_sent": [],
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "updated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    data["tasks"].append(task)
    data["next_id"] += 1
    save_tasks(data)
    return task

def update_task_status(task_id, new_status):
    data = get_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["status"] = new_status
            task["updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            save_tasks(data)
            return task
    return None

def delete_task(task_id):
    data = get_data()
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    if len(data["tasks"]) < before:
        save_tasks(data)
        return True
    return False

def find_task(task_id):
    for task in get_data()["tasks"]:
        if task["id"] == task_id:
            return task
    return None

def parse_deadline(text):
    for fmt in ["%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m.%Y", "%d.%m.%y"]:
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if fmt in ["%d.%m.%Y", "%d.%m.%y"]:
                dt = dt.replace(hour=23, minute=59)
            return dt
        except ValueError:
            continue
    return None

def format_deadline(task):
    if not task.get("deadline"):
        return ""
    try:
        dt = datetime.strptime(task["deadline"], "%d.%m.%Y %H:%M")
        diff = dt - datetime.now()
        if task["status"] in OPEN_STATUSES:
            if diff.total_seconds() < 0:
                return f"\n  ⚠️ *Дедлайн просрочен!* {task['deadline']}"
            elif diff.total_seconds() < 3600:
                mins = int(diff.total_seconds() / 60)
                return f"\n  🔥 *Дедлайн через {mins} мин!* {task['deadline']}"
            else:
                return f"\n  ⏰ Дедлайн: {task['deadline']}"
        else:
            return f"\n  ⏰ Дедлайн был: {task['deadline']}"
    except Exception:
        return f"\n  ⏰ Дедлайн: {task['deadline']}"

def format_task(task):
    status_label   = STATUS_EMOJI.get(task["status"], task["status"])
    priority_label = PRIORITY_EMOJI.get(task.get("priority", PRIORITY_MEDIUM), "")
    assignee_line  = f"\n  🎯 Исполнитель: {task['assignee']}" if task.get("assignee") else ""
    comments_line  = ""
    if task.get("comments"):
        last = task["comments"][-1]
        comments_line = f"\n  💬 {last['author']}: {last['text']}"
        if len(task["comments"]) > 1:
            comments_line += f" _(+{len(task['comments'])-1})_"
    return (
        f"{priority_label} *#{task['id']}* — {task['text']}\n"
        f"  {status_label} | 👤 {task['author_name']}"
        f"{assignee_line}\n"
        f"  🕐 {task['created_at']} | обновлено: {task['updated_at']}"
        f"{format_deadline(task)}"
        f"{comments_line}"
    )

# ─── Авто-удаление ───────────────────────────────────────────────────────────
async def safe_delete(msg):
    try:
        await msg.delete()
    except Exception:
        pass

async def auto_delete_later(msg, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    await safe_delete(msg)

async def send_auto(chat, *args, **kwargs):
    msg = await chat.send_message(*args, **kwargs)
    asyncio.ensure_future(auto_delete_later(msg))
    return msg

# ─── Клавиатуры ──────────────────────────────────────────────────────────────
def task_keyboard(task_id, current_status):
    buttons = []
    if current_status != STATUS_TODO:
        buttons.append(InlineKeyboardButton("📋 To Do", callback_data=f"todo:{task_id}"))
    if current_status != STATUS_INPROGRESS:
        buttons.append(InlineKeyboardButton("🔄 In Progress", callback_data=f"inprogress:{task_id}"))
    if current_status != STATUS_DONE:
        buttons.append(InlineKeyboardButton("✅ Done", callback_data=f"done:{task_id}"))
    if current_status != STATUS_CANCELLED:
        buttons.append(InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{task_id}"))
    buttons.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{task_id}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)

def priority_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 Высокий",  callback_data="priority:high"),
        InlineKeyboardButton("🟡 Средний",  callback_data="priority:medium"),
        InlineKeyboardButton("🟢 Низкий",   callback_data="priority:low"),
    ]])

def assignee_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Пропустить", callback_data="assignee:skip")
    ]])

def deadline_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Пропустить (без дедлайна)", callback_data="deadline:skip")
    ]])

def list_item_keyboard(task_id, current_status):
    row = []
    if current_status != STATUS_DONE:
        row.append(InlineKeyboardButton("✅ Готово", callback_data=f"list_done:{task_id}"))
    if current_status != STATUS_INPROGRESS:
        row.append(InlineKeyboardButton("🔄 В работу", callback_data=f"list_inp:{task_id}"))
    if current_status != STATUS_CANCELLED:
        row.append(InlineKeyboardButton("❌ Отмена", callback_data=f"list_cancel:{task_id}"))
    return InlineKeyboardMarkup([row]) if row else None

# ─── ПОП-АП СПИСОК ───────────────────────────────────────────────────────────
def format_list_item(task):
    status   = STATUS_EMOJI.get(task["status"], task["status"])
    priority = PRIORITY_EMOJI.get(task.get("priority", PRIORITY_MEDIUM), "")
    dl = f"  ⏰ {task['deadline']}" if task.get("deadline") else ""
    assignee = f"  🎯 {task['assignee']}" if task.get("assignee") else ""
    return (
        f"{priority} {status} *#{task['id']}* — {task['text']}\n"
        f"  👤 {task['author_name']}{assignee}{dl}"
    )

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    data = get_data()
    open_tasks = [t for t in data["tasks"] if t["status"] in OPEN_STATUSES]
    if not open_tasks:
        await send_auto(update.effective_chat, "🎉 Нет открытых задач!")
        return
    header = await update.effective_chat.send_message(
        f"📋 *Открытые задачи: {len(open_tasks)}*\n_Нажми кнопку чтобы изменить статус_",
        parse_mode="Markdown"
    )
    asyncio.ensure_future(auto_delete_later(header, 120))
    # Сортируем по приоритету: высокий → средний → низкий
    priority_order = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
    open_tasks.sort(key=lambda t: priority_order.get(t.get("priority", PRIORITY_MEDIUM), 1))
    for task in open_tasks:
        kb = list_item_keyboard(task["id"], task["status"])
        msg = await update.effective_chat.send_message(
            format_list_item(task), parse_mode="Markdown", reply_markup=kb
        )
        asyncio.ensure_future(auto_delete_later(msg, 120))

# ─── Напоминания ─────────────────────────────────────────────────────────────
async def deadline_checker(app):
    while True:
        await asyncio.sleep(60)
        if not REMINDER_CHAT_ID:
            continue
        try:
            data = get_data()
            now = datetime.now()
            changed = False
            for task in data["tasks"]:
                if task["status"] not in OPEN_STATUSES or not task.get("deadline"):
                    continue
                try:
                    dl = datetime.strptime(task["deadline"], "%d.%m.%Y %H:%M")
                except Exception:
                    continue
                for mins in REMINDER_MINUTES:
                    if mins in task.get("reminders_sent", []):
                        continue
                    trigger = dl - timedelta(minutes=mins)
                    if trigger <= now < trigger + timedelta(minutes=2):
                        text = f"⏰ *До дедлайна {mins} минут!*\n\n{format_task(task)}"
                        try:
                            await app.bot.send_message(REMINDER_CHAT_ID, text, parse_mode="Markdown")
                            task.setdefault("reminders_sent", []).append(mins)
                            changed = True
                        except Exception as e:
                            logger.error(f"Ошибка напоминания: {e}")
            if changed:
                save_tasks(data)
        except Exception as e:
            logger.error(f"Ошибка deadline_checker: {e}")

# ─── ДИАЛОГ ДОБАВЛЕНИЯ ЗАДАЧИ ────────────────────────────────────────────────
async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    text = " ".join(ctx.args).strip()
    if text:
        ctx.user_data["pending_task_text"] = text
        ctx.user_data["pending_task_author_id"]   = update.effective_user.id
        ctx.user_data["pending_task_author_name"] = update.effective_user.full_name
    else:
        msg = await update.effective_chat.send_message(
            "📝 Напиши текст задачи:", reply_markup=ForceReply(selective=True)
        )
        asyncio.ensure_future(auto_delete_later(msg, 60))
        return WAITING_TASK_TEXT

    msg = await update.effective_chat.send_message(
        f"📝 Задача: *{text}*\n\nВыбери приоритет:",
        parse_mode="Markdown", reply_markup=priority_keyboard()
    )
    asyncio.ensure_future(auto_delete_later(msg, 60))
    return WAITING_PRIORITY

async def received_task_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    text = update.message.text.strip()
    ctx.user_data["pending_task_text"]        = text
    ctx.user_data["pending_task_author_id"]   = update.effective_user.id
    ctx.user_data["pending_task_author_name"] = update.effective_user.full_name
    msg = await update.effective_chat.send_message(
        f"📝 Задача: *{text}*\n\nВыбери приоритет:",
        parse_mode="Markdown", reply_markup=priority_keyboard()
    )
    asyncio.ensure_future(auto_delete_later(msg, 60))
    return WAITING_PRIORITY

async def priority_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    priority = query.data.split(":")[1]
    ctx.user_data["pending_priority"] = priority
    await query.edit_message_text(
        f"📝 *{ctx.user_data['pending_task_text']}*\n"
        f"Приоритет: {PRIORITY_EMOJI[priority]}\n\n"
        "👤 Укажи исполнителя (имя или @username)\nИли нажми пропустить:",
        parse_mode="Markdown", reply_markup=assignee_keyboard()
    )
    return WAITING_ASSIGNEE

async def received_assignee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    ctx.user_data["pending_assignee"] = update.message.text.strip()
    msg = await update.effective_chat.send_message(
        f"👤 Исполнитель: *{ctx.user_data['pending_assignee']}*\n\n"
        "⏰ Укажи дедлайн `дд.мм.гггг чч:мм`\nИли нажми пропустить:",
        parse_mode="Markdown", reply_markup=deadline_keyboard()
    )
    asyncio.ensure_future(auto_delete_later(msg, 60))
    return WAITING_DEADLINE

async def assignee_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "assignee:skip":
        ctx.user_data["pending_assignee"] = None
        await query.edit_message_text(
            "⏰ Укажи дедлайн `дд.мм.гггг чч:мм`\nИли нажми пропустить:",
            parse_mode="Markdown", reply_markup=deadline_keyboard()
        )
        return WAITING_DEADLINE

async def received_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    dt = parse_deadline(update.message.text.strip())
    if not dt:
        msg = await update.effective_chat.send_message(
            "❗ Неверный формат. Попробуй: `дд.мм.гггг чч:мм`\nИли нажми пропустить:",
            parse_mode="Markdown", reply_markup=deadline_keyboard()
        )
        asyncio.ensure_future(auto_delete_later(msg, 60))
        return WAITING_DEADLINE
    task = add_task(
        ctx.user_data["pending_task_text"],
        ctx.user_data["pending_task_author_id"],
        ctx.user_data["pending_task_author_name"],
        dt.strftime("%d.%m.%Y %H:%M"),
        ctx.user_data.get("pending_priority", PRIORITY_MEDIUM),
        ctx.user_data.get("pending_assignee"),
    )
    kb = task_keyboard(task["id"], task["status"])
    await send_auto(update.effective_chat,
        f"✅ *Задача #{task['id']} добавлена*\n\n{format_task(task)}",
        parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END

async def deadline_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "deadline:skip":
        task = add_task(
            ctx.user_data.get("pending_task_text", ""),
            ctx.user_data.get("pending_task_author_id", query.from_user.id),
            ctx.user_data.get("pending_task_author_name", query.from_user.full_name),
            None,
            ctx.user_data.get("pending_priority", PRIORITY_MEDIUM),
            ctx.user_data.get("pending_assignee"),
        )
        await query.edit_message_text(
            f"✅ *Задача #{task['id']} добавлена*\n\n{format_task(task)}",
            parse_mode="Markdown",
            reply_markup=task_keyboard(task["id"], task["status"])
        )
        asyncio.ensure_future(auto_delete_later(query.message, AUTO_DELETE_SECONDS))
        return ConversationHandler.END

async def cancel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    await send_auto(update.effective_chat, "❌ Добавление задачи отменено.")
    return ConversationHandler.END

# ─── КОММЕНТАРИИ ─────────────────────────────────────────────────────────────
async def cmd_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    if len(ctx.args) < 2:
        await send_auto(update.effective_chat,
            "❗ Использование: `/comment 5 Текст комментария`", parse_mode="Markdown")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await send_auto(update.effective_chat, "❗ ID должен быть числом.")
        return
    comment_text = " ".join(ctx.args[1:]).strip()
    data = get_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task.setdefault("comments", []).append({
                "author": update.effective_user.full_name,
                "text": comment_text,
                "at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            })
            task["updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            save_tasks(data)
            # Показываем все комментарии
            lines = [f"💬 *Комментарии к задаче #{task_id}:*\n"]
            for c in task["comments"]:
                lines.append(f"👤 *{c['author']}* [{c['at']}]\n{c['text']}")
            await send_auto(update.effective_chat, "\n\n".join(lines), parse_mode="Markdown")
            return
    await send_auto(update.effective_chat, f"❗ Задача #{task_id} не найдена.")

# ─── РЕДАКТИРОВАНИЕ ──────────────────────────────────────────────────────────
async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    if len(ctx.args) < 2:
        await send_auto(update.effective_chat,
            "❗ Использование: `/edit 5 Новый текст задачи`", parse_mode="Markdown")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await send_auto(update.effective_chat, "❗ ID должен быть числом.")
        return
    new_text = " ".join(ctx.args[1:]).strip()
    data = get_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            if task["author_id"] != update.effective_user.id:
                await send_auto(update.effective_chat, "🚫 Редактировать может только автор.")
                return
            task["text"] = new_text
            task["updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            save_tasks(data)
            kb = task_keyboard(task["id"], task["status"])
            await send_auto(update.effective_chat,
                f"✏️ *Задача #{task_id} обновлена*\n\n{format_task(task)}",
                parse_mode="Markdown", reply_markup=kb)
            return
    await send_auto(update.effective_chat, f"❗ Задача #{task_id} не найдена.")

# ─── ОСТАЛЬНЫЕ КОМАНДЫ ───────────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 *Task Manager Bot*\n\n"
        "/add — добавить задачу\n"
        "/list — 📋 список задач с кнопками\n"
        "/tasks — открытые задачи\n"
        "/tasks high — только высокий приоритет\n"
        "/tasks medium — средний приоритет\n"
        "/tasks low — низкий приоритет\n"
        "/alltasks — все задачи\n"
        "/mytasks — мои задачи\n"
        "/comment <id> <текст> — комментарий\n"
        "/edit <id> <текст> — редактировать задачу\n"
        "/todo <id> — To Do\n"
        "/inprogress <id> — In Progress\n"
        "/done <id> — закрыть задачу\n"
        "/cancel <id> — отменить\n"
        "/del <id> — удалить задачу\n"
        "/help — эта справка"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    data = get_data()
    open_tasks = [t for t in data["tasks"] if t["status"] in OPEN_STATUSES]

    # Фильтр по приоритету
    filter_arg = ctx.args[0].lower() if ctx.args else None
    if filter_arg in (PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW):
        open_tasks = [t for t in open_tasks if t.get("priority") == filter_arg]
        label = PRIORITY_EMOJI[filter_arg]
    else:
        label = None

    if not open_tasks:
        await send_auto(update.effective_chat, "🎉 Нет открытых задач!")
        return

    title = f"📋 *{label} — задачи: {len(open_tasks)}*" if label else f"📋 *Открытые задачи: {len(open_tasks)}*"
    await send_auto(update.effective_chat, title, parse_mode="Markdown")

    priority_order = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}
    open_tasks.sort(key=lambda t: priority_order.get(t.get("priority", PRIORITY_MEDIUM), 1))

    for task in open_tasks:
        kb = task_keyboard(task["id"], task["status"])
        await send_auto(update.effective_chat, format_task(task), parse_mode="Markdown", reply_markup=kb)

async def cmd_alltasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    data = get_data()
    tasks = data["tasks"]
    if not tasks:
        await send_auto(update.effective_chat, "📭 Задач пока нет.")
        return
    lines = [f"📁 *Все задачи: {len(tasks)}*\n"]
    for task in tasks:
        status_label   = STATUS_EMOJI.get(task["status"], task["status"])
        priority_label = PRIORITY_EMOJI.get(task.get("priority", PRIORITY_MEDIUM), "")
        assignee = f"  🎯 {task['assignee']}" if task.get("assignee") else ""
        lines.append(
            f"{priority_label} {status_label}\n"
            f"  *#{task['id']}* {task['text']}\n"
            f"  👤 {task['author_name']}{assignee} · 🕐 {task['updated_at']}"
            f"{format_deadline(task)}"
        )
    await send_auto(update.effective_chat, "\n\n".join(lines), parse_mode="Markdown")

async def cmd_mytasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    user = update.effective_user
    data = get_data()
    my = [t for t in data["tasks"] if t["author_id"] == user.id and t["status"] in OPEN_STATUSES]
    if not my:
        await send_auto(update.effective_chat, "🎉 У тебя нет открытых задач!")
        return
    await send_auto(update.effective_chat,
        f"👤 *Твои открытые задачи: {len(my)}*", parse_mode="Markdown")
    for task in my:
        kb = task_keyboard(task["id"], task["status"])
        await send_auto(update.effective_chat, format_task(task), parse_mode="Markdown", reply_markup=kb)

async def _change_status(update, ctx, new_status):
    await safe_delete(update.message)
    if not ctx.args:
        await send_auto(update.effective_chat, f"❗ Укажи ID: /{new_status} 5")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await send_auto(update.effective_chat, "❗ ID должен быть числом.")
        return
    task = update_task_status(task_id, new_status)
    if not task:
        await send_auto(update.effective_chat, f"❗ Задача #{task_id} не найдена.")
        return
    kb = task_keyboard(task["id"], task["status"])
    await send_auto(update.effective_chat,
        f"{STATUS_EMOJI[new_status]}\n\n{format_task(task)}", parse_mode="Markdown", reply_markup=kb)

async def cmd_todo(update, ctx): await _change_status(update, ctx, STATUS_TODO)
async def cmd_inprogress(update, ctx): await _change_status(update, ctx, STATUS_INPROGRESS)
async def cmd_done(update, ctx): await _change_status(update, ctx, STATUS_DONE)
async def cmd_cancel_status(update, ctx): await _change_status(update, ctx, STATUS_CANCELLED)

async def cmd_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_delete(update.message)
    if not ctx.args:
        await send_auto(update.effective_chat, "❗ Укажи ID: /del 5")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await send_auto(update.effective_chat, "❗ ID должен быть числом.")
        return
    task = find_task(task_id)
    if not task:
        await send_auto(update.effective_chat, f"❗ Задача #{task_id} не найдена.")
        return
    if task["author_id"] != update.effective_user.id:
        await send_auto(update.effective_chat, "🚫 Удалить может только автор.")
        return
    delete_task(task_id)
    await send_auto(update.effective_chat, f"🗑 Задача #{task_id} удалена.")

# ─── CALLBACK HANDLER ────────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data.startswith("list_"):
        await query.answer()
        action, task_id = query.data.split(":")
        task_id = int(task_id)
        status_map = {
            "list_done": STATUS_DONE, "list_inp": STATUS_INPROGRESS,
            "list_cancel": STATUS_CANCELLED, "list_todo": STATUS_TODO,
        }
        new_status = status_map.get(action)
        if new_status:
            task = update_task_status(task_id, new_status)
            if task:
                kb = list_item_keyboard(task["id"], task["status"])
                await query.edit_message_text(
                    format_list_item(task), parse_mode="Markdown", reply_markup=kb)
        return

    if query.data.startswith("priority:"):
        await priority_callback(update, ctx)
        return

    if query.data.startswith("assignee:"):
        await assignee_callback(update, ctx)
        return

    if query.data.startswith("deadline:"):
        return

    await query.answer()
    action, task_id_str = query.data.split(":", 1)
    task_id = int(task_id_str)
    user = query.from_user

    if action == "del":
        task = find_task(task_id)
        if not task:
            await query.edit_message_text("❗ Задача не найдена.")
            return
        if task["author_id"] != user.id:
            await query.answer("🚫 Удалить может только автор.", show_alert=True)
            return
        delete_task(task_id)
        await query.edit_message_text(f"🗑 Задача #{task_id} удалена.")
        return

    status_map = {"todo": STATUS_TODO, "inprogress": STATUS_INPROGRESS,
                  "done": STATUS_DONE, "cancel": STATUS_CANCELLED}
    new_status = status_map.get(action)
    if not new_status:
        return
    task = update_task_status(task_id, new_status)
    if not task:
        await query.edit_message_text("❗ Задача не найдена.")
        return
    kb = task_keyboard(task["id"], task["status"])
    await query.edit_message_text(format_task(task), parse_mode="Markdown", reply_markup=kb)

# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────
async def post_init(app):
    asyncio.ensure_future(deadline_checker(app))
    logger.info("Планировщик дедлайнов запущен.")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            WAITING_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_task_text)],
            WAITING_PRIORITY:  [CallbackQueryHandler(priority_callback, pattern="^priority:")],
            WAITING_ASSIGNEE:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_assignee),
                CallbackQueryHandler(assignee_callback, pattern="^assignee:"),
            ],
            WAITING_DEADLINE:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_deadline),
                CallbackQueryHandler(deadline_callback, pattern="^deadline:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
        per_user=True,
        per_chat=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",      cmd_help))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("list",       cmd_list))
    app.add_handler(CommandHandler("tasks",      cmd_tasks))
    app.add_handler(CommandHandler("alltasks",   cmd_alltasks))
    app.add_handler(CommandHandler("mytasks",    cmd_mytasks))
    app.add_handler(CommandHandler("comment",    cmd_comment))
    app.add_handler(CommandHandler("edit",       cmd_edit))
    app.add_handler(CommandHandler("todo",       cmd_todo))
    app.add_handler(CommandHandler("inprogress", cmd_inprogress))
    app.add_handler(CommandHandler("done",       cmd_done))
    app.add_handler(CommandHandler("cancel",     cmd_cancel_status))
    app.add_handler(CommandHandler("del",        cmd_del))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()