"""
Логирование лидов и эскалаций. Пишем в простой JSONL-файл —
его легко открыть, импортировать в Excel/Google Sheets или подключить к CRM позже.
Каждая строка — один структурированный объект лида, формат соответствует
разделу 10 базы знаний (см. knowledge_base.md).
"""
import json
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from app.config import LEADS_LOG_PATH


def log_lead(
    phone: str,
    event_type: str,  # "new_lead" | "booking" | "escalation"
    name: Optional[str] = None,
    object_type: Optional[str] = None,
    area_m2: Optional[str] = None,
    district: Optional[str] = None,
    tariff: Optional[str] = None,
    budget: Optional[str] = None,
    installment_interest: Optional[str] = None,
    booking_datetime: Optional[str] = None,
    source: str = "WhatsApp",
    comment: Optional[str] = None,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "phone": phone,
        "name": name,
        "object_type": object_type,
        "area_m2": area_m2,
        "district": district,
        "tariff": tariff,
        "budget": budget,
        "installment_interest": installment_interest,
        "booking_datetime": booking_datetime,
        "source": source,
        "comment": comment,
    }
    with open(LEADS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_all_leads() -> list:
    try:
        with open(LEADS_LOG_PATH, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
