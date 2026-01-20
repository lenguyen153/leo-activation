import logging
import requests
import re
import unicodedata
from typing import Dict, Any, Optional, List

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agentic_tools.weather_tools")

# ============================================================
# Canonical aliases
# ============================================================
CITY_ALIASES = {
    "saigon": "ho chi minh city",
    "hcm": "ho chi minh city",
    "hcmc": "ho chi minh city",
    "tphcm": "ho chi minh city",
    "danang": "da nang",
    "hn": "hanoi",
    "ha noi": "hanoi"
}

VIETNAM_KEYWORDS = {"viet", "vietnam", "vn", "tphcm", "hcm", "saigon", "hanoi", "danang"}

# ============================================================
# Normalization helpers
# ============================================================
def normalize_text(text: str) -> str:
    """
    Normalize text for geocoding.

    Steps:
    - Lowercase
    - Vietnamese-specific letter normalization (đ → d)
    - Unicode NFKD normalization
    - Remove diacritics
    - Remove punctuation
    - Collapse whitespace
    """
    text = text.strip().lower()

    # 🔴 CRITICAL: Vietnamese-specific normalization
    text = text.replace("đ", "d").replace("Đ", "d")

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()



def canonicalize_city_name(raw: str) -> str:
    """
    Convert a city name to its canonical form using alias mapping.

    Args:
        raw: Original user-provided city name.

    Returns:
        Canonical city name suitable for geocoding.
    """
    normalized = normalize_text(raw)
    return CITY_ALIASES.get(normalized, normalized)


def looks_vietnamese(text: str) -> bool:
    """
    Heuristically detect whether a location is likely in Vietnam.

    Args:
        text: User-provided location string.

    Returns:
        True if Vietnamese indicators are detected, else False.
    """
    t = normalize_text(text)
    return any(k in t for k in VIETNAM_KEYWORDS)

# ============================================================
# Geocoding
# ============================================================
def get_coordinates(city_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a city name to geographic coordinates.

    This function applies multiple accuracy strategies:
    - Unicode normalization and alias resolution
    - Language fallback (vi → en)
    - Country bias (Vietnam when detected)
    - Candidate ranking instead of first-hit selection

    Args:
        city_name: City or location name provided by the user.

    Returns:
        Dictionary containing latitude, longitude, resolved name, and country
        if successful; otherwise None.
    """
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"

    canonical = canonicalize_city_name(city_name)
    country_bias = "VN" if looks_vietnamese(city_name) else None

    attempts = [
        {"name": city_name, "language": "en"},
        {"name": city_name, "language": "vi"},
        {"name": canonical, "language": "vi"},
        {"name": canonical, "language": "en"},
    ]

    seen = set()
    candidates: List[Dict[str, Any]] = []

    for attempt in attempts:
        key = (attempt["name"], attempt["language"])
        if key in seen:
            continue
        seen.add(key)

        try:
            params = {
                "name": attempt["name"],
                "count": 5,
                "language": attempt["language"],
                "format": "json"
            }
            resp = requests.get(geo_url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            for r in data.get("results", []):
                score = 0

                if country_bias and r.get("country_code") == country_bias:
                    score += 3

                population = r.get("population") or 0
                if population > 1_000_000:
                    score += 2
                elif population > 100_000:
                    score += 1

                resolved = normalize_text(r.get("name", ""))
                if resolved == canonical:
                    score += 3
                elif canonical in resolved:
                    score += 1

                candidates.append({
                    "score": score,
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "name": r["name"],
                    "country": r.get("country", ""),
                    "country_code": r.get("country_code", "")
                })

        except requests.RequestException as e:
            logger.warning(f"Geocoding error for {attempt}: {e}")

    if not candidates:
        logger.warning(f"Geolocation failed for '{city_name}'")
        return None

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]

    logger.info(
        f"Geolocated '{city_name}' → {best['name']}, {best['country']} "
        f"({best['lat']}, {best['lon']}) score={best['score']}"
    )

    return best

# ============================================================
# Weather helpers
# ============================================================
def get_weather_description(code: int) -> str:
    """
    Convert WMO weather codes into human-readable descriptions.

    Args:
        code: Integer weather code from Open-Meteo.

    Returns:
        Textual description of the weather condition.
    """
    wmo_codes = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
        95: "Thunderstorm", 96: "Thunderstorm with hail"
    }
    return wmo_codes.get(code, "Unknown")

# ============================================================
# Public tool function (REQUIRES DOCSTRING)
# ============================================================
def get_current_weather(location: str, unit: str = "celsius") -> Dict[str, Any]:
    """
    Get the current weather for a city or location name.

    The function automatically:
    - Normalizes and resolves the location name
    - Converts it into latitude and longitude
    - Fetches real-time weather data from Open-Meteo

    Args:
        location: City or place name (e.g., "Da Nang", "Paris", "HCMC").
        unit: Temperature unit, either "celsius" or "fahrenheit".

    Returns:
        A structured dictionary containing:
        - resolved location metadata
        - current temperature, wind speed, and weather condition
        - data source identifier
    """
    unit = unit.lower()
    if unit not in {"celsius", "fahrenheit"}:
        return {"status": "error", "message": "Invalid unit"}

    coords = get_coordinates(location)
    if not coords:
        return {"status": "error", "message": f"Location not found: {location}"}

    weather_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "current_weather": "true",
        "temperature_unit": unit
    }

    try:
        resp = requests.get(weather_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current_weather", {})

        return {
            "status": "success",
            "location": {
                "input": location,
                "resolved_name": coords["name"],
                "country": coords["country"],
                "lat": coords["lat"],
                "lon": coords["lon"]
            },
            "weather": {
                "temperature": current.get("temperature"),
                "unit": "°C" if unit == "celsius" else "°F",
                "windspeed": current.get("windspeed"),
                "condition_code": current.get("weathercode"),
                "description": get_weather_description(current.get("weathercode")),
                "is_day": bool(current.get("is_day"))
            },
            "source": "Open-Meteo"
        }

    except requests.RequestException as e:
        logger.error(f"Weather API error: {e}")
        return {"status": "error", "message": "Weather service unreachable"}
