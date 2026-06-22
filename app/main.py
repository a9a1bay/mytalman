"""
Главная точка входа. Twilio шлёт POST-запрос на /webhook/whatsapp при каждом
входящем сообщении в WhatsApp. Мы:
  1. Проверяем подпись запроса (защита от поддельных вызовов).
  2. Сохраняем входящее сообщение в историю диалога клиента.
  3. Отдаём всю историю в Claude (claude_client.get_bot_response).
  4. Если Claude вызвал инструменты — обновляем лид / логируем эскалацию / уведомляем менеджера.
  5. Отправляем текстовый ответ клиенту через Twilio.
  6. Отвечаем Twilio пустым 200 OK (это вебхук, не нужен синхронный ответ в самом HTTP-response).
"""
from fastapi import FastAPI, Request, Response, HTTPException
from twilio.request_validator import RequestValidator

from app.config import TWILIO_AUTH_TOKEN, VALIDATE_TWILIO_SIGNATURE, BOT_NAME
from app import memory
from app.claude_client import get_bot_response
from app.whatsapp import send_whatsapp_message, notify_managers
from app.lead_logger import log_lead

app = FastAPI(title="Ремонт-бот WhatsApp")

_validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None


def _public_url(request: Request) -> str:
    """
    Восстанавливает публичный https-URL запроса.

    Railway (как и большинство облачных платформ) терминирует HTTPS на уровне
    прокси и передаёт внутрь контейнера обычный HTTP-запрос. Из-за этого
    request.url у Starlette содержит схему "http://", хотя Twilio подписывал
    запрос как "https://" — подпись не совпадает, и валидация падает с 403
    (в Twilio это видно как ошибка 11200 / "Forbidden").

    Чтобы починить это, берём настоящую схему и хост из заголовков
    X-Forwarded-Proto / X-Forwarded-Host, которые прокси Railway всегда
    проставляет, и пересобираем URL на их основе.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}{request.url.path}"


@app.get("/")
def health_check():
    return {"status": "ok", "bot": BOT_NAME}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    params = dict(form)

    if VALIDATE_TWILIO_SIGNATURE and _validator is not None:
        signature = request.headers.get("X-Twilio-Signature", "")
        url = _public_url(request)
        if not _validator.validate(url, params, signature):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    from_number = params.get("From", "")  # формат: "whatsapp:+77011234567"
    body = (params.get("Body") or "").strip()

    if not from_number or not body:
        return Response(status_code=204)

    # Тестовая команда сброса диалога — полезно при дебаге сценария
    if body.lower() in ("/reset", "сброс"):
        memory.reset_conversation(from_number)
        send_whatsapp_message(from_number, "Диалог сброшен. Начнём заново — здравствуйте! 👋")
        return Response(status_code=204)

    is_new_conversation = len(memory.get_history(from_number, limit=1)) == 0

    memory.add_message(from_number, "user", body)

    if memory.is_escalated(from_number):
        # Диалог уже передан человеку — бот не вмешивается, просто логируем сообщение
        return Response(status_code=204)

    history = memory.get_history(from_number)
    reply_text, lead_patch, escalation = get_bot_response(history)

    memory.add_message(from_number, "assistant", reply_text)
    send_whatsapp_message(from_number, reply_text)

    if lead_patch:
        updated = memory.update_lead_data(from_number, lead_patch)
        event_type = "booking" if lead_patch.get("booking_datetime") else "new_lead"
        log_lead(
            phone=from_number,
            event_type=event_type,
            name=updated.get("name"),
            object_type=updated.get("object_type"),
            area_m2=updated.get("area_m2"),
            district=updated.get("district"),
            tariff=updated.get("tariff"),
            budget=updated.get("budget"),
            installment_interest=updated.get("installment_interest"),
            booking_datetime=updated.get("booking_datetime"),
            comment=updated.get("comment"),
        )
        if event_type == "booking":
            notify_managers(
                f"📐 Новая запись на замер!\n"
                f"Клиент: {updated.get('name', '—')}\n"
                f"Телефон: {from_number.replace('whatsapp:', '')}\n"
                f"Объект: {updated.get('object_type', '—')}, {updated.get('area_m2', '—')} м²\n"
                f"Район: {updated.get('district', '—')}\n"
                f"Тариф: {updated.get('tariff', '—')}\n"
                f"Время замера: {updated.get('booking_datetime', '—')}"
            )

    if escalation:
        memory.set_escalated(from_number, True)
        log_lead(
            phone=from_number,
            event_type="escalation",
            comment=f"Причина: {escalation.get('reason')} | Срочность: {escalation.get('urgency', 'обычная')}",
        )
        notify_managers(
            f"🚨 Эскалация диалога ({escalation.get('urgency', 'обычная')} срочность)\n"
            f"Клиент: {from_number.replace('whatsapp:', '')}\n"
            f"Причина: {escalation.get('reason')}\n"
            f"Подключитесь в WhatsApp напрямую — бот приостановлен для этого клиента."
        )

    if is_new_conversation:
        log_lead(phone=from_number, event_type="new_lead", comment="Первое сообщение в диалоге")

    return Response(status_code=204)
