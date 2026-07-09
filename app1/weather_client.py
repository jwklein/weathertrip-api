import requests
import os

def _base():
    host = os.environ.get("WEATHER_HOST", "localhost")
    port = os.environ.get("WEATHER_PORT", "5001")
    return f"http://{host}:{port}"
    
def get_current_weather(lat, lon, timezone):
    r = requests.get(f"{_base()}/weather/current", params={
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        }, timeout=10)
    r.raise_for_status()
    return r.json()

def get_trip_forecast(lat, lon, timezone):
    r = requests.get(f"{_base()}/weather/forecast", params={
    "latitude": lat,
    "longitude": lon,
    "timezone": timezone,
    }, timeout=10)
    r.raise_for_status()
    return r.json()

def get_extremes(lat, lon, timezone, years=10):
    r = requests.get(f"{_base()}/weather/extremes", params={
        "latitude":  lat,
        "longitude": lon,
        "timezone":  timezone,
        "years":     years,
    }, timeout=35)   # longer timeout — historical query is slow
    r.raise_for_status()
    return r.json()
