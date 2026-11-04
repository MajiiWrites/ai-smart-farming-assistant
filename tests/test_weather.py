"""Weather service tests: manual mode is offline-safe; API mode is mocked."""
import pytest

from app.services import weather as W
from app.services.weather import WeatherError, get_weather


def test_manual_tmax_tmin():
    out = get_weather(tmax=38.0, tmin=24.0, humidity=55.0)
    assert out == {"tmax": 38.0, "tmin": 24.0, "tmean": 31.0,
                   "humidity": 55.0, "source": "manual", "city": None}


def test_manual_single_temp():
    """The web form sends one temperature -> treated as the daily mean."""
    out = get_weather(temp_c=30.0)
    assert out["tmean"] == 30.0
    assert out["tmax"] == 33.0 and out["tmin"] == 27.0
    assert out["source"] == "manual"


def test_manual_validates():
    with pytest.raises(WeatherError, match="higher than the minimum"):
        get_weather(tmax=20.0, tmin=25.0)
    with pytest.raises(WeatherError, match="between 0 and 100"):
        get_weather(tmax=38.0, tmin=24.0, humidity=150.0)
    with pytest.raises(WeatherError, match="No city and no temperature"):
        get_weather()


def test_unknown_city():
    with pytest.raises(WeatherError, match="Unknown city"):
        get_weather(city="Atlantis")


def test_open_meteo_parsing_mocked(monkeypatch):
    """Mock requests.get: no network, deterministic payload."""

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"daily": {
                "temperature_2m_max": [36.5],
                "temperature_2m_min": [24.2],
                "relative_humidity_2m_mean": [48.0],
            }}

    monkeypatch.setattr(W.requests, "get",
                        lambda *a, **k: FakeResp())
    out = get_weather(city="Multan")
    assert out["tmax"] == 36.5 and out["tmin"] == 24.2
    # (36.5+24.2)/2 = 30.35; binary float rounds the 1-dp display to 30.4
    assert out["tmean"] == pytest.approx(30.35, abs=0.06)
    assert out["humidity"] == 48.0
    assert out["source"] == "open-meteo"
    assert out["city"] == "Multan"


def test_open_meteo_failure_is_friendly(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(W.requests, "get", boom)
    with pytest.raises(WeatherError, match="Could not reach the weather"):
        get_weather(city="Lahore")


def test_city_latlon_table():
    assert W.CITY_LATLON["bahawalpur"] == (29.38, 71.68)
    assert len(W.CITY_LATLON) == 8
