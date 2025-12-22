import logging
import requests
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Agent-Weather")

def get_coordinates(city_name: str) -> Optional[Dict[str, float]]:
    """
    Resolves a city name to latitude/longitude using Open-Meteo Geocoding API.
    """
    try:
        # Open-Meteo Geocoding API (Free, no key required)
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": city_name,
            "count": 1,       # We only need the top match
            "language": "en",
            "format": "json"
        }
        
        response = requests.get(geo_url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data.get("results"):
            logger.warning(f"Geolocation failed: No results found for '{city_name}'")
            return None

        # Return the top match
        result = data["results"][0]
        logger.info(f"Geolocated '{city_name}' to {result['name']}, {result.get('country')} ({result['latitude']}, {result['longitude']})")
        
        return {
            "lat": result["latitude"],
            "lon": result["longitude"],
            "name": result["name"],
            "country": result.get("country", "")
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Geocoding network error: {e}")
        return None

def get_weather_description(code: int) -> str:
    """Helper to convert WMO weather codes to text."""
    # Simplified WMO code mapping
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

def get_current_weather(location: str, unit: str = "celsius") -> Dict[str, Any]:
    """
    Get real-time weather by automatically geocoding the location name.

    Args:
        location: The city name (e.g., 'Saigon', 'Paris').
        unit: 'celsius' or 'fahrenheit'.
    """
    unit = unit.lower()
    if unit not in ["celsius", "fahrenheit"]:
        return {"status": "error", "message": "Invalid unit. Use 'celsius' or 'fahrenheit'."}

    # 1. Geocode the text to coordinates
    coords = get_coordinates(location)
    if not coords:
        return {
            "status": "error", 
            "message": f"Could not find location: {location}"
        }

    # 2. Fetch Weather Data
    weather_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "current_weather": "true",
        "temperature_unit": unit  # API handles unit conversion automatically
    }

    logger.info(f"Fetching weather for {coords['name']}...")

    try:
        response = requests.get(weather_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        current = data.get("current_weather", {})
        
        # 3. Construct rich response
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

    except requests.exceptions.RequestException as e:
        logger.error(f"Weather API error: {e}")
        return {"status": "error", "message": "Weather service unreachable"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"status": "error", "message": str(e)}

# --- Usage Example ---
if __name__ == "__main__":
    # Test with a city not in your original list
    result = get_current_weather("Da Nang", unit="celsius")
    import json
    print(json.dumps(result, indent=2))