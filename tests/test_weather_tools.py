import os
import sys
import pytest
import requests

# Ensure project root is on path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from agentic_tools import weather_tools as wt


# ============================================================
# Shared test utilities
# ============================================================
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ============================================================
# Tests: normalization & canonicalization
# ============================================================
def test_normalize_text_removes_diacritics_and_noise():
    assert wt.normalize_text("Đà   Lạt!!!") == "da lat"
    assert wt.normalize_text("  HỒ–CHÍ–MINH ") == "ho chi minh"


def test_canonicalize_city_aliases():
    assert wt.canonicalize_city_name("Saigon") == "ho chi minh city"
    assert wt.canonicalize_city_name("HCMC") == "ho chi minh city"
    assert wt.canonicalize_city_name("Đà Nẵng") == "da nang"


# ============================================================
# Tests: geocoding behavior
# ============================================================
def test_get_coordinates_handles_diacritics_and_ranking(monkeypatch):
    """
    Ensure:
    - diacritics are handled
    - VN result is preferred
    - ranking logic is exercised (not first-hit)
    """
    calls = []

    def fake_get(url, params, timeout):
        calls.append((params["name"], params["language"]))

        # Only return results for normalized / canonical forms
        if params["name"] in {"da lat", "da lat city"}:
            return FakeResponse({
                "results": [
                    {
                        "name": "Dalat",
                        "latitude": 43.0,
                        "longitude": -79.0,
                        "country": "Canada",
                        "country_code": "CA",
                        "population": 50000,
                    },
                    {
                        "name": "Đà Lạt",
                        "latitude": 11.9342,
                        "longitude": 108.4384,
                        "country": "Vietnam",
                        "country_code": "VN",
                        "population": 230000,
                    },
                ]
            })

        return FakeResponse({"results": []})

    monkeypatch.setattr(requests, "get", fake_get)

    coords = wt.get_coordinates("Đà Lạt")

    assert coords is not None
    assert coords["country_code"] == "VN"
    assert coords["lat"] == 11.9342
    assert coords["lon"] == 108.4384

    # Verify fallback attempts actually happened
    attempted_names = {name for name, _ in calls}
    assert "da lat" in attempted_names or "đà lạt" in attempted_names


def test_get_coordinates_returns_none_when_unresolved(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse({"results": []})

    monkeypatch.setattr(requests, "get", fake_get)

    coords = wt.get_coordinates("ThisCityDoesNotExist")
    assert coords is None


# ============================================================
# Tests: weather integration
# ============================================================
def test_get_current_weather_success(monkeypatch):
    """
    Full happy-path test:
    - geocoding resolves
    - weather API returns current_weather
    """

    def fake_get(url, params, timeout):
        if "geocoding-api" in url:
            return FakeResponse({
                "results": [
                    {
                        "name": "Đà Lạt",
                        "latitude": 11.9342,
                        "longitude": 108.4384,
                        "country": "Vietnam",
                        "country_code": "VN",
                        "population": 230000,
                    }
                ]
            })

        if "api.open-meteo.com" in url:
            return FakeResponse({
                "current_weather": {
                    "temperature": 17.4,
                    "windspeed": 10.7,
                    "weathercode": 3,
                    "is_day": 0,
                }
            })

        pytest.fail("Unexpected URL called")

    monkeypatch.setattr(requests, "get", fake_get)

    res = wt.get_current_weather("Đà Lạt")

    assert res["status"] == "success"
    assert res["location"]["resolved_name"] == "Đà Lạt"
    assert res["location"]["country"] == "Vietnam"
    assert res["weather"]["temperature"] == 17.4
    assert res["weather"]["description"] == "Overcast"


def test_get_current_weather_invalid_unit():
    res = wt.get_current_weather("Paris", unit="kelvin")
    assert res["status"] == "error"
    assert "Invalid unit" in res["message"]


def test_get_current_weather_location_not_found(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse({"results": []})

    monkeypatch.setattr(requests, "get", fake_get)

    res = wt.get_current_weather("Atlantis")
    assert res["status"] == "error"
    assert "Location not found" in res["message"]
