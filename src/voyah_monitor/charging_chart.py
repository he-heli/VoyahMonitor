from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from voyah_monitor.timeutil import MSK

ChargingPoint = tuple[datetime, float, float | None]


def render_charging_chart(
    points: list[ChargingPoint] | list[tuple[datetime, float]],
    *,
    max_percent: float,
    forecast_end: datetime | None,
    current_soc: float,
) -> bytes:
    """PNG chart: SOC (blue) + optional battery temp (red, right axis), Moscow time."""
    if not points:
        raise ValueError("points required")

    normalized: list[ChargingPoint] = []
    for item in points:
        if len(item) >= 3:
            normalized.append((item[0], float(item[1]), item[2]))  # type: ignore[misc]
        else:
            normalized.append((item[0], float(item[1]), None))

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)

    times_msk = [ts.astimezone(MSK) for ts, _, _ in normalized]
    socs = [soc for _, soc, _ in normalized]

    ax.plot(times_msk, socs, "o-", color="#2563eb", linewidth=2, markersize=5, label="Заряд")

    last_time = times_msk[-1]
    if forecast_end is not None and current_soc < max_percent:
        end_msk = forecast_end.astimezone(MSK)
        ax.plot(
            [last_time, end_msk],
            [current_soc, max_percent],
            "--",
            color="#16a34a",
            linewidth=2,
            label="Прогноз",
        )

    ax.set_ylabel("Заряд, %", color="#2563eb")
    ax.tick_params(axis="y", labelcolor="#2563eb")
    ax.set_xlabel("Время (МСК)")
    ax.set_ylim(max(0, min(socs) - 5), min(100, max_percent + 3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=MSK))
    ax.grid(True, alpha=0.3)

    temp_pairs = [(ts.astimezone(MSK), temp) for ts, _, temp in normalized if temp is not None]
    temp_times = [ts for ts, _ in temp_pairs]
    temps = [temp for _, temp in temp_pairs]

    handles, labels = ax.get_legend_handles_labels()
    if temps:
        ax_temp = ax.twinx()
        (temp_line,) = ax_temp.plot(
            temp_times,
            temps,
            "s-",
            color="#dc2626",
            linewidth=2,
            markersize=4,
            label="Темп. АКБ",
        )
        ax_temp.set_ylabel("Темп. АКБ, °C", color="#dc2626")
        ax_temp.tick_params(axis="y", labelcolor="#dc2626")
        pad = max(2.0, (max(temps) - min(temps)) * 0.15)
        ax_temp.set_ylim(min(temps) - pad, max(temps) + pad)
        handles.append(temp_line)
        labels.append("Темп. АКБ")

    ax.legend(handles, labels, loc="lower right", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def parse_point_timestamp(iso_value: str) -> datetime:
    dt = datetime.fromisoformat(iso_value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
