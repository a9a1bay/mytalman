"""
Конфигурация бота. Все секреты читаются из переменных окружения.
Локально — из .env файла (см. .env.example), на Railway — из Variables в дашборде.
"""
import os
from pathlib import Path

# === Anthropic (Claude) ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))

# === Twilio (WhatsApp) ===
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
# Номер отправителя в формате "whatsapp:+14155238886" (sandbox) или ваш купленный номер
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# === Безопасность вебхука ===
# Если задан — проверяем подпись запроса Twilio (рекомендуется в проде)
VALIDATE_TWILIO_SIGNATURE = os.getenv("VALIDATE_TWILIO_SIGNATURE", "true").lower() == "true"

# === Эскалация / уведомления диспетчеру ===
# Номер(а) менеджера в WhatsApp для уведомлений о новых лидах и эскалациях, через запятую
MANAGER_WHATSAPP_NUMBERS = [
    n.strip() for n in os.getenv("MANAGER_WHATSAPP_NUMBERS", "").split(",") if n.strip()
]

# === Хранилище диалогов и лидов ===
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CONVERSATIONS_DB_PATH = str(DATA_DIR / "conversations.sqlite3")
LEADS_LOG_PATH = str(DATA_DIR / "leads.jsonl")

# === База знаний ===
KNOWLEDGE_BASE_PATH = BASE_DIR / "app" / "knowledge" / "knowledge_base.md"

# === Прочее ===
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))  # сколько последних сообщений хранить в контексте
BOT_NAME = os.getenv("BOT_NAME", "Айгерим")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Solomon Partners")
