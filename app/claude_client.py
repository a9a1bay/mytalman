"""
Обёртка над Anthropic API. Ключевая идея:
- База знаний (knowledge_base.md) целиком идёт в system prompt — это и есть "мозг" бота.
- Два инструмента (tools) дают модели возможность СТРУКТУРИРОВАННО сообщить коду:
    1) save_lead_info — обновить данные лида (имя, площадь, тариф, запись на замер...)
    2) escalate_to_human — передать диалог менеджеру с указанием причины
  Без этого пришлось бы парсить свободный текст ответа регулярками — ненадёжно.
- Модель сама решает, когда вызвать инструмент, согласно правилам из раздела 8 и 9 базы знаний.
"""
import anthropic
from typing import List, Dict, Tuple, Optional

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS, KNOWLEDGE_BASE_PATH, BOT_NAME, COMPANY_NAME

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _load_knowledge_base() -> str:
    with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        return f.read()


_KNOWLEDGE_BASE_TEXT = _load_knowledge_base()


def _build_system_prompt() -> str:
    return f"""Ты — {BOT_NAME}, менеджер компании «{COMPANY_NAME}» (ремонт под ключ в Алматы),
отвечаешь клиентам в WhatsApp от первого лица как живой сотрудник.

Ниже — ПОЛНАЯ база знаний компании. Используй её как единственный источник правды
по ценам, услугам, условиям рассрочки, гарантии и сценарию диалога. Если ответа
в базе знаний нет — не придумывай, скажи, что уточнишь у менеджера, и вызови
инструмент escalate_to_human.

ВАЖНЫЕ ПРАВИЛА ФОРМАТА:
- Пиши как в мессенджере: 2-4 коротких предложения, без длинных списков, без markdown-разметки (никаких **, #, списков с тире в ответе клиенту).
- Не представляйся каждый раз заново — представляйся только в первом сообщении диалога.
- Если в истории уже есть имя, площадь, тариф клиента — не спрашивай повторно.
- Следуй сценарию диалога (раздел 8 базы): квалификация → ориентир по цене → запись на замер.
- Каждый раз, когда узнаёшь что-то новое о клиенте (имя, тип объекта, площадь, район, тариф, бюджет, интерес к рассрочке, дату/время записи на замер) — ОБЯЗАТЕЛЬНО вызови инструмент save_lead_info с этими полями, даже если просто продолжаешь диалог текстом.
- Если ситуация попадает под правила эскалации (раздел 9 базы: жалобы, юридические вопросы сверх базы, нестандартные объекты, финансовые споры, явная просьба человека, агрессия, вопрос без ответа в базе) — вызови escalate_to_human и в текстовом ответе клиенту мягко предупреди, что подключаешь менеджера (шаблон в разделе 9).

=== БАЗА ЗНАНИЙ КОМПАНИИ ===
{_KNOWLEDGE_BASE_TEXT}
=== КОНЕЦ БАЗЫ ЗНАНИЙ ===
"""


TOOLS = [
    {
        "name": "save_lead_info",
        "description": (
            "Сохранить или обновить данные о клиенте-лиде, полученные в ходе диалога. "
            "Вызывай каждый раз, когда узнаёшь новую информацию о клиенте — даже частично, "
            "не нужно ждать, пока соберутся все поля."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя клиента"},
                "object_type": {
                    "type": "string",
                    "enum": ["квартира", "коммерция", "локальный ремонт", "не определено"],
                    "description": "Тип объекта",
                },
                "area_m2": {"type": "string", "description": "Площадь объекта в м², если названа"},
                "district": {"type": "string", "description": "Район/адрес объекта в Алматы"},
                "tariff": {
                    "type": "string",
                    "enum": ["Эконом", "Стандарт", "Комфорт+", "не определён"],
                    "description": "Интересующий тариф",
                },
                "budget": {"type": "string", "description": "Названный клиентом бюджет, если есть"},
                "installment_interest": {
                    "type": "string",
                    "enum": ["Kaspi Kredit", "поэтапная оплата", "не уточнялось", "нет интереса"],
                    "description": "Интерес к рассрочке/оплате",
                },
                "booking_datetime": {
                    "type": "string",
                    "description": "Согласованная дата и время замера в свободном текстовом виде, если запись состоялась",
                },
                "comment": {"type": "string", "description": "Любой другой важный комментарий по лиду"},
            },
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Передать диалог человеку-менеджеру согласно правилам эскалации из базы знаний "
            "(раздел 9): жалобы, юридические вопросы сверх базы, нестандартные объекты, "
            "финансовые споры, явная просьба клиента, агрессия, вопрос без ответа в базе."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Короткое описание причины эскалации на русском языке",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["обычная", "высокая"],
                    "description": "Срочность — высокая для конфликтов/жалоб",
                },
            },
            "required": ["reason"],
        },
    },
]


MAX_TOOL_ITERATIONS = 5  # защита от бесконечного цикла, если модель будет постоянно звать инструменты


def get_bot_response(history: List[Dict[str, str]]) -> Tuple[str, Optional[Dict], Optional[Dict]]:
    """
    Отправляет историю диалога в Claude, возвращает:
    - текст ответа для отправки клиенту,
    - данные лида (dict | None), если модель вызвала save_lead_info,
    - данные эскалации (dict | None), если модель вызвала escalate_to_human.

    Модель может вызывать инструменты несколько раз подряд (например, сначала
    save_lead_info, а на следующем шаге ещё и escalate_to_human, и только потом
    дать финальный текст). Поэтому здесь не два фиксированных вызова, а цикл:
    на каждом шаге собираем все tool_use, выполняем их, отдаём результат модели
    и продолжаем, пока она не ответит обычным текстом без вызова инструментов
    (или пока не упрёмся в лимит итераций — на этот случай отдаём клиенту
    осмысленный текст вместо вечной заглушки "отвечу через минуту").
    """
    system_prompt = _build_system_prompt()
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    lead_patch: Optional[Dict] = None
    escalation: Optional[Dict] = None
    final_text = ""

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        text_parts = [block.text for block in response.content if block.type == "text"]
        final_text = "\n".join(text_parts).strip()

        print(
            f"[claude_client] iter={iteration} stop_reason={response.stop_reason} "
            f"tool_names={[tu.name for tu in tool_uses]} text_len={len(final_text)}"
        )

        if not tool_uses:
            # Модель ответила обычным текстом без инструментов — диалог на этом шаге закончен
            break

        tool_results = []
        for tu in tool_uses:
            if tu.name == "save_lead_info":
                # Если модель вызвала save_lead_info несколько раз за диалог — берём
                # последние значения, но не теряем уже накопленные поля из прошлых шагов
                lead_patch = {**(lead_patch or {}), **tu.input}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Данные лида сохранены.",
                })
            elif tu.name == "escalate_to_human":
                escalation = tu.input
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Менеджер уведомлён, подключится в ближайшее время.",
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Инструмент выполнен.",
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    if not final_text:
        # Сюда попадаем только если за все итерации модель ни разу не вернула текст
        # (например, упёрлись в MAX_TOOL_ITERATIONS) — отвечаем клиенту по-человечески,
        # а не оставляем его без ответа навсегда
        final_text = (
            "Уточняю детали по вашему вопросу, скоро вернусь с ответом. "
            "Если это срочно — просто напишите ещё раз, и я подключу менеджера."
        )

    return final_text, lead_patch, escalation
