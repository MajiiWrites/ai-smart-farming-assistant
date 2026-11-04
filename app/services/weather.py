"""Weather service: live Open-Meteo fetch or manual temperature input.

WHY two modes: the irrigation form lets the farmer either pick a city
(live 3-day forecast, no API key needed) or type the temperature directly
(works offline, works for villages not in our city list). The route treats
a WeatherError as "fall back to the manual form" — so failures are always
friendly, never a 500.

Open-Meteo (https://open-meteo.com) needs no key; we request only the
daily max/min temperature and mean relative humidity for 3 days and use
day 0 (today).
"""

import requests

# WHY these cities: the major agricultural districts of Punjab/Sindh/KPK
# where the target users farm. (lat, lon) in decimal degrees.
CITY_LATLON = {
    "bahawalpur": (29.38, 71.68),
    "multan": (30.16, 71.52),
    "lahore": (31.55, 74.35),
    "karachi": (24.86, 67.01),
    "faisalabad": (31.45, 73.14),
    "peshawar": (34.00, 71.58),
    "hyderabad": (25.38, 68.37),
    "rawalpindi": (33.60, 73.04),
}

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_REQUEST_TIMEOUT = 8  # seconds; WHY 8: mobile networks in rural areas are
# slow, but the form must not hang — 8 s is the compromise.


class WeatherError(Exception):
    """Raised when weather cannot be obtained (bad city, no network, ...).

    The message is written for the farmer ("check your internet, or type
    the temperature yourself"), because routes show it in a flash message.
    """


def _manual(tmax=None, tmin=None, temp_c=None, humidity=None, city=None):
    """Build the result dict from hand-typed values (source='manual')."""
    if tmax is not None and tmin is not None:
        tmax, tmin = float(tmax), float(tmin)
        if tmax <= tmin:
            raise WeatherError(
                "Maximum temperature must be higher than the minimum."
            )
        tmean = (tmax + tmin) / 2.0
    elif temp_c is not None:
        # The form has a single "temperature" box: treat it as the daily
        # mean and reconstruct a plausible max/min around it (±3 °C is the
        # typical diurnal half-range on the Punjab plains in mild season).
        tmean = float(temp_c)
        tmax, tmin = tmean + 3.0, tmean - 3.0
    else:
        raise WeatherError(
            "No temperature given. Type the temperature or pick a city."
        )
    hum = float(humidity) if humidity is not None else None
    if hum is not None and not (0 <= hum <= 100):
        raise WeatherError("Humidity must be between 0 and 100 %.")
    return {
        "tmax": round(tmax, 1),
        "tmin": round(tmin, 1),
        "tmean": round(tmean, 1),
        "humidity": round(hum, 1) if hum is not None else None,
        "source": "manual",
        "city": city,
    }


def _from_open_meteo(city):
    """Fetch today's forecast for a known city from Open-Meteo."""
    key = city.strip().lower()
    if key not in CITY_LATLON:
        known = ", ".join(sorted(CITY_LATLON))
        raise WeatherError(
            f"Unknown city '{city}'. Choose one of: {known} — "
            "or type the temperature manually."
        )
    lat, lon = CITY_LATLON[key]
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,"
                 "relative_humidity_2m_mean",
        "forecast_days": 3,
        "timezone": "auto",
    }
    try:
        resp = requests.get(_OPEN_METEO_URL, params=params,
                            timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        daily = resp.json()["daily"]
    except requests.RequestException as exc:
        # WHY catch broadly: DNS failure, timeout, 5xx — the farmer gets
        # the same actionable message for all of them.
        raise WeatherError(
            "Could not reach the weather service. Check your internet "
            f"connection, or type the temperature manually. ({exc})"
        ) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise WeatherError(
            "The weather service returned an unexpected response. "
            "Please type the temperature manually."
        ) from exc
    try:
        tmax = float(daily["temperature_2m_max"][0])
        tmin = float(daily["temperature_2m_min"][0])
        hum_raw = daily["relative_humidity_2m_mean"][0]
        humidity = float(hum_raw) if hum_raw is not None else None
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError(
            "The weather service returned an unexpected response. "
            "Please type the temperature manually."
        ) from exc
    return {
        "tmax": round(tmax, 1),
        "tmin": round(tmin, 1),
        "tmean": round((tmax + tmin) / 2.0, 1),
        "humidity": round(humidity, 1) if humidity is not None else None,
        "source": "open-meteo",
        "city": city.strip(),
    }


def get_weather(city=None, tmax=None, tmin=None, temp_c=None, humidity=None):
    """Get weather for irrigation: manual values win, else live API.

    Args:
        city: e.g. "Multan" (case-insensitive; must be in CITY_LATLON).
        tmax/tmin: hand-typed daily max/min °C (both required together).
        temp_c: single hand-typed temperature °C, used as the daily mean
            when tmax/tmin are not given (this is what the web form sends).
        humidity: hand-typed relative humidity % (optional).

    Priority: explicit tmax+tmin > temp_c > city lookup.
    Manual input always returns source='manual' and never touches the
    network — WHY: a farmer in a low-signal area must still get an answer.

    Returns:
        dict {tmax, tmin, tmean, humidity, source, city}.

    Raises:
        WeatherError: on bad input or unreachable/unparseable API.
    """
    if (tmax is not None and tmin is not None) or temp_c is not None:
        return _manual(tmax=tmax, tmin=tmin, temp_c=temp_c,
                       humidity=humidity, city=city)
    if city:
        return _from_open_meteo(city)
    raise WeatherError(
        "No city and no temperature given. Pick a city or type the "
        "temperature."
    )
