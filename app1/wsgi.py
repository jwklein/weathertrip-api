from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix
from database import get_db, close_db
from weather_client import get_current_weather, get_trip_forecast, get_extremes
import os

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.teardown_appcontext(close_db)

# ── GET /api/locations ─────────────────────────────────────

@app.route("/api/locations", methods=["GET"])
def get_locations():
    cur = get_db().cursor(dictionary=True)
    cur.execute("SELECT id, name FROM locations")
    return jsonify(locations=cur.fetchall())

# ── GET /api/locations/<id> ────────────────────────────────

@app.route("/api/locations/<int:id>", methods=["GET"])
def get_location(id):
    cur = get_db().cursor(dictionary=True)
    cur.execute(
        "SELECT id, name, latitude, longitude, timezone FROM locations WHERE id=%s",
        (id,)
    )
    row = cur.fetchone()
    if not row:
        return jsonify(error="not found"), 404
    return jsonify(row)

# ── POST /api/locations ────────────────────────────────────

@app.route("/api/locations", methods=["POST"])
def create_location():
    data = request.get_json()
    name = data.get("name")
    lat  = data.get("latitude")
    lon  = data.get("longitude")
    tz   = data.get("timezone", "America/New_York")

    if not name:
        return jsonify(status="fail-name required"), 400
    if lat is None or not (-90 <= float(lat) <= 90):
        return jsonify(status="fail-invalid latitude"), 400
    if lon is None or not (-180 <= float(lon) <= 180):
        return jsonify(status="fail-invalid longitude"), 400

    db  = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO locations (name, latitude, longitude, timezone) VALUES (%s,%s,%s,%s)",
            (name, lat, lon, tz)
        )
        db.commit()
    except Exception as e:
        if "Duplicate" in str(e) or "1062" in str(e):
            return jsonify(status="fail-name must be unique"), 409
        return jsonify(status=f"fail-{e}"), 500
    return jsonify(status="ok"), 201

# ── GET /api/weather/current/<location_id> ─────────────────

@app.route("/api/weather/current/<int:location_id>", methods=["GET"])
def current_weather(location_id):
    cur = get_db().cursor(dictionary=True)
    cur.execute(
        "SELECT latitude, longitude, timezone FROM locations WHERE id=%s",
        (location_id,)
    )
    loc = cur.fetchone()
    if not loc:
        return jsonify(error="location not found"), 404
    try:
        data = get_current_weather(loc["latitude"], loc["longitude"], loc["timezone"])
    except Exception as e:
        return jsonify(error=f"weather service error: {e}"), 502
    return jsonify(data)

# ── GET /api/trips ─────────────────────────────────────────

@app.route("/api/trips", methods=["GET"])
def get_trips():
    cur = get_db().cursor(dictionary=True)
    cur.execute("SELECT id, title FROM trips")
    return jsonify(trips=cur.fetchall())

# ── GET /api/trips/<id> ────────────────────────────────────

@app.route("/api/trips/<int:id>", methods=["GET"])
def get_trip(id):
    cur = get_db().cursor(dictionary=True)
    cur.execute("""
        SELECT t.id, t.title, l.name AS location,
               t.start_date, t.end_date, t.notes
        FROM trips t
        JOIN locations l ON t.location_id = l.id
        WHERE t.id = %s
    """, (id,))
    trip = cur.fetchone()
    if not trip:
        return jsonify(error="not found"), 404

    cur.execute("""
        SELECT l.latitude, l.longitude, l.timezone
        FROM locations l
        JOIN trips t ON l.id = t.location_id
        WHERE t.id = %s
    """, (id,))
    loc = cur.fetchone()

    try:
        forecast_raw = get_trip_forecast(
            loc["latitude"], loc["longitude"], loc["timezone"]
        )
        daily = forecast_raw.get("daily", {})
        dates  = daily.get("time", [])
        tmax   = daily.get("temperature_2m_max", [])
        tmin   = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_probability_max", [])
        forecast = [
            {
                "date": d,
                "temperature_max": mx,
                "temperature_min": mn,
                "precipitation_probability": pr,
            }
            for d, mx, mn, pr in zip(dates, tmax, tmin, precip)
        ]
    except Exception as e:
        forecast = []

    # convert dates to strings for JSON serialization
    trip["start_date"] = str(trip["start_date"])
    trip["end_date"]   = str(trip["end_date"])

    return jsonify(trip=trip, forecast=forecast)

