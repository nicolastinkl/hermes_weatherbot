# 🌦️ WeatherBet — Polymarket Weather Trading Bot

> Autonomous trading bot that exploits weather forecast errors to find mispriced Polymarket prediction markets — and self-improves over time.

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Polygon](https://img.shields.io/badge/Chain-Polygon%20137-9B59B6.svg)](https://polygon.technology/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🎯 What It Does

The bot monitors **6 US cities** (NYC, Chicago, Miami, Dallas, Seattle, Atlanta) and bets on Polymarket's temperature prediction markets using **real ECMWF weather forecasts** as its edge. When the forecast predicts a temperature bucket, but the market price implies a different probability, the bot calculates the Expected Value (EV) and places a trade if EV > threshold.

---

## 💡 Why It Makes Money

**The edge is weather forecast accuracy.**

Polymarket traders rely on gut feel and consensus. This bot uses **ECMWF** — the world's most accurate weather model — to calculate the true probability of each temperature bucket, then compares it to the market price.

```
True Probability (from ECMWF) vs. Market Price (from Polymarket)
```

When `Market Price < True Probability`, the market is **underpriced** → BUY.

---

## 🧮 The Math

### Step 1 — True Probability (Gaussian Bucket Model)

```python
import math

def norm_cdf(x):
    """Cumulative distribution function of standard normal — uses math.erf, no scipy needed."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast_temp, t_low, t_high, sigma=2.0):
    """
    The forecast says 72°F ± 2σ.
    What's the probability the actual high falls in the 70-75°F bucket?
    P(t_low ≤ X ≤ t_high) = CDF(z_high) - CDF(z_low)
    """
    z_low  = (t_low  - forecast_temp) / sigma
    z_high = (t_high - forecast_temp) / sigma
    return norm_cdf(z_high) - norm_cdf(z_low)
```

### Step 2 — Expected Value

```python
def calc_ev(true_prob, market_price):
    """
    EV = P(win) × payoff - P(lose) × cost
    If EV > 0, the market underprices this outcome.
    """
    win  = true_prob * (1 / market_price - 1)   # profit if we win
    lose = (1 - true_prob) * 1                   # we lose our stake
    return win - lose
```

**Example:**
- Forecast: 72°F → 75% chance of 70-75°F bucket
- Market price: $0.30 (implies 30% probability)
- `EV = 0.75 × (1/0.30 - 1) - 0.25 = +1.25` → **Strong BUY**

### Step 3 — Kelly Criterion (Optimal Bet Size)

```python
def calc_kelly(p, price):
    """
    Kelly % = (bp - q) / b
    where b = 1/price - 1, p = true_prob, q = 1-p
    """
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(f, 0.0) * KELLY_FRAC, 1.0), 4)

def bet_size(kelly, balance):
    return round(min(kelly * balance, MAX_BET), 2)
```

- Uses **1/4 Kelly** (conservative fraction) to survive variance
- Caps bet at `$2.00` per trade
- **Only trades when EV ≥ 10%** (adaptive floor, self-improving)

### Summary: Why This Strategy Wins

| Component | Detail |
|---|---|
| **Edge** | ECMWF weather model is more accurate than consensus |
| **Signal** | Mispriced markets when `Market Price < True Probability` |
| **Sizing** | Kelly Criterion — mathematically optimal bet sizing |
| **Filter** | EV ≥ 10% (adaptive), volume > $500, spread < 3% |
| **Execution** | Real Polymarket CLOB on Polygon (not simulation) |
| **Learning** | Self-tuning Kelly fraction + EV floor from trade history |

---

## 🧠 Self-Learning System

After each trade, the bot records the outcome and adjusts its strategy:

```
data/learning/
├── trade_log.json   # All trades: city, bucket, cost, outcome, pnl
└── model.json       # Learned parameters per city/bucket
```

**Adaptation rules:**
- Winrate < 45% → Kelly fraction ×0.8, EV floor +10%
- Winrate > 55% + PnL > $2 → Kelly fraction ×1.1, EV floor −5%
- Per-city winrate tracking adjusts confidence in each market
- Starts conservative (25% Kelly) → converges to optimal as data accumulates

---

## ⚙️ Setup

### Requirements

- Python 3.13+
- Polygon wallet with USDC.e (on chain 137)
- Polymarket CLOB approval
- Polymarket API credentials

### Installation

```bash
git clone https://github.com/yourhandle/weatherbot.git
cd weatherbot
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create `.env`:
```env
PK=your_polygon_private_key
WALLET=your_polygon_address
SIG_TYPE=0
```

Edit `config.json`:
```json
{
  "balance": 0,
  "max_bet": 2.0,
  "min_ev": 0.10,
  "min_volume": 500,
  "scan_interval": 3600,
  "telegram_bot_token": "your_token",
  "telegram_chat_id": "your_chat_id"
}
```

### Run

```bash
# One-shot scan
python bot_v3.py scan

# Continuous trading loop
python bot_v3.py run

# Check status
python bot_v3.py status
```

---

## 📊 Architecture

```
bot_v3.py
│
├── Weather Data
│   ├── ECMWF API      — 10-day temperature forecast (primary signal)
│   └── METAR          — current obs for D+0 override
│
├── Signal Evaluation
│   ├── bucket_prob()  — Gaussian model → true probability
│   ├── calc_ev()      — expected value vs market price
│   ├── calc_kelly()   — optimal bet fraction
│   └── Adaptive floor — self-learning EV threshold
│
├── Execution
│   ├── py_clob_client — Polymarket CLOB on Polygon
│   ├── place_buy_order — market order with 10s timeout
│   └── on-chain settlement
│
├── Monitoring
│   ├── Telegram       — real-time trade alerts
│   ├── Self-learning  — trade_log + model.json
│   └── 60-min loop    — continuous scan
│
└── Market Resolution
    └── Outcome check   — PnL update when market resolves
```

---

## 🔐 Trading Flow

```
1. Fetch ECMWF forecast for each city (D+0 to D+3)
2. Query Polymarket for temperature bucket markets
3. Calculate true probability (Gaussian model, σ=2°F)
4. Compare to market price → calc EV
5. If EV ≥ adaptive threshold → calculate Kelly bet size
6. Execute market order on Polymarket CLOB (Polygon)
7. Record trade → update self-learning model
8. Send Telegram notification
9. Repeat every 60 minutes
```

---

## ⚠️ Risk Management

| Parameter | Value | Purpose |
|---|---|---|
| Max bet | $2.00 | Cap per-trade exposure |
| Kelly fraction | 25% | Survive variance (1/4 Kelly) |
| Min EV | 10%+ | Only trade positive EV |
| Min volume | $500 | Avoid illiquid markets |
| Max spread | 3% | Avoid high-slippage markets |
| Adaptive floor | 10-20% | Self-tuning from performance |

---

## 📦 Tech Stack

- **Language:** Python 3.13
- **Trading:** [py_clob_client](https://github.com/polymarket/py-clob-client) — Polymarket CLOB
- **Weather:** ECMWF OpenMETAR / Open-Meteo API
- **Chain:** Polygon (Chain ID 137) — USDC.e stablecoin
- **Notifications:** Telegram Bot API
- **Self-learning:** Pure Python JSON persistence (no DB needed)

---

## 📝 Disclaimer

This bot trades real markets with real money. Past performance does not guarantee future results. Trade at your own risk. The bot is provided as-is for educational and research purposes.

---

*Built with 🐍 on Polygon — autonomous weather prediction trading.*
