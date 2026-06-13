"""Ballpark weather via Open-Meteo (https://open-meteo.com) — no key required.

Domed/retractable-roof parks are treated as climate-controlled (neutral
conditions, no adjustment) since we have no live roof-status feed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from .cache import cache

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

NEUTRAL: Dict[str, Any] = {
    "available": False,
    "isDome": False,
    "tempF": None,
    "windMph": None,
    "windDir": None,
}

DOME: Dict[str, Any] = {
    "available": True,
    "isDome": True,
    "tempF": 72.0,
    "windMph": 0.0,
    "windDir": None,
}

# (latitude, longitude, isDome). Retractable-roof parks that are closed more
# often than not in extreme weather are marked as domes — a simplification,
# but better than guessing wind direction through an open roof.
STADIUMS: Dict[str, tuple] = {
    "Angel Stadium": (33.8003, -117.8827, False),
    "Chase Field": (33.4455, -112.0667, True),
    "Truist Park": (33.8908, -84.4678, False),
    "Oriole Park at Camden Yards": (39.2838, -76.6217, False),
    "Fenway Park": (42.3467, -71.0972, False),
    "Wrigley Field": (41.9484, -87.6553, False),
    "Guaranteed Rate Field": (41.8299, -87.6338, False),
    "Great American Ball Park": (39.0979, -84.5066, False),
    "Progressive Field": (41.4962, -81.6852, False),
    "Coors Field": (39.7559, -104.9942, False),
    "Comerica Park": (42.3390, -83.0485, False),
    "Daikin Park": (29.7570, -95.3555, True),
    "Minute Maid Park": (29.7570, -95.3555, True),
    "Kauffman Stadium": (39.0517, -94.4803, False),
    "Dodger Stadium": (34.0739, -118.2400, False),
    "loanDepot park": (25.7781, -80.2196, True),
    "American Family Field": (43.0280, -87.9712, True),
    "Target Field": (44.9817, -93.2776, False),
    "Citi Field": (40.7571, -73.8458, False),
    "Yankee Stadium": (40.8296, -73.9262, False),
    "Oakland Coliseum": (37.7516, -122.2005, False),
    "Sutter Health Park": (38.5805, -121.5132, False),
    "Citizens Bank Park": (39.9061, -75.1665, False),
    "PNC Park": (40.4469, -80.0057, False),
    "Petco Park": (32.7073, -117.1566, False),
    "Oracle Park": (37.7786, -122.3893, False),
    "T-Mobile Park": (47.5914, -122.3325, False),
    "Busch Stadium": (38.6226, -90.1928, False),
    "Tropicana Field": (27.7683, -82.6534, True),
    "Globe Life Field": (32.7473, -97.0832, True),
    "Rogers Centre": (43.6414, -79.3894, True),
    "Nationals Park": (38.8730, -77.0074, False),
}

_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_weather(venue: str, game_date_iso: str) -> Dict[str, Any]:
    """Forecast conditions for ``venue`` at game time, or a neutral default."""
    coords = STADIUMS.get(venue)
    if coords is None:
        return dict(NEUTRAL)
    lat, lon, is_dome = coords
    if is_dome:
        return dict(DOME)

    async def fetch() -> Dict[str, Any]:
        c = client()
        r = await c.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 7,
                "past_days": 2,
            },
        )
        r.raise_for_status()
        data = r.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return dict(NEUTRAL)

        target = datetime.fromisoformat(game_date_iso.replace("Z", "+00:00"))
        best_idx, best_diff = 0, None
        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=target.tzinfo)
            diff = abs((dt - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_idx, best_diff = i, diff

        return {
            "available": True,
            "isDome": False,
            "tempF": hourly.get("temperature_2m", [None])[best_idx],
            "windMph": hourly.get("wind_speed_10m", [None])[best_idx],
            "windDir": hourly.get("wind_direction_10m", [None])[best_idx],
        }

    return await cache.get_or_set(f"weather:{venue}:{game_date_iso[:13]}", 1800, fetch)