# ── POST /api/trips ────────────────────────────────────────

@app.route("/api/trips", methods=["POST"])
def create_trip():
    data        = request.get_json()
    location_id = data.get("location_id")
    title       = data.get("title")
    start_date  = data.get("start_date")
    end_date    = data.get("end_date")
    notes       = data.get("notes", "")

    if not location_id:
        return jsonify(status="fail-location_id required"), 400
    if not title:
        return jsonify(status="fail-title required"), 400
    if not start_date or not end_date:
        return jsonify(status="fail-dates required"), 400

    from datetime import datetime
    try:
        s = datetime.strptime(start_date, "%Y-%m-%d")
        e = datetime.strptime(end_date,   "%Y-%m-%d")
        if s > e:
            return jsonify(status="fail-start_date must be before end_date"), 400
    except ValueError:
        return jsonify(status="fail-invalid date format"), 400

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM locations WHERE id=%s", (location_id,))
    if not cur.fetchone():
        return jsonify(status="fail-location not found"), 404

    cur2 = db.cursor()
    try:
        cur2.execute(
            "INSERT INTO trips (location_id, title, start_date, end_date, notes) VALUES (%s,%s,%s,%s,%s)",
            (location_id, title, start_date, end_date, notes)
        )
        db.commit()
    except Exception as e:
        if "Duplicate" in str(e) or "1062" in str(e):
            return jsonify(status="fail-title must be unique"), 409
        return jsonify(status=f"fail-{e}"), 500
    return jsonify(status="ok"), 201

# ── POST /api/trips/<id>/note ──────────────────────────────

@app.route("/api/trips/<int:id>/note", methods=["POST"])
def add_note(id):
    data      = request.get_json()
    note      = data.get("note", "")
    overwrite = str(data.get("overwrite", "false")).lower() == "true"

    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT notes FROM trips WHERE id=%s", (id,))
    row = cur.fetchone()
    if not row:
        return jsonify(status="fail-trip not found"), 404

    new_note = note if overwrite else f"{row['notes'] or ''}\n{note}".strip()
    cur2 = db.cursor()
    cur2.execute("UPDATE trips SET notes=%s WHERE id=%s", (new_note, id))
    db.commit()
    return jsonify(status="ok")

# ── POST /api/admin/reset-demo-data ───────────────────────

@app.route("/api/admin/reset-demo-data", methods=["POST"])
def reset_demo():
    data = request.get_json()
    if not data.get("confirm"):
        return jsonify(status="fail-confirm required"), 400

    db  = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM trips")
    cur.execute("DELETE FROM locations")

    locations = [
        ("Oxford, OH",  39.507, -84.745, "America/New_York"),
        ("Boston, MA",  42.360, -71.058, "America/New_York"),
        ("Denver, CO",  39.739, -104.984, "America/Denver"),
    ]

    loc_ids = []
    for name, lat, lon, tz in locations:
        cur.execute(
            "INSERT INTO locations (name, latitude, longitude, timezone) VALUES (%s,%s,%s,%s)",
            (name, lat, lon, tz)
        )
        loc_ids.append(cur.lastrowid)    

    trips = [
        (loc_ids[0], "May Cyber Conference", "2026-05-01", "2026-05-03", "Check rain and wind"),
        (loc_ids[1], "Aruba",                "2026-06-10", "2026-06-17", ""),
    ]

    for loc_id, title, start, end, notes in trips:
        cur.execute(
            "INSERT INTO trips (location_id, title, start_date, end_date, notes) VALUES (%s,%s,%s,%s,%s)",
            (loc_id, title, start, end, notes)
        )
    db.commit()
    return jsonify(status="reset complete", locations_created=3, trips_created=2)

# -- GET /api/locations/<int:id>/extremes?[years]
@app.route("/api/locations/<int:id>/extremes", methods=["GET"])
def location_extremes(id):
    cur = get_db().cursor(dictionary=True)
    cur.execute(
        "SELECT name, latitude, longitude, timezone FROM locations WHERE id=%s",
        (id,)
    )
    loc = cur.fetchone()
    if not loc:
        return jsonify(error="location not found"), 404

    years = request.args.get("years", 10, type=int)
    try:
        data = get_extremes(loc["latitude"], loc["longitude"], loc["timezone"], years)
    except Exception as e:
        return jsonify(error=f"weather service error: {e}"), 502

    return jsonify(location=loc["name"], **data)

# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
