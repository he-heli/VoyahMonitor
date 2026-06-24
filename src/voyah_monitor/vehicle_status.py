from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    if len(digits) == 10:
        return f"+7 ({digits[0:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
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
        if seconds < 0:
            return "только что"
        if seconds < 60:
            return "несколько секунд назад"
        if seconds < 3600:
            minutes = max(1, seconds // 60)
            return f"{minutes} минут назад"
        if seconds < 86400:
            hours = max(1, seconds // 3600)
            return f"{hours} часов назад"
        days = max(1, seconds // 86400)
        return f"{days} дней назад"
    except ValueError:
        return str(value)


def _display_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _owner_from_drivers(drivers_payload: Any) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if isinstance(drivers_payload, list):
        entries = [item for item in drivers_payload if isinstance(item, dict)]
    elif isinstance(drivers_payload, dict):
        if isinstance(drivers_payload.get("owner"), dict):
            entries = [drivers_payload["owner"]]
        elif isinstance(drivers_payload.get("rows"), list):
            entries = [item for item in drivers_payload["rows"] if isinstance(item, dict)]

    owner = next((item for item in entries if item.get("kind") == "owner"), entries[0] if entries else None)
    if not owner:
        return {}

    first = (owner.get("firstName") or "").strip()
    last = (owner.get("lastName") or "").strip()
    name = " ".join(part for part in (first, last) if part).strip()
    if not name:
        name = "Без имени"

    return {
        "name": name,
        "phone": _format_phone(owner.get("phone")),
    }


def _on_off_label(value: Any, *, on_text: str = "Включено", off_text: str = "Отключено") -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return on_text if value else off_text
    try:
        return on_text if int(value) != 0 else off_text
    except (TypeError, ValueError):
        return str(value)


def _open_closed_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Закрыт" if value else "Открыт"
    try:
        return "Закрыт" if int(value) == 0 else "Открыт"
    except (TypeError, ValueError):
        return str(value)


def _lock_label(metrics: dict[str, Any], tbox: dict[str, Any]) -> str | None:
    if metrics.get("centralLockingStatus") is not None:
        return _open_closed_label(metrics.get("centralLockingStatus"))
    if tbox.get("isCentralLockingOn") is not None:
        return "Закрыт" if tbox.get("isCentralLockingOn") else "Открыт"
    return None


def _speed_label(value: Any) -> str | None:
    if value is None:
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return str(value)
    if speed <= 0:
        return "нет"
    return f"{speed:g}"


def _collect_metrics(
    table: dict[str, Any],
    detail: dict[str, Any],
    geo: dict[str, Any],
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    for source in (table, detail):
        live = source.get("liveSensors")
        if isinstance(live, dict):
            metrics.update(live)

        sensors = source.get("sensors")
        if isinstance(sensors, dict):
            sensors_data = sensors.get("sensorsData")
            if isinstance(sensors_data, dict):
                metrics.update(sensors_data)
            if sensors.get("battery") is not None:
                metrics["batteryPercentage"] = sensors.get("battery")
            if sensors.get("v12") is not None:
                metrics["12VBatteryVoltage"] = sensors.get("v12")
            if sensors.get("odometer") is not None:
                metrics["odometer"] = sensors.get("odometer")
            if sensors.get("remain") is not None:
                metrics["remainsMileage"] = sensors.get("remain")
            if sensors.get("lastSensorsRecieved"):
                metrics["lastSensorsRecieved"] = sensors.get("lastSensorsRecieved")

    if isinstance(tbox, dict):
        tbox_sensors = tbox.get("sensors")
        if isinstance(tbox_sensors, dict):
            sensors_data = tbox_sensors.get("sensorsData")
            if isinstance(sensors_data, dict):
                metrics.update(sensors_data)
            position = tbox_sensors.get("positionData")
            if isinstance(position, dict):
                if position.get("speed") is not None:
                    metrics["speed"] = position.get("speed")
                if position.get("lat") is not None:
                    metrics["latitude"] = position.get("lat")
                if position.get("lon") is not None:
                    metrics["longitude"] = position.get("lon")
                if position.get("course") is not None:
                    metrics["course"] = position.get("course")

    if geo.get("battery") is not None and metrics.get("batteryPercentage") is None:
        metrics["batteryPercentage"] = geo.get("battery")
    if geo.get("lat") is not None and metrics.get("latitude") is None:
        metrics["latitude"] = geo.get("lat")
    if geo.get("lon") is not None and metrics.get("longitude") is None:
        metrics["longitude"] = geo.get("lon")
    if geo.get("course") is not None and metrics.get("course") is None:
        metrics["course"] = geo.get("course")

    return metrics


def _status_chip(tbox: dict[str, Any] | None) -> str | None:
    if not isinstance(tbox, dict):
        return None
    sensors = tbox.get("sensors")
    if not isinstance(sensors, dict):
        return None
    chip = sensors.get("chip")
    if isinstance(chip, dict):
        return chip.get("title")
    return None


def _recency_from_sources(*sources: dict[str, Any], metrics: dict[str, Any]) -> str | None:
    for source in sources:
        value = source.get("lastSensorRequest") or source.get("lastSensorsRecieved")
        if value:
            return _humanize_recency(value)
    return _humanize_recency(metrics.get("lastSensorsRecieved"))


def _table_fields(
    table: dict[str, Any],
    geo: dict[str, Any],
    detail: dict[str, Any],
    drivers_payload: Any,
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _collect_metrics(table, detail, geo, tbox)
    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    owner = _owner_from_drivers(drivers_payload)

    return {
        "VIN": table.get("vin"),
        "Модель": car_model.get("displayName") or car_model.get("name"),
        "Модификация": car_model.get("modname"),
        "Гос. номер": table.get("licensePlate"),
        "Заряд тяговой батареи, %": metrics.get("batteryPercentage"),
        "Батарея 12V": metrics.get("12VBatteryVoltage"),
        "Скорость": _speed_label(metrics.get("speed")),
        "Пробег, км": metrics.get("odometer"),
        "Актуальность сенсоров": _recency_from_sources(table, detail, metrics=metrics),
        "Владелец": owner.get("name"),
    }


def _summary_fields(
    table: dict[str, Any],
    geo: dict[str, Any],
    detail: dict[str, Any],
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _collect_metrics(table, detail, geo, tbox)

    fields: dict[str, Any] = {
        "Статус": _status_chip(tbox),
        "Топливо, %": metrics.get("fuelPercentage"),
        "Топливо, км": metrics.get("remainsMileageFuel"),
        "Батарея, %": metrics.get("batteryPercentage"),
        "Батарея, км": metrics.get("remainsMileage"),
        "Охлаждающая жидкость, °C": metrics.get("coolantTemp"),
        "Температура батареи, °C": metrics.get("batteryTemp"),
        "Напряжение АКБ, V": metrics.get("12VBatteryVoltage"),
        "Одометр, км": metrics.get("odometer"),
        "SOH, %": metrics.get("soh"),
        "Обновлено": _recency_from_sources(table, detail, metrics=metrics),
    }
    return fields


def _about_car_fields(table: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    car_model = detail.get("carModel") if isinstance(detail.get("carModel"), dict) else {}
    if not car_model and isinstance(table.get("carModel"), dict):
        car_model = table["carModel"]

    return {
        "Гос. номер": detail.get("licensePlate") or table.get("licensePlate"),
        "VIN": detail.get("vin") or table.get("vin"),
        "Модель": car_model.get("displayName") or car_model.get("name"),
        "Цвет": car_model.get("color"),
        "Модификация": car_model.get("modname"),
        "IMEI": detail.get("imei") or table.get("imei"),
        "Номер SIM в мультимедии": detail.get("imsiSim") or table.get("imsiSim"),
    }


def _climate_fields(
    table: dict[str, Any],
    detail: dict[str, Any],
    geo: dict[str, Any],
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _collect_metrics(table, detail, geo, tbox)
    return {
        "На улице, °C": metrics.get("outsideTemp"),
        "В салоне, °C": metrics.get("inBoardTemp"),
        "Целевая температура, °C": metrics.get("climateTargetTemp"),
    }


def _location_sharing_label(table: dict[str, Any], detail: dict[str, Any]) -> str | None:
    value = table.get("locationStatus", detail.get("locationStatus"))
    return _on_off_label(value, on_text="да", off_text="нет")


def _location_fields(
    geo: dict[str, Any],
    table: dict[str, Any],
    detail: dict[str, Any],
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _collect_metrics(table, detail, geo, tbox)
    return {
        "Широта": metrics.get("latitude", geo.get("lat")),
        "Долгота": metrics.get("longitude", geo.get("lon")),
        "Курс": metrics.get("course", geo.get("course")),
        "Передача геопозиции": _location_sharing_label(table, detail),
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "да"}:
            return True
        if lowered in {"false", "0", "no", "off", "нет"}:
            return False
    return None


def _detect_is_charging(metrics: dict[str, Any], tbox: dict[str, Any] | None) -> bool | None:
    for key in ("isCharging", "charging", "chargeStatus", "chargingStatus"):
        if key in metrics:
            return _to_bool(metrics[key])
    if isinstance(tbox, dict):
        sensors = tbox.get("sensors")
        if isinstance(sensors, dict):
            chip = sensors.get("chip")
            if isinstance(chip, dict):
                title = chip.get("title")
                if isinstance(title, str):
                    lower = title.lower()
                    if any(token in lower for token in ("заряд", "заряж", "charging")):
                        return True
    return None


def dashboard_item_to_telemetry(item: dict[str, Any]) -> "VehicleTelemetry":
    from voyah_monitor.telemetry import VehicleTelemetry

    table = item.get("table") if isinstance(item.get("table"), dict) else {}
    geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    tbox = item.get("tbox") if isinstance(item.get("tbox"), dict) else None

    metrics = _collect_metrics(table, detail, geo, tbox)
    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    name = car_model.get("displayName") or car_model.get("name")

    speed = _to_float(metrics.get("speed"))
    if speed is not None and speed <= 0:
        speed = 0.0

    vin = table.get("vin") or detail.get("vin")
    vehicle_id = table.get("_id")

    return VehicleTelemetry(
        vehicle_id=str(vehicle_id) if vehicle_id is not None else None,
        vin=str(vin) if vin is not None else None,
        name=str(name) if name is not None else None,
        odometer_km=_to_float(metrics.get("odometer")),
        battery_percent=_to_float(metrics.get("batteryPercentage")),
        range_km=_to_float(metrics.get("remainsMileage")),
        speed_kmh=speed,
        latitude=_to_float(metrics.get("latitude", geo.get("lat"))),
        longitude=_to_float(metrics.get("longitude", geo.get("lon"))),
        course_deg=_to_float(metrics.get("course", geo.get("course"))),
        soh_percent=_to_float(metrics.get("soh")),
        v12_voltage=_to_float(metrics.get("12VBatteryVoltage")),
        is_online=_to_bool(tbox.get("isOnline")) if tbox else None,
        location_sharing=_to_bool(table.get("locationStatus", detail.get("locationStatus"))),
        status=_status_chip(tbox),
        is_charging=_detect_is_charging(metrics, tbox),
        raw=item,
    )


def _control_state_fields(tbox: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(tbox, dict):
        return {}

    metrics = _collect_metrics({}, {}, {}, tbox)
    preparation = tbox.get("preparation_script")
    heating_active = False
    if isinstance(preparation, dict):
        heating_active = bool(preparation.get("running"))

    wheel_heating = metrics.get("climateWheelHeatingStatus")
    seat_heating = any(
        metrics.get(key)
        for key in (
            "seatHeatingDriverStatus",
            "seatHeatingFPassStatus",
            "seatHeatingRLPassStatus",
            "seatHeatingRRPassStatus",
        )
    )

    cooling_active = (metrics.get("climateFanSpeed") or 0) > 0 or bool(metrics.get("airingStatus"))

    return {
        "Прогрев": _on_off_label(
            heating_active or wheel_heating or seat_heating,
            on_text="Включено",
            off_text="Отключено",
        ),
        "Охлаждение": _on_off_label(cooling_active, on_text="Включено", off_text="Отключено"),
        "Багажник": _open_closed_label(metrics.get("trunkStatus")),
        "Центральный замок": _lock_label(metrics, tbox),
        "На связи": _on_off_label(tbox.get("isOnline"), on_text="да", off_text="нет"),
    }


def _access_fields(drivers_payload: Any) -> dict[str, Any]:
    owner = _owner_from_drivers(drivers_payload)
    if not owner:
        return {}

    drivers: list[str] = []
    if isinstance(drivers_payload, list):
        for item in drivers_payload:
            if not isinstance(item, dict) or item.get("kind") == "owner":
                continue
            first = (item.get("firstName") or "").strip()
            last = (item.get("lastName") or "").strip()
            name = " ".join(part for part in (first, last) if part).strip() or "Без имени"
            phone = _format_phone(item.get("phone"))
            drivers.append(f"{name} ({phone})" if phone else name)

    fields = {
        "Владелец": owner.get("name"),
        "Телефон владельца": owner.get("phone"),
    }
    if drivers:
        fields["Водители"] = ", ".join(drivers)
    return fields


def _format_dealers(dealers: Any) -> str | None:
    if not dealers:
        return None
    if not isinstance(dealers, list):
        return str(dealers)
    names: list[str] = []
    for dealer in dealers:
        if isinstance(dealer, dict):
            name = dealer.get("name") or dealer.get("title")
            if name:
                names.append(str(name))
        elif dealer:
            names.append(str(dealer))
    return ", ".join(names) if names else None


def _maintenance_fields(maintenance: dict[str, Any]) -> dict[str, Any]:
    next_info = maintenance.get("next")
    next_label = None
    if isinstance(next_info, dict):
        next_label = next_info.get("label")

    booking_list = maintenance.get("bookingList")
    bookings = None
    if isinstance(booking_list, list):
        bookings = len(booking_list) if booking_list else None

    return {
        "Следующее ТО": next_label,
        "Рекомендуемое ТО": _get_nested(maintenance, "recommended", "label")
        if isinstance(maintenance.get("recommended"), dict)
        else maintenance.get("recommended"),
        "Заявки на ТО": bookings if bookings is not None else maintenance.get("ordersCount"),
        "История ТО": maintenance.get("historyTotal", maintenance.get("historyCount")),
        "Избранные дилеры": _format_dealers(maintenance.get("favDealers")),
        "Авто обслуживается у": _format_dealers(maintenance.get("servicingDealers")),
    }


def _render_section(title: str, fields: dict[str, Any], *, show_empty: bool = False) -> str:
    lines = [f"=== {title} ==="]
    has_values = False
    for label, value in fields.items():
        if value is None or value == "":
            if show_empty:
                lines.append(f"{label}: —")
                has_values = True
            continue
        lines.append(f"{label}: {_display_value(value)}")
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
    tbox = item.get("tbox")

    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    title = car_model.get("displayName") or table.get("licensePlate") or table.get("vin") or f"Автомобиль {index}"

    sections = [f"--- [{index}/{total}] {title} ---"]
    sections.append(
        _render_section("Таблица (как на сайте)", _table_fields(table, geo, detail, drivers, tbox), show_empty=True)
    )
    sections.append("")
    sections.append(_render_section("Сводка (верх карточки)", _summary_fields(table, geo, detail, tbox), show_empty=True))
    sections.append("")
    sections.append(_render_section("Об автомобиле", _about_car_fields(table, detail), show_empty=True))
    sections.append("")
    sections.append(_render_section("Управление (только чтение)", _control_state_fields(tbox), show_empty=True))
    sections.append("")
    sections.append(_render_section("Климат контроль", _climate_fields(table, detail, geo, tbox), show_empty=True))
    sections.append("")
    sections.append(_render_section("Местоположение", _location_fields(geo, table, detail, tbox), show_empty=True))

    access = _access_fields(drivers)
    sections.append("")
    if access:
        sections.append(_render_section("Доступы", access, show_empty=True))
    else:
        sections.append(_render_section("Доступы", {"Примечание": item.get("drivers_error", "нет данных")}))

    sections.append("")
    if maintenance:
        sections.append(_render_section("Техническое обслуживание", _maintenance_fields(maintenance), show_empty=True))
    else:
        sections.append(
            _render_section(
                "Техническое обслуживание",
                {"Примечание": item.get("maintenance_error", "нет данных")},
            )
        )

    if item.get("detail_error"):
        sections.append("")
        sections.append(f"Ошибка карточки: {item['detail_error']}")
    if item.get("tbox_error"):
        sections.append("")
        sections.append(f"Ошибка телеметрии: {item['tbox_error']}")

    return "\n".join(sections)


def format_dashboard_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Автомобили не найдены."

    chunks = [format_vehicle_dashboard(item, index, len(items)) for index, item in enumerate(items, start=1)]
    return "\n\n".join(chunks)


def _brief_fields(
    table: dict[str, Any],
    geo: dict[str, Any],
    detail: dict[str, Any],
    tbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Key live metrics that change often (for Telegram short view)."""
    metrics = _collect_metrics(table, detail, geo, tbox)
    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}

    fields: dict[str, Any] = {
        "Модель": car_model.get("displayName") or car_model.get("name"),
        "Гос. номер": table.get("licensePlate") or detail.get("licensePlate"),
        "Статус": _status_chip(tbox),
    }
    if metrics.get("fuelPercentage") is not None or metrics.get("remainsMileageFuel") is not None:
        fuel_pct = metrics.get("fuelPercentage")
        fuel_km = metrics.get("remainsMileageFuel")
        if fuel_pct is not None and fuel_km is not None:
            fields["Топливо"] = f"{fuel_pct}% / {fuel_km} км"
        elif fuel_pct is not None:
            fields["Топливо"] = f"{fuel_pct}%"
        elif fuel_km is not None:
            fields["Топливо"] = f"{fuel_km} км"

    battery_pct = metrics.get("batteryPercentage")
    battery_km = metrics.get("remainsMileage")
    if battery_pct is not None and battery_km is not None:
        fields["Батарея"] = f"{battery_pct}% / {battery_km} км"
    elif battery_pct is not None:
        fields["Батарея"] = f"{battery_pct}%"

    fields.update(
        {
            "12V": metrics.get("12VBatteryVoltage"),
            "Пробег, км": metrics.get("odometer"),
            "SOH, %": metrics.get("soh"),
            "ОЖ, °C": metrics.get("coolantTemp"),
            "Темп. АКБ, °C": metrics.get("batteryTemp"),
            "На улице, °C": metrics.get("outsideTemp"),
            "Скорость": _speed_label(metrics.get("speed")),
            "На связи": _on_off_label(tbox.get("isOnline"), on_text="да", off_text="нет")
            if isinstance(tbox, dict)
            else None,
            "Обновлено": _recency_from_sources(table, detail, metrics=metrics),
        }
    )
    return fields


def format_vehicle_brief(item: dict[str, Any], index: int, total: int) -> str:
    table = item.get("table", {})
    geo = item.get("geo", {})
    detail = item.get("detail", {})
    tbox = item.get("tbox")

    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    title = car_model.get("displayName") or table.get("licensePlate") or table.get("vin") or f"Автомобиль {index}"

    lines = [f"--- [{index}/{total}] {title} — кратко ---"]
    for label, value in _brief_fields(table, geo, detail, tbox).items():
        if value is None or value == "":
            continue
        lines.append(f"{label}: {_display_value(value)}")

    if item.get("tbox_error"):
        lines.append(f"Телеметрия: {item['tbox_error']}")
    return "\n".join(lines)


def format_dashboard_brief(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Автомобили не найдены."
    chunks = [format_vehicle_brief(item, index, len(items)) for index, item in enumerate(items, start=1)]
    return "\n\n".join(chunks)


def extract_vehicle_coordinates(item: dict[str, Any]) -> tuple[float, float] | None:
    table = item.get("table") if isinstance(item.get("table"), dict) else {}
    geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    tbox = item.get("tbox") if isinstance(item.get("tbox"), dict) else None

    metrics = _collect_metrics(table, detail, geo, tbox)
    lat = metrics.get("latitude", geo.get("lat"))
    lon = metrics.get("longitude", geo.get("lon"))
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def vehicle_location_title(item: dict[str, Any]) -> str:
    table = item.get("table") if isinstance(item.get("table"), dict) else {}
    car_model = table.get("carModel") if isinstance(table.get("carModel"), dict) else {}
    return (
        car_model.get("displayName")
        or table.get("licensePlate")
        or table.get("vin")
        or "Автомобиль"
    )


def is_dashboard_snapshot_raw(raw: Any) -> bool:
    return isinstance(raw, dict) and any(key in raw for key in ("table", "tbox", "detail", "geo"))


def compact_dashboard_raw(item: dict[str, Any]) -> dict[str, Any]:
    """Drop unused API bulk (e.g. tbox.buttons ~70 KB) before persisting to SQLite."""
    if not is_dashboard_snapshot_raw(item):
        return item

    slim_tbox: dict[str, Any] | None = None
    tbox = item.get("tbox")
    if isinstance(tbox, dict):
        slim_tbox = {}
        for key in (
            "isOnline",
            "isCentralLockingOn",
            "isParked",
            "lastOnlineTime",
            "preparation_script",
        ):
            if key in tbox:
                slim_tbox[key] = tbox[key]
        sensors = tbox.get("sensors")
        if isinstance(sensors, dict):
            slim_sensors: dict[str, Any] = {}
            for key in (
                "chip",
                "sensorsData",
                "positionData",
                "battery",
                "v12",
                "odometer",
                "remain",
                "lastSensorsRecieved",
            ):
                if key in sensors:
                    slim_sensors[key] = sensors[key]
            if slim_sensors:
                slim_tbox["sensors"] = slim_sensors

    compacted: dict[str, Any] = {
        "table": item.get("table") if isinstance(item.get("table"), dict) else {},
        "geo": item.get("geo") if isinstance(item.get("geo"), dict) else {},
        "detail": item.get("detail") if isinstance(item.get("detail"), dict) else {},
        "drivers": item.get("drivers"),
        "maintenance": item.get("maintenance") if isinstance(item.get("maintenance"), dict) else {},
    }
    if slim_tbox:
        compacted["tbox"] = slim_tbox
    return compacted


def merge_dashboard_export_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Flat fields for history export — same labels as format_vehicle_dashboard sections."""
    table = item.get("table") if isinstance(item.get("table"), dict) else {}
    geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    tbox = item.get("tbox") if isinstance(item.get("tbox"), dict) else None
    drivers = item.get("drivers")
    maintenance = item.get("maintenance") if isinstance(item.get("maintenance"), dict) else {}

    sections: list[dict[str, Any]] = [
        _table_fields(table, geo, detail, drivers, tbox),
        _summary_fields(table, geo, detail, tbox),
        _about_car_fields(table, detail),
        _control_state_fields(tbox),
        _climate_fields(table, detail, geo, tbox),
        _location_fields(geo, table, detail, tbox),
        _access_fields(drivers),
        _maintenance_fields(maintenance),
    ]

    merged: dict[str, Any] = {}
    for section in sections:
        for key, value in section.items():
            if key not in merged:
                merged[key] = value
    return merged


def _empty_dashboard_item() -> dict[str, Any]:
    return {
        "table": {},
        "geo": {},
        "detail": {},
        "tbox": {},
        "drivers": [],
        "maintenance": {},
    }


SNAPSHOT_EXPORT_DATA_HEADERS: tuple[str, ...] = tuple(
    merge_dashboard_export_fields(_empty_dashboard_item()).keys()
)


def telemetry_fallback_export_fields(telemetry: "VehicleTelemetry") -> dict[str, Any]:
    """Map stored scalar columns when raw dashboard JSON is missing."""
    fields = merge_dashboard_export_fields(_empty_dashboard_item())

    if telemetry.vin:
        fields["VIN"] = telemetry.vin
    if telemetry.name:
        fields["Модель"] = telemetry.name
    if telemetry.status:
        fields["Статус"] = telemetry.status
    if telemetry.battery_percent is not None:
        fields["Заряд тяговой батареи, %"] = telemetry.battery_percent
        fields["Батарея, %"] = telemetry.battery_percent
    if telemetry.range_km is not None:
        fields["Батарея, км"] = telemetry.range_km
    if telemetry.odometer_km is not None:
        fields["Пробег, км"] = telemetry.odometer_km
        fields["Одометр, км"] = telemetry.odometer_km
    if telemetry.v12_voltage is not None:
        fields["Батарея 12V"] = telemetry.v12_voltage
        fields["Напряжение АКБ, V"] = telemetry.v12_voltage
    if telemetry.soh_percent is not None:
        fields["SOH, %"] = telemetry.soh_percent
    if telemetry.speed_kmh is not None:
        fields["Скорость"] = _speed_label(telemetry.speed_kmh)
    if telemetry.latitude is not None:
        fields["Широта"] = telemetry.latitude
    if telemetry.longitude is not None:
        fields["Долгота"] = telemetry.longitude
    if telemetry.course_deg is not None:
        fields["Курс"] = telemetry.course_deg
    if telemetry.is_online is not None:
        fields["На связи"] = _on_off_label(telemetry.is_online, on_text="да", off_text="нет")
    if telemetry.location_sharing is not None:
        fields["Передача геопозиции"] = _on_off_label(
            telemetry.location_sharing,
            on_text="да",
            off_text="нет",
        )
    return fields


def snapshot_export_field_map(telemetry: "VehicleTelemetry") -> dict[str, Any]:
    raw = telemetry.raw
    if is_dashboard_snapshot_raw(raw):
        return merge_dashboard_export_fields(raw)
    return telemetry_fallback_export_fields(telemetry)
