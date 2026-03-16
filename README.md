<div align="center">
  <h1>
    🏃 TrainingPeaks Workout of the Day → Telegram [OpenClaw]
  </h1>
  <img src="https://img.shields.io/badge/DoneBy-OpenClaw-red">
  <img src="https://img.shields.io/badge/Python-Script-blue">
  
  Fetches your planned workout from TrainingPeaks and sends it to Telegram, with real pace targets, per-section distances, and a total distance estimate, using OpenClaw.
</div>

## Example output

```
🏃 Workout of the Day — 2026-03-14

🏃 Run  4x3 - 2x20 - 4x3
⏱ 2h 00min  TSS: 167

📊 Structure:
  • Warm up: 15' ~6:50/km  ≈2.19 km
  🔁 4x (3' ~5:17/km / 2' ~6:25/km)  ≈3.51 km
  • Recovery: 5' ~6:25/km  ≈0.78 km
  • Active: 20' ~5:38/km  ≈3.55 km
  • Recovery: 5' ~6:25/km  ≈0.78 km
  • Active: 20' ~5:38/km  ≈3.55 km
  • Recovery: 5' ~6:25/km  ≈0.78 km
  🔁 4x (3' ~5:17/km / 2' ~6:25/km)  ≈3.51 km
  • Cool Down: 10' ~6:50/km  ≈1.46 km
  ──────────────────
  📍 Total: ~20.1 km
```

Pace targets are computed from your TrainingPeaks threshold speed — no percentages, just real paces. Supports all sport types (Run, Bike, Swim, Strength, etc.).

## Setup

### 1. Copy and fill in credentials

```bash
cp credentials.example.json credentials.json
```

Edit `credentials.json` with your details. This file is gitignored — never commit it.

### 2. Run

```bash
# Print to terminal only
python3 trainingpeaks_workout.py --print

# Send to Telegram
python3 trainingpeaks_workout.py

# Specific date
python3 trainingpeaks_workout.py --date 2026-03-16
```

### 3. Automate (optional)

Add a daily cron job (e.g. 7:30 AM):

```bash
30 7 * * * python3 /path/to/trainingpeaks_workout.py
```

## Configuration

Credentials can be set via **file** or **environment variables** (env vars take priority).

### credentials.json

```json
{
  "trainingpeaks": {
    "username": "your_tp_username",
    "password": "your_tp_password"
  },
  "telegram": {
    "token": "your_bot_token",
    "chat_id": "your_chat_id"
  }
}
```

### Environment variables

| Variable          | Description                    |
|-------------------|--------------------------------|
| `TP_USERNAME`     | TrainingPeaks username         |
| `TP_PASSWORD`     | TrainingPeaks password         |
| `TELEGRAM_TOKEN`  | Telegram bot token             |
| `TELEGRAM_CHAT_ID`| Telegram chat/user ID          |

## Requirements

- Python 3.6+
- No external dependencies (stdlib only)
- A TrainingPeaks account (free or premium)
- A Telegram bot token ([create one via @BotFather](https://t.me/BotFather))

## How it works

1. Logs into TrainingPeaks via the web login flow (no official API key needed)
2. Fetches a Bearer token from the internal TP API
3. Retrieves your planned workout for the day
4. Fetches your threshold speed to convert % targets into real paces
5. Formats and sends the message to Telegram
