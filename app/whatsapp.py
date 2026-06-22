"""
Отправка исходящих сообщений в WhatsApp через Twilio.
Twilio лимитирует длину сообщения WhatsApp в ~1600 символов — режем на части на всякий случай,
хотя наши ответы короткие по дизайну (см. правила формата в claude_client.py).
"""
from twilio.rest import Client
from app.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, MANAGER_WHATSAPP_NUMBERS

_twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

MAX_WHATSAPP_LEN = 1500


def send_whatsapp_message(to_number: str, body: str) -> None:
    """
    to_number — в формате "whatsapp:+77011234567" (с префиксом whatsapp:)
    """
    if _twilio_client is None:
        print(f"[DRY-RUN, нет Twilio credentials] -> {to_number}: {body}")
        return

    chunks = [body[i:i + MAX_WHATSAPP_LEN] for i in range(0, len(body), MAX_WHATSAPP_LEN)] or [""]
    for chunk in chunks:
        _twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number,
            body=chunk,
        )


def notify_managers(text: str) -> None:
    """Уведомление диспетчеру/менеджеру о новом лиде или эскалации."""
    for manager_number in MANAGER_WHATSAPP_NUMBERS:
        send_whatsapp_message(manager_number, text)
