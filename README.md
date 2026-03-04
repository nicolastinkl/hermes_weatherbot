# 🌤 Weather Trading Bot — Polymarket

Automated weather market trading bot for Polymarket. Finds mispriced temperature outcomes using Open-Meteo forecasts.

No SDK. No black box. Pure Python.

---

## Versions

### `bot_v1.py` — Base Bot
The foundation. Scans 6 cities, fetches forecasts from Open-Meteo, finds matching temperature buckets on Polymarket, and enters trades when the market price is below the entry threshold.

No math, no complexity. Just the core logic — good for understanding how the system works.

### `bot_v2.py` — Kelly + EV Edition *(current)*
Everything in v1, plus:
- **Expected Value** — skips trades where the math doesn't work
- **Kelly Criterion** — sizes positions based on edge strength, not a flat %
- **Live monitor** — updates `simulation.json` every 10s so the dashboard stays current
- **Auto-exit** — closes positions when price hits the exit threshold

~400 lines of pure Python.

### `bot_v3.py` — Coming Soon
- Auto-cycle every hour — continuously scans and opens new positions
- Forecast monitoring every 10 minutes — closes positions if the forecast changes and EV goes negative
- Historical calibration — uses 10 years of weather data to validate probabilities

---

## How It Works

Polymarket runs markets like *"Will the highest temperature in NYC be between 40–41°F on March 4?"* These markets are often mispriced — the forecast says 78% likely, but the market is trading at 8 cents.

The bot:
1. Fetches 4-day forecasts from **Open-Meteo** (free, no API key)
2. Finds the matching temperature bucket on Polymarket
3. Calculates Expected Value — skips the trade if EV is negative
4. Calculates Kelly Criterion — sizes the position based on edge strength
5. Runs a full $1,000 simulation against real market prices before you risk anything

---

## Kelly + EV Logic

**Expected Value** — is this trade mathematically profitable?

```
EV = (our_probability × net_payout) − (1 − our_probability)
```

**Kelly Criterion** — how much of the balance to bet?

```
Kelly % = (p × b − q) / b
```

We use fractional Kelly (25%) and cap each position at 10% of balance.

---

## Installation

```bash
git clone https://github.com/alteregoeth-ai/weatherbot
cd weatherbot
pip install requests
```

Add your settings to `config.json`:

```json
{
  "entry_threshold": 0.15,
  "exit_threshold": 0.45,
  "locations": "NYC,Chicago,Seattle,Atlanta,Dallas,Miami",
  "max_trades_per_run": 5,
  "min_hours_to_resolution": 2
}
```

---

## Usage

### bot_v1.py
```bash
# Scan markets and show signals
python bot_v1.py
```

### bot_v2.py
```bash
# Paper mode — shows signals + Kelly/EV analysis, no trades
python bot_v2.py

# Simulation mode — executes trades, updates virtual $1,000 balance
python bot_v2.py --live

# Live monitor — updates dashboard every 10s
python bot_v2.py --monitor

# Show open positions and PnL
python bot_v2.py --positions

# Reset simulation back to $1,000
python bot_v2.py --reset
```

---

## Dashboard

Run a local server in the bot folder:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/sim_dashboard.html` in your browser.

- Balance chart with floating +/- labels on each trade
- Open positions with Kelly %, EV, and price progress bar
- Full trade history with W/L tracking
- Refreshes every 10 seconds automatically

---

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entry_threshold` | `0.15` | Buy below this price |
| `exit_threshold` | `0.45` | Sell above this price |
| `locations` | `NYC,...` | Cities to scan |
| `max_trades_per_run` | `5` | Max trades per run |
| `min_hours_to_resolution` | `2` | Skip if resolves too soon |

---

## Live Trading

The bot runs in simulation mode by default. To execute real trades, add Polymarket CLOB integration:

```bash
pip install py-clob-client
```

Then replace the paper mode block in `bot_v2.py` with your CLOB buy function. Full guide in the article linked below.

---

## APIs Used

| API | Auth | Purpose |
|-----|------|---------|
| Open-Meteo | None | Weather forecasts |
| Polymarket Gamma | None | Market data |
| Polymarket CLOB | Wallet key | Live trading (optional) |

---

## Disclaimer

This is not financial advice. Prediction markets carry real risk. Run the simulation thoroughly before committing real capital.
