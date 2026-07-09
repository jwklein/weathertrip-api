from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

@app.route("/weather/current")
def current():
    lat = request.args.get("latitude")
    lon = request.args.get("longitude")
    tz  = request.args.get("timezone", "America/New_York")

    r = requests.get(OPEN_METEO, params={
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
        "forecast_days": 1,
        "timezone": tz,
    }, timeout=10)
    r.raise_for_status()
    return jsonify(r.json())

@app.route("/weather/forecast")
def forecast():
    lat        = request.args.get("latitude")
    lon        = request.args.get("longitude")
    tz         = request.args.get("timezone", "America/New_York")
    start_date = request.args.get("start_date")
    end_date   = request.args.get("end_date")

    r = requests.get(OPEN_METEO, params={
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 7,
        "timezone": tz,
    }, timeout=10)
    r.raise_for_status()
    return jsonify(r.json())

@app.route("/weather/extremes")
def extremes():
    lat   = request.args.get("latitude")
    lon   = request.args.get("longitude")
    tz    = request.args.get("timezone", "America/New_York")
    years = int(request.args.get("years", 10))

    from datetime import date, timedelta
    end   = date.today()
    start = date(end.year - years, end.month, end.day)

    r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
        "latitude":  lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_gusts_10m_max",
            "snowfall_sum",
        ]),
        "timezone": tz,
    }, timeout=30)
    r.raise_for_status()
    data  = r.json()
    daily = data.get("daily", {})
    dates = daily.get("time", [])

    def extreme(values, mode="max"):
        pairs = [(d, v) for d, v in zip(dates, values) if v is not None]
        if not pairs:
            return None
        pick = max if mode == "max" else min
        date_val, value = pick(pairs, key=lambda p: p[1])
        return {"date": date_val, "value": value}

    return jsonify({
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "extremes": {
            "hottest_day":  extreme(daily.get("temperature_2m_max", []), "max"),
            "coldest_day":  extreme(daily.get("temperature_2m_min", []), "min"),
            "wettest_day":  extreme(daily.get("precipitation_sum",  []), "max"),
            "windiest_day": extreme(daily.get("wind_gusts_10m_max", []), "max"),
            "snowiest_day": extreme(daily.get("snowfall_sum",       []), "max"),
        }
    })

if __name__ == "__main__":
    app.run(host="172.17.35.50", port=5001, debug=False)
