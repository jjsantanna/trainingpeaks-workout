#!/usr/bin/env python3
"""
tp_structured_workouts.py — Create structured workouts on TrainingPeaks
with proper step-by-step format that syncs to Garmin/watch.

Key findings (reverse-engineered from TP internal API):
- primaryIntensityMetric must be "percentOfThresholdPace" for running pace zones
  (NOT "percentOfThresholdSpeed" — that returns HTTP 400)
- "rpe" also works but shows RPE % not pace
- Time-based steps must use unit: "second" (NOT "minute" — returns HTTP 400)
- Outer step blocks: type="step", length={value:1, unit:"repetition"}
- Inner steps inside repetition blocks need explicit type="step"
- Inner steps inside plain step blocks do NOT have type field
- begin/end are cumulative distance markers in metres (optional but recommended)
- athleteId must be included in the POST body

Threshold pace: 5:08/km (3.247 m/s) — fetched from TP athlete settings
Zone guide (% of threshold pace → actual pace):
  60–65%  → 7:54–8:33/km   recovery jog
  65–70%  → 7:20–7:54/km   very easy
  70–75%  → 6:51–7:20/km   warm-up / cool-down
  72–78%  → 6:35–7:08/km   zone 2 easy aerobic
  85–88%  → 5:50–6:02/km   conservative HM pace
  90–95%  → 5:24–5:42/km   HM race pace
  95–102% → 5:02–5:24/km   HM final push
  103–107%→ 4:48–4:59/km   5K / VO2max pace
"""

import json, os, re, urllib.request, urllib.parse, http.cookiejar

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "../private/credentials.json")


# ── Auth ──────────────────────────────────────────────────────────────────────

def login(username, password):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"}
    html = opener.open(urllib.request.Request(
        "https://home.trainingpeaks.com/login", headers=h)).read().decode()
    csrf = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', html).group(1)
    opener.open(urllib.request.Request(
        "https://home.trainingpeaks.com/login",
        data=urllib.parse.urlencode({
            "__RequestVerificationToken": csrf, "Username": username,
            "Password": password, "RememberMe": "true",
            "CaptchaToken": "", "CaptchaHidden": "true", "Attempts": ""
        }).encode(),
        headers={**h, "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://home.trainingpeaks.com/login"}))
    td = json.loads(opener.open(urllib.request.Request(
        "https://tpapi.trainingpeaks.com/users/v3/token",
        headers={**h, "Accept": "application/json",
                 "Origin": "https://app.trainingpeaks.com",
                 "Referer": "https://app.trainingpeaks.com/"})).read().decode())
    token = td["token"]["access_token"]
    uid = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://tpapi.trainingpeaks.com/users/v3/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                 "Origin": "https://app.trainingpeaks.com"})).read().decode())["user"]["userId"]
    return token, uid


# ── Helpers ───────────────────────────────────────────────────────────────────

def step_block(name, unit, value, lo, hi, cls, begin, end):
    """A single named step block (warm-up, main effort, cool-down, etc.)"""
    return {
        "type": "step",
        "length": {"value": 1, "unit": "repetition"},
        "steps": [{
            "name": name,
            "length": {"value": value, "unit": unit},
            "targets": [{"minValue": lo, "maxValue": hi}],
            "intensityClass": cls,
            "openDuration": False
        }],
        "begin": begin, "end": end
    }


def repetition_block(reps, steps_list, begin, end):
    """A repeated interval block. steps_list items must include type='step'."""
    return {
        "type": "repetition",
        "length": {"value": reps, "unit": "repetition"},
        "steps": steps_list,
        "begin": begin, "end": end
    }


def interval_step(name, unit, value, lo, hi, cls):
    """A step inside a repetition block (requires explicit type field)."""
    return {
        "type": "step",
        "name": name,
        "length": {"value": value, "unit": unit},
        "targets": [{"minValue": lo, "maxValue": hi}],
        "intensityClass": cls,
        "openDuration": False
    }


def post_workout(token, uid, workout):
    workout["athleteId"] = uid
    url = f"https://tpapi.trainingpeaks.com/fitness/v6/athletes/{uid}/workouts"
    req = urllib.request.Request(url, data=json.dumps(workout).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json", "Origin": "https://app.trainingpeaks.com",
        "Referer": "https://app.trainingpeaks.com/"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return True, data.get("workoutId") or data.get("id", "?")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:300]}"


