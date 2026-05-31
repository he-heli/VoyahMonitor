from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from voyah_monitor.telemetry import _first_match, _to_float


def _get_nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _format_phone(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_datetime(value: Any) -> str | None:
    if not value:
        return None
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
    return str(value)


def _humanize_recency(value: Any) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        delta = datetime.now(UTC) - dt.astimezone(UTC)
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "несколько секунд назад"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} минут назад"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} часов назад"
        days = seconds // 86400
        return f"{days} дней назад"
    except ValueError:
        return str(value)


def _live_sensors(*sources: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        if not source:
            continue
        live = source.get("liveSensors")
        if isinstance(live, dict):
            merged.update(live)
        sensors_data = _get_nested(source, "sensors", "sensorsData")
        if isinstance(sensors_data, dict):
            merged.update(sensors_data)
    return merged


def _table_fields(table: dict[str, Any], geo: dict[str, Any]) -> dict[str, Any]:
    live = _live_sensors(table, geo)
    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    owner = table.get("owner") if isinstance(table.get("owner"), dict) else {}

    return {
        "VIN": table.get("vin"),
        "Модель": car_model.get("displayName") or car_model.get("name"),
        "Модификация": car_model.get("modname"),
        "Гос. номер": table.get("licensePlate"),
        "Заряд тяговой батареи, %": live.get("batteryPercentage", geo.get("battery")),
        "Вольтаж 12V": live.get("12VBatteryVoltage"),
        "Пробег, км": live.get("odometer"),
        "Прогноз, км": live.get("remainsMileage"),
        "Актуальность по связи": _humanize_recency(table.get("lastSensorRequest")),
        "Владелец": owner.get("name") or owner.get("fullName"),
    }


def _detail_fields(detail: dict[str, Any], geo: dict[str, Any]) -> dict[str, Any]:
    live = _live_sensors(detail, geo)
    car_model = detail.get("carModel") if isinstance(detail.get("carModel"), dict) else {}

    return {
        "Топливо, %": live.get("fuelPercentage"),
        "Топливо, км": live.get("remainsMileageFuel"),
        "Батарея, %": live.get("batteryPercentage", geo.get("battery")),
        "Батарея, км": live.get("remainsMileage"),
        "Охлаждающая жидкость, °C": live.get("coolantTemp"),
        "Температура батареи, °C": live.get("batteryTemp"),
        "Напряжение АКБ, V": live.get("12VBatteryVoltage"),
        "Одометр, км": live.get("odometer"),
        "Гос. номер": detail.get("licensePlate"),
        "VIN": detail.get("vin"),
        "Модель": car_model.get("displayName") or car_model.get("name"),
        "Цвет": car_model.get("color"),
        "Модификация": car_model.get("modname"),
        "IMEI": detail.get("imei"),
        "Номер SIM в мультимедии": detail.get("imsiSim"),
        "Температура на улице, °C": live.get("outsideTemp"),
        "Широта": geo.get("lat"),
        "Долгота": geo.get("lon"),
        "Курс": geo.get("course"),
        "Обновлено": _humanize_recency(detail.get("lastSensorRequest")),
        "Обновлено (UTC)": _format_datetime(detail.get("lastSensorRequest")),
    }


def _access_fields(drivers_payload: Any) -> dict[str, Any]:
    if isinstance(drivers_payload, dict):
        owner = drivers_payload.get("owner")
        if isinstance(owner, dict):
            first = owner.get("firstName") or ""
            last = owner.get("lastName") or ""
            name = " ".join(part for part in (first, last) if part).strip()
            return {
                "Владелец": name or "Без имени",
                "Телефон владельца": _format_phone(owner.get("phone")),
            }
    if isinstance(drivers_payload, list) and drivers_payload:
        owner = drivers_payload[0]
        if isinstance(owner, dict):
            return {
                "Владелец": owner.get("name") or "Без имени",
                "Телефон владельца": _format_phone(owner.get("phone")),
            }
    return {}


def _maintenance_fields(maintenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "Следующее ТО": maintenance.get("nextMaintenanceText")
        or maintenance.get("nextMaintenance")
        or maintenance.get("next"),
        "Рекомендуемое ТО": maintenance.get("recommendedMaintenance")
        or maintenance.get("recommended"),
        "Заявки на ТО": maintenance.get("ordersCount"),
        "История ТО": maintenance.get("historyCount"),
        "Избранные дилеры": maintenance.get("favDealers"),
        "Авто обслуживается у": maintenance.get("serviceDealer"),
    }


def _render_section(title: str, fields: dict[str, Any]) -> str:
    lines = [f"=== {title} ==="]
    has_values = False
    for label, value in fields.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"{label}: {value}")
        else:
            lines.append(f"{label}: {value}")
        has_values = True
    if not has_values:
        lines.append("(нет данных)")
    return "\n".join(lines)


def format_vehicle_dashboard(item: dict[str, Any], index: int, total: int) -> str:
    table = item.get("table", {})
    geo = item.get("geo", {})
    detail = item.get("detail", {})
    drivers = item.get("drivers")
    maintenance = item.get("maintenance", {})

    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    title = car_model.get("displayName") or table.get("licensePlate") or table.get("vin") or f"Автомобиль {index}"

    sections = [f"--- [{index}/{total}] {title} ---"]
    sections.append(_render_section("Таблица (как на сайте)", _table_fields(table, geo)))
    sections.append("")
    sections.append(_render_section("Карточка автомобиля", _detail_fields(detail, geo)))

    access = _access_fields(drivers)
    sections.append("")
    sections.append(_render_section("Доступы", access if access else {"Примечание": item.get("drivers_error", "нет данных")}))

    sections.append("")
    sections.append(
        _render_section(
            "Техническое обслуживание",
            _maintenance_fields(maintenance) if maintenance else {"Примечание": item.get("maintenance_error", "нет данных")},
        )
    )

    if item.get("detail_error"):
        sections.append("")
        sections.append(f"Ошибка карточки: {item['detail_error']}")

    return "\n".join(sections)


def format_dashboard_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Автомобили не найдены."

    chunks = [format_vehicle_dashboard(item, index, len(items)) for index, item in enumerate(items, start=1)]
    return "\n\n".join(chunks)
