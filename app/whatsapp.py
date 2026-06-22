"""
Отправка исходящих сообщений в WhatsApp через Twilio.
Twilio лимитирует длину сообщения WhatsApp в ~1600 символов — режем на части на всякий случай,
хотя наши ответы короткие по дизайну (см. правила формата в claude_client.py).
"""
from twilio.rest import Client
from app.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, MANAGER_WHATSAPP_NUMBERS

_twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

MAX_WHATSAPP_LEN = 1500


def _normalize_whatsapp_number(number: str) -> str:
    """
    Гарантирует префикс "whatsapp:" и убирает случайные пробелы — это частая
    причина ошибки Twilio 21910 (Invalid From and To pair), когда номер задан
    в переменных окружения без префикса или с лишним пробелом по краям.
    """
    number = (number or "").strip()
    if number and not number.startswith("whatsapp:"):
        number = f"whatsapp:{number}"
    return number


def send_whatsapp_message(to_number: str, body: str) -> None:
    """
    to_number — в формате "whatsapp:+77011234567" (с префиксом whatsapp:)
    """
    if _twilio_client is None:
        print(f"[DRY-RUN, нет Twilio credentials] -> {to_number}: {body}")
        return

    from_number = _normalize_whatsapp_number(TWILIO_WHATSAPP_FROM)
    to_number = _normalize_whatsapp_number(to_number)
    print(f"[whatsapp] send from={from_number!r} to={to_number!r}")

    chunks = [body[i:i + MAX_WHATSAPP_LEN] for i in range(0, len(body), MAX_WHATSAPP_LEN)] or [""]
    for chunk in chunks:
        _twilio_client.messages.create(
            from_=from_number,
            to=to_number,
            body=chunk,
        )


def notify_managers(text: str) -> None:
    """Уведомление диспетчеру/менеджеру о новом лиде или эскалации."""
    for manager_number in MANAGER_WHATSAPP_NUMBERS:
        send_whatsapp_message(manager_number, text)
