import calendar
from collections import Counter
from datetime import date, datetime
from typing import Any

import requests

from forms import SKIN_TYPE_OPTIONS, clean_text

MONTHS_RU = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
MAX_MONTHS_BACK = 11
SKIN_TYPE_TIPS = {
    "I": "Очень светлая кожа быстро обгорает. SPF нужен почти всегда, особенно при высоком UV.",
    "II": "Светлая кожа чувствительна к солнцу, SPF лучше не пропускать.",
    "III": "Средний фототип. SPF всё ещё обязателен, особенно летом и днём.",
    "IV": "Смуглая кожа тоже нуждается в защите, просто риск ожога ниже.",
    "V": "Тёмная кожа тоже получает UV-нагрузку, SPF помогает сохранять кожу здоровой.",
    "VI": "Очень тёмная кожа защищена лучше, но SPF всё равно нужен при солнце.",
}
TIMEOUT_SECONDS = 8


class SunDiaryService:
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def _fetch_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        for _ in range(3):
            try:
                response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    return data
            except (requests.RequestException, ValueError):
                pass
        return None

    def resolve_location(self, query: str) -> dict[str, Any] | None:
        query = clean_text(query)
        if not query:
            return None

        data = self._fetch_json(
            self.GEOCODE_URL,
            {"name": query, "count": 1, "language": "ru", "format": "json"},
        )
        results = (data or {}).get("results") or []
        if not results:
            return None

        place = results[0]
        return {
            "name": place.get("name", query),
            "country": place.get("country", ""),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
        }

    def _current_weather(self, place: dict[str, Any]) -> dict[str, Any] | None:
        data = self._fetch_json(
            self.FORECAST_URL,
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,uv_index",
                "timezone": "auto",
            },
        )
        current = (data or {}).get("current") or {}
        if not current:
            return None
        return {
            "name": place.get("name", "Локация"),
            "country": place.get("country", ""),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "timezone": (data or {}).get("timezone"),
            "local_now": current.get("time"),
            "uv": current.get("uv_index"),
            "temp": current.get("temperature_2m"),
        }

    def get_location_context(self, location: str) -> dict[str, Any] | None:
        place = self.resolve_location(location)
        if not place:
            return None
        return self._current_weather(place)

    def get_current_weather_for_place(self, place: dict[str, Any]) -> dict[str, Any] | None:
        if not place:
            return None
        data = self._current_weather(place)
        if not data:
            return None
        return {
            "location": data.get("name", "Локация"),
            "country": data.get("country", ""),
            "uv": data.get("uv"),
            "temp": data.get("temp"),
            "time": data.get("local_now"),
        }

    def _hourly_params(self, place: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "hourly": "uv_index,temperature_2m",
            "timezone": "auto",
        }
        if extra:
            params.update(extra)
        return params

    def _pick_hourly_point(self, data: dict[str, Any] | None, selected_dt: datetime) -> dict[str, Any] | None:
        if not data:
            return None

        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return None

        uv_list = hourly.get("uv_index") or []
        temp_list = hourly.get("temperature_2m") or []
        stamp = selected_dt.strftime("%Y-%m-%dT%H:00")
        index = next((i for i, item in enumerate(times) if str(item).startswith(stamp)), None)
        if index is None:
            index = next((i for i, item in enumerate(times) if str(item).startswith(selected_dt.date().isoformat())), None)
        if index is None:
            return None

        return {
            "uv": uv_list[index] if index < len(uv_list) else None,
            "temp": temp_list[index] if index < len(temp_list) else None,
            "time": times[index],
        }

    def _fetch_uv_from_sources(self, place: dict[str, Any], selected_dt: datetime, local_today: date) -> dict[str, Any] | None:
        days_back = max((local_today - selected_dt.date()).days, 0)
        sources = [
            (self.FORECAST_URL, {"forecast_days": 16}),
            (self.HISTORICAL_FORECAST_URL, {}),
            (self.ARCHIVE_URL, {}),
        ]
        if selected_dt.date() < local_today:
            sources = [
                (self.ARCHIVE_URL, {}),
                (self.HISTORICAL_FORECAST_URL, {}),
                (self.FORECAST_URL, {"past_days": min(max(days_back, 1), 92)}),
            ]

        for url, extra in sources:
            data = self._fetch_json(url, self._hourly_params(place, extra))
            point = self._pick_hourly_point(data, selected_dt)
            if point and (point.get("uv") is not None or point.get("temp") is not None):
                return point
        return None

    def _parse_iso_local(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _same_minute(self, a: datetime, b: datetime) -> bool:
        return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)

    def get_uv_for_day(self, location: str, date_value: str, time_value: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        location = clean_text(location)
        date_value = clean_text(date_value)
        time_value = clean_text(time_value)
        if not location or not date_value or not time_value:
            return None

        place = context if context and context.get("latitude") is not None and context.get("longitude") is not None else self.resolve_location(location)
        if not place:
            return None

        try:
            selected_dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None

        local_now = self._parse_iso_local(context.get("local_now") if context else None)
        if local_now and self._same_minute(selected_dt, local_now):
            weather = self.get_current_weather_for_place(place)
            if weather:
                return {
                    "location": weather.get("location", "Локация"),
                    "country": weather.get("country", ""),
                    "uv": weather.get("uv"),
                    "temp": weather.get("temp"),
                    "time": weather.get("time"),
                }
            return None

        local_today = local_now.date() if local_now else date.today()
        point = self._fetch_uv_from_sources(place, selected_dt, local_today)
        if not point:
            return None

        return {
            "location": place.get("name", "Локация"),
            "country": place.get("country", ""),
            "uv": point.get("uv"),
            "temp": point.get("temp"),
            "time": point.get("time"),
        }

    def validate_location_datetime(self, location: str, date_value: str, time_value: str) -> tuple[dict[str, Any] | None, str | None]:
        context = self.get_location_context(location)
        if not context:
            return None, "Не удалось определить локацию и местное время."

        try:
            selected_dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        except ValueError:
            return context, "Некорректные дата или время."

        local_now = self._parse_iso_local(context.get("local_now"))
        if not local_now:
            return context, "Не удалось определить текущее время в выбранной локации."

        if selected_dt > local_now:
            name = context.get("name") or "выбранной локации"
            return context, f"Будущее время в {name} выбрать нельзя. Сейчас там {local_now.strftime('%d.%m.%Y %H:%M')}."

        return context, None

    def normalize_session_values(self, was_outside: bool, used_spf: bool, had_tan: bool, duration: int) -> tuple[bool, bool, bool, int]:
        if not was_outside:
            return False, False, False, 0
        if not had_tan:
            return True, bool(used_spf), False, 0
        return True, bool(used_spf), True, max(int(duration or 0), 1)

    def get_skin_type_label(self, skin_type: str) -> str:
        return SKIN_TYPE_OPTIONS.get(skin_type, SKIN_TYPE_OPTIONS["II"])

    def get_skin_type_tip(self, skin_type: str, uv_index: float | int | None) -> str:
        skin_type = skin_type if skin_type in SKIN_TYPE_TIPS else "II"
        try:
            uv = float(uv_index) if uv_index is not None else None
        except (TypeError, ValueError):
            uv = None
        tip = SKIN_TYPE_TIPS[skin_type]
        if uv is None:
            return tip
        if skin_type in {"I", "II"} and uv >= 6:
            return tip + " При таком UV лучше не тянуть с SPF и тенью."
        if skin_type in {"III", "IV"} and uv >= 6:
            return tip + " В высокий UV защита особенно важна."
        return tip

    def _safe_rate(self, part: int, total: int) -> float:
        return round(part / total * 100, 1) if total else 0

    def _average(self, values: list[float | int | None]) -> float:
        data = [value for value in values if value is not None]
        return round(sum(data) / len(data), 1) if data else 0

    def build_analytics_stats(self, sessions: list[Any]) -> dict[str, Any] | None:
        if not sessions:
            return None

        skin_counts = Counter(session.skin_type for session in sessions)
        common_skin = max(skin_counts, key=skin_counts.get)
        tan = [s for s in sessions if s.had_tan]
        high_uv = [s for s in sessions if (s.uv_index or 0) >= 6]
        high_uv_no_spf = [s for s in high_uv if not s.used_spf]
        tan_spf = [s for s in tan if s.used_spf]
        tan_times = [s.duration for s in tan if s.duration > 0]

        if high_uv_no_spf:
            insight = f"В высокий UV у вас {len(high_uv_no_spf)} запись(ей) без SPF. Это главный риск, который стоит сократить первым."
        elif tan:
            insight = f"У вас {len(tan)} запись(ей) с загаром, средняя длительность — {self._average(tan_times)} мин."
        else:
            insight = "Пока мало записей с загаром. Когда накопится больше данных, здесь появятся более точные выводы."

        max_uv = max((s.uv_index or 0) for s in sessions)

        return {
            "count": len(sessions),
            "spf_rate": self._safe_rate(sum(1 for s in sessions if s.used_spf), len(sessions)),
            "avg_uv": self._average([s.uv_index for s in sessions if s.uv_index is not None]),
            "avg_tan_time": self._average(tan_times),
            "tan_count": len(tan),
            "high_uv_sessions": len(high_uv),
            "high_uv_without_spf": len(high_uv_no_spf),
            "tan_spf_rate": self._safe_rate(len(tan_spf), len(tan)),
            "high_uv_spf_rate": self._safe_rate(len([s for s in high_uv if s.used_spf]), len(high_uv)),
            "max_uv": round(max_uv, 1),
            "skin_type_counts": dict(sorted(skin_counts.items(), key=lambda item: (-item[1], item[0]))),
            "common_skin_type": common_skin,
            "common_skin_label": self.get_skin_type_label(common_skin),
            "common_skin_count": skin_counts[common_skin],
            "skin_tip": self.get_skin_type_tip(common_skin, max_uv),
            "insight": insight,
        }


service = SunDiaryService()


def build_calendar(sessions: list[Any], year: int, month: int) -> list[list[dict[str, Any]]]:
    by_day: dict[str, list[Any]] = {}
    for session in sessions:
        by_day.setdefault(session.date[:10], []).append(session)

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    return [[{
        "day": day.day,
        "date": day.strftime("%Y-%m-%d"),
        "current_month": day.month == month,
        "sessions": by_day.get(day.strftime("%Y-%m-%d"), []),
    } for day in week] for week in weeks]


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def get_month_title(year: int, month: int) -> str:
    return f"{MONTHS_RU[month - 1].capitalize()} {year}"


def month_to_value(year: int, month: int) -> str:
    return f"{year}-{month:02d}"