def delete_workouts_on_date(token, uid, date_str):
    """Delete all existing workouts on a given date (YYYY-MM-DD)."""
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json",
         "Origin": "https://app.trainingpeaks.com"}
    workouts = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"https://tpapi.trainingpeaks.com/fitness/v6/athletes/{uid}/workouts/{date_str}/{date_str}",
        headers=h)).read().decode())
    for w in workouts:
        wid = w["workoutId"]
        urllib.request.urlopen(urllib.request.Request(
            f"https://tpapi.trainingpeaks.com/fitness/v6/athletes/{uid}/workouts/{wid}",
            method="DELETE", headers=h))
        print(f"  🗑  Deleted {wid} ({w.get('title', '?')}) on {date_str}")


# ── Workout definitions ───────────────────────────────────────────────────────

def build_track_intervals(date="2026-04-07"):
    """VO2max track session: WU 2km + 6x800m fast/90s recovery + CD 2km (~10km)"""
    return {
        "workoutDay": f"{date}T00:00:00",
        "title": "Track Intervals - VO2max",
        "workoutTypeValueId": 3,  # Run
        "totalTimePlanned": 1.0,
        "distancePlanned": 10000,
        "tssPlanned": 75,
        "structure": {
            "primaryIntensityMetric": "percentOfThresholdPace",
            "primaryIntensityTargetOrRange": "range",
            "structure": [
                step_block("Warm-up", "meter", 2000, 70, 75, "warmUp", 0, 2000),
                repetition_block(6, [
                    interval_step("800m Fast", "meter", 800, 103, 107, "active"),
                    interval_step("90s Recovery", "second", 90, 60, 65, "rest"),
                ], 2000, 6800),
                step_block("Cool-down", "meter", 2000, 70, 75, "coolDown", 6800, 8800),
            ]
        }
    }


def build_easy_run(date="2026-04-09"):
    """Easy aerobic endurance run: WU 1km + 10km zone 2 + CD 1km (12km total)"""
    return {
        "workoutDay": f"{date}T00:00:00",
        "title": "Easy Aerobic Run - Endurance",
        "workoutTypeValueId": 3,
        "totalTimePlanned": 1.167,
        "distancePlanned": 12000,
        "tssPlanned": 55,
        "structure": {
            "primaryIntensityMetric": "percentOfThresholdPace",
            "primaryIntensityTargetOrRange": "range",
            "structure": [
                step_block("Warm-up", "meter", 1000, 65, 70, "warmUp", 0, 1000),
                step_block("Easy Zone 2 Run", "meter", 10000, 72, 78, "active", 1000, 11000),
                step_block("Cool-down", "meter", 1000, 65, 70, "coolDown", 11000, 12000),
            ]
        }
    }


def build_half_marathon(date="2026-04-12"):
    """Half marathon race with pacing strategy: WU + conservative + race pace + final push"""
    return {
        "workoutDay": f"{date}T00:00:00",
        "title": "Half Marathon Race",
        "workoutTypeValueId": 6,  # Race
        "totalTimePlanned": 1.833,
        "distancePlanned": 21097,
        "tssPlanned": 150,
        "structure": {
            "primaryIntensityMetric": "percentOfThresholdPace",
            "primaryIntensityTargetOrRange": "range",
            "structure": [
                step_block("Warm-up", "meter", 2000, 70, 78, "warmUp", 0, 2000),
                step_block("First 5km - Conservative", "meter", 5000, 85, 88, "active", 2000, 7000),
                step_block("Main Race Pace", "meter", 10000, 90, 95, "active", 7000, 17000),
                step_block("Final Push to Finish", "meter", 4097, 95, 102, "active", 17000, 21097),
            ]
        }
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create structured TrainingPeaks workouts")
    parser.add_argument("--replace", action="store_true",
                        help="Delete existing workouts on the same dates before creating")
    args = parser.parse_args()

    creds = json.load(open(CREDENTIALS_FILE))["trainingpeaks"]
    print(f"🔐 Logging in as {creds['username']}...")
    token, uid = login(creds["username"], creds["password"])
    print(f"✅ Logged in (userId={uid})\n")

    workouts = [
        (build_track_intervals, "2026-04-07", "Track Intervals - VO2max      | Tue Apr 7"),
        (build_easy_run,        "2026-04-09", "Easy Aerobic Run - Endurance  | Thu Apr 9"),
        (build_half_marathon,   "2026-04-12", "Half Marathon Race             | Sun Apr 12"),
    ]

    for build_fn, date, label in workouts:
        if args.replace:
            delete_workouts_on_date(token, uid, date)
        w = build_fn(date)
        print(f"📅 Creating: {label}...")
        ok, result = post_workout(token, uid, w)
        print(f"  {'✅ Created (id=' + str(result) + ')' if ok else '❌ Failed: ' + str(result)}")


if __name__ == "__main__":
    main()
