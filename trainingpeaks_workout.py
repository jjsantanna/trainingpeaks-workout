#!/usr/bin/env python3
"""
trainingpeaks_workout.py — Fetch today's planned workout from TrainingPeaks
and send it to Telegram.

Usage:
    python3 trainingpeaks_workout.py             # sends to Telegram
    python3 trainingpeaks_workout.py --print     # print only, no Telegram
    python3 trainingpeaks_workout.py --date 2026-03-15  # specific date
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import re
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
# Credentials file: { "trainingpeaks": { "username": "...", "password": "..." },
#                     "telegram": { "token": "...", "chat_id": "..." } }
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT    = os.environ.get("TELEGRAM_CHAT_ID", "")

# Authoritative type map extracted from TrainingPeaks app JS
WORKOUT_TYPES = {
    1:   "🏊 Swim",
    2:   "🚴 Bike",
    3:   "🏃 Run",
    4:   "🏅 Brick",
    5:   "🏋️ Crosstrain",
    6:   "🏆 Race",
    7:   "😴 Day Off",
    8:   "🚵 Mountain Bike",
    9:   "💪 Strength",
    10:  "⚡ Custom",
    11:  "🎿 XC-Ski",
    12:  "🚣 Rowing",
    13:  "🚶 Walk",
    100: "🏅 Other",
}


def load_credentials():
    creds = {}
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE) as f:
            creds = json.load(f)
    return creds


def get_telegram_config(creds):
    """Return (token, chat_id) — env vars take priority over credentials file."""
    token   = TELEGRAM_TOKEN or creds.get("telegram", {}).get("token", "")
    chat_id = TELEGRAM_CHAT  or creds.get("telegram", {}).get("chat_id", "")
    return token, chat_id


def login_and_get_token(username, password):
    """Login to TrainingPeaks and return Bearer access token + user ID."""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Step 1: Get CSRF token
    req = urllib.request.Request("https://home.trainingpeaks.com/login", headers=headers)
    resp = opener.open(req)
    html = resp.read().decode("utf-8", errors="ignore")
    csrf = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', html)
    if not csrf:
        raise RuntimeError("Could not extract CSRF token from login page")

    # Step 2: Login
    login_data = urllib.parse.urlencode({
        "__RequestVerificationToken": csrf.group(1),
        "Username": username,
        "Password": password,
        "RememberMe": "true",
        "CaptchaToken": "",
        "CaptchaHidden": "true",
        "Attempts": "",
    }).encode()
    login_req = urllib.request.Request(
        "https://home.trainingpeaks.com/login",
        data=login_data,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://home.trainingpeaks.com/login"},
    )
    opener.open(login_req)

    # Step 3: Get Bearer token
    token_req = urllib.request.Request(
        "https://tpapi.trainingpeaks.com/users/v3/token",
        headers={**headers, "Accept": "application/json",
                 "Origin": "https://app.trainingpeaks.com",
                 "Referer": "https://app.trainingpeaks.com/"},
    )
    token_resp = opener.open(token_req)
    token_data = json.loads(token_resp.read().decode())

    if not token_data.get("success"):
        raise RuntimeError(f"Token fetch failed: {token_data}")

    access_token = token_data["token"]["access_token"]

    # Step 4: Get user ID
    user_req = urllib.request.Request(
        "https://tpapi.trainingpeaks.com/users/v3/user",
        headers={"Authorization": f"Bearer {access_token}",
                 "Accept": "application/json",
                 "Origin": "https://app.trainingpeaks.com"},
    )
    user_resp = urllib.request.urlopen(user_req)
    user_data = json.loads(user_resp.read().decode())
    user_id = user_data["user"]["userId"]

    return access_token, user_id


def fetch_workouts(access_token, user_id, date_str):
    """Fetch planned workouts for a given date."""
    url = (f"https://tpapi.trainingpeaks.com/fitness/v6/athletes"
           f"/{user_id}/workouts/{date_str}/{date_str}")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Origin": "https://app.trainingpeaks.com",
    })
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())


def fetch_threshold_speed(access_token, user_id):
    """Return threshold running speed in m/s from athlete settings, or None."""
    url = f"https://tpapi.trainingpeaks.com/fitness/v1/athletes/{user_id}/settings"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Origin": "https://app.trainingpeaks.com",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        for zone in data.get("speedZones", []):
            if zone.get("threshold"):
                return zone["threshold"]   # m/s
    except Exception:
        pass
    return None


def fmt_duration(hours):
    if not hours:
        return None
    total_min = int(round(hours * 60))
    h, m = divmod(total_min, 60)
    return f"{h}h {m:02d}min" if h else f"{m} min"


def fmt_distance(workout):
    """Return estimated distance string, preferring planned value, falling back to velocity × time."""
    dist_m = workout.get("distancePlanned")  # already in metres when present
    if not dist_m:
        velocity = workout.get("velocityPlanned")   # m/s
        duration = workout.get("totalTimePlanned")   # hours
        if velocity and duration:
            dist_m = velocity * duration * 3600      # metres
    if not dist_m:
        return None
    dist_km = dist_m / 1000
    return f"{dist_km:.1f} km"


def pct_to_pace(pct, threshold_speed_ms):
    """Convert % of threshold speed to pace string (min:ss /km)."""
    if not pct or not threshold_speed_ms:
        return None
    speed = threshold_speed_ms * (pct / 100.0)   # m/s
    pace_sec_per_km = 1000.0 / speed              # sec/km
    mins = int(pace_sec_per_km // 60)
    secs = int(pace_sec_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def fmt_intensity(lo, hi, threshold_speed_ms, intensity_metric):
    """Return a human-readable intensity string: avg pace for running, % for others."""
    if not lo and not hi:
        return ""
    if intensity_metric and "pace" in intensity_metric.lower() and threshold_speed_ms:
        avg_pct = ((lo or hi) + (hi or lo)) / 2.0
        pace = pct_to_pace(avg_pct, threshold_speed_ms)
        return f"~{pace}" if pace else ""
    return f"{lo}-{hi}%" if lo and hi else ""


def step_distance_km(step, threshold_speed_ms, intensity_metric):
    """Return distance in km for a single step, or None if not calculable.

    Handles three cases:
      1. Step length is a distance unit (meter / kilometer) → direct read.
      2. Step length is time + pace-based metric + threshold → velocity × time.
      3. Step length is time + HR/power metric → cannot estimate, return None.
    """
    slen  = step.get("length", {})
    unit  = slen.get("unit", "")
    value = slen.get("value") or 0

    # ── Case 1: distance-based step ──────────────────────────────────────────
    if unit == "meter":
        return value / 1000.0
    if unit == "kilometer":
        return float(value)

    # ── Case 2 / 3: time-based step ─────────────────────────────────────────
    if unit == "second":
        secs = value
    elif unit == "minute":
        secs = value * 60
    else:
        return None   # unknown unit

    if not secs:
        return None

    t  = step.get("targets", [{}])[0]
    lo = t.get("minValue")
    hi = t.get("maxValue")

    if intensity_metric and "pace" in intensity_metric.lower() and threshold_speed_ms:
        avg_pct = ((lo or hi) + (hi or lo)) / 2.0
        if avg_pct:
            speed = threshold_speed_ms * (avg_pct / 100.0)   # m/s
            return speed * secs / 1000.0                      # km

    return None


def fmt_structure(structure, threshold_speed_ms=None):
    """Summarise workout structure. Returns (formatted_str, total_distance_km)."""
    if not structure or not structure.get("structure"):
        return None, None

    intensity_metric = structure.get("primaryIntensityMetric", "")
    lines = []
    total_km = 0.0
    has_distance = False

    for block in structure["structure"]:
        steps = block.get("steps", [])
        reps  = block.get("length", {})

        if block.get("type") == "repetition":
            count = reps.get("value", 1)
            parts = []
            block_km = 0.0
            for step in steps:
                slen = step.get("length", {})
                t    = step.get("targets", [{}])[0]
                lo, hi = t.get("minValue"), t.get("maxValue")
                # human-readable duration label
                unit  = slen.get("unit", "")
                value = slen.get("value") or 0
                if unit in ("meter", "kilometer"):
                    d_m = value if unit == "meter" else value * 1000
                    dur = f"{int(d_m)}m" if d_m < 1000 else f"{d_m/1000:.1f}km"
                else:
                    secs = value if unit == "second" else value * 60
                    dur  = f"{int(secs//60)}'" if secs >= 60 else f"{int(secs)}\""
                intensity = fmt_intensity(lo, hi, threshold_speed_ms, intensity_metric)
                d_km = step_distance_km(step, threshold_speed_ms, intensity_metric)
                if d_km is not None:
                    block_km += d_km
                parts.append(f"{dur} {intensity}".strip())
            block_total = block_km * count
            total_km += block_total
            if block_km:
                has_distance = True
                dist_str = f"  ≈{block_total:.2f} km"
            else:
                dist_str = ""
            lines.append(f"  🔁 {count}x ({' / '.join(parts)}){dist_str}")
        else:
            for step in steps:
                slen = step.get("length", {})
                t    = step.get("targets", [{}])[0]
                lo, hi = t.get("minValue"), t.get("maxValue")
                # human-readable duration label
                unit  = slen.get("unit", "")
                value = slen.get("value") or 0
                if unit in ("meter", "kilometer"):
                    d_m = value if unit == "meter" else value * 1000
                    dur = f"{int(d_m)}m" if d_m < 1000 else f"{d_m/1000:.1f}km"
                else:
                    secs = value if unit == "second" else value * 60
                    dur  = f"{int(secs//60)}'" if secs >= 60 else f"{int(secs)}\""
                intensity = fmt_intensity(lo, hi, threshold_speed_ms, intensity_metric)
                d_km = step_distance_km(step, threshold_speed_ms, intensity_metric)
                name = step.get("name", "")
                if d_km is not None:
                    total_km += d_km
                    has_distance = True
                    dist_str = f"  ≈{d_km:.2f} km"
                else:
                    dist_str = ""
                lines.append(f"  • {name}: {dur} {intensity}{dist_str}".strip())

    total = total_km if has_distance else None
    return "\n".join(lines), total


def format_workout_message(workout, date_str, threshold_speed_ms=None):
    """Format a single workout into a Telegram-friendly message."""
    title       = workout.get("title", "Untitled workout")
    wtype_id    = workout.get("workoutTypeValueId", 0)
    wtype       = WORKOUT_TYPES.get(wtype_id, "🏅 Workout")
    sport_emoji = wtype.split()[0]   # just the emoji for the header
    duration              = fmt_duration(workout.get("totalTimePlanned"))
    tss                   = workout.get("tssPlanned")
    coach_note            = workout.get("coachComments") or ""
    desc                  = workout.get("description") or ""
    structure, struct_km  = fmt_structure(workout.get("structure"), threshold_speed_ms)
    # Prefer structure-derived distance; fall back to velocity × time
    if struct_km:
        distance = f"{struct_km:.1f} km"
    else:
        distance = fmt_distance(workout)
    completed = workout.get("completed")

    lines = [f"{sport_emoji} *Workout of the Day — {date_str}*", "",
             f"{wtype}  *{title}*"]

    stats = []
    if duration:  stats.append(f"⏱ {duration}")
    if tss:       stats.append(f"TSS: {tss:.0f}")
    if stats:    lines.append("  ".join(stats))

    if completed is True:
        lines.append("✅ Already completed!")
    elif completed is False:
        lines.append("⬜ Not yet completed")

    if coach_note:
        lines += ["", f"📋 Coach note:", coach_note.strip()]
    elif desc:
        lines += ["", desc.strip()[:400]]

    if structure:
        lines += ["", "📊 Structure:", structure]
        if distance:
            lines.append(f"  ──────────────────")
            lines.append(f"  📍 Total: ~{distance}")

    return "\n".join(lines)


def send_telegram(message, token, chat_id):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
        if not result.get("ok"):
            print(f"Telegram error: {result}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="TrainingPeaks daily workout")
    parser.add_argument("--date",  default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args()

    creds    = load_credentials()
    tp_creds = creds.get("trainingpeaks", {})
    username = os.environ.get("TP_USERNAME") or tp_creds.get("username")
    password = os.environ.get("TP_PASSWORD") or tp_creds.get("password")
    if not username or not password:
        print("❌ No TrainingPeaks credentials found.\n"
              "   Set TP_USERNAME / TP_PASSWORD env vars, or add to credentials.json.",
              file=sys.stderr)
        sys.exit(1)
    tg_token, tg_chat = get_telegram_config(creds)
    if not args.print_only and (not tg_token or not tg_chat):
        print("❌ No Telegram config found.\n"
              "   Set TELEGRAM_TOKEN / TELEGRAM_CHAT_ID env vars, or add to credentials.json.",
              file=sys.stderr)
        sys.exit(1)

    print(f"🔐 Logging in as {username}...")
    access_token, user_id = login_and_get_token(username, password)
    print(f"✅ Logged in (userId={user_id})")

    print(f"📅 Fetching workouts for {args.date}...")
    workouts = fetch_workouts(access_token, user_id, args.date)
    threshold_speed = fetch_threshold_speed(access_token, user_id)
    if threshold_speed:
        pace_sec = 1000.0 / threshold_speed
        print(f"⚡ Threshold speed: {threshold_speed:.3f} m/s  "
              f"({int(pace_sec//60)}:{int(pace_sec%60):02d}/km)")

    if not workouts:
        msg = f"🗓 No workout planned for {args.date}. Rest day! 🛋️"
        print(msg)
        if not args.print_only:
            send_telegram(msg)
        return

    for w in workouts:
        msg = format_workout_message(w, args.date, threshold_speed)
        print("\n" + msg)
        if not args.print_only:
            print("\n📲 Sending to Telegram...")
            send_telegram(msg, tg_token, tg_chat)
            print("✅ Sent!")


if __name__ == "__main__":
    main()
