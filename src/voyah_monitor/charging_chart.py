from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

MSK = ZoneInfo("Europe/Moscow")


def render_charging_chart(
    points: list[tuple[datetime, float]],
    *,
    max_percent: float,
    forecast_end: datetime | None,
    current_soc: float,
) -> bytes:
    """Build PNG chart: Y = SOC %, X = Moscow time; solid = actual, dashed = forecast."""
    if not points:
        raise ValueError("points required")

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)

    times_msk = [ts.astimezone(MSK) for ts, _ in points]
    socs = [soc for _, soc in points]

    ax.plot(times_msk, socs, "o-", color="#2563eb", linewidth=2, markersize=5, label="Факт")

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

    ax.set_ylabel("Заряд, %")
    ax.set_xlabel("Время (МСК)")
    ax.set_ylim(max(0, min(socs) - 5), min(100, max_percent + 3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=MSK))
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
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
