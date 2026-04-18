# 🌦️ WeatherBet — Powered by Hermes Agent

> **Fully Autonomous Prediction Market Trading Bot** — Uses ECMWF weather forecast data to automatically find mispriced Polymarket markets and bet on them. Self-improves over time via the **Hermes Agent** framework.

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Polygon](https://img.shields.io/badge/Chain-Polygon%20137-9B59B6.svg)](https://polygon.technology/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🤖 Why Hermes Agent

This project demonstrates the power of **Hermes Agent** framework in autonomous trading:

| Hermes Agent Feature | Application in This Project |
|---|---|
| **Self-Learning & Evolution** | Bot automatically adjusts Kelly fraction and EV threshold from trade history |
| **Fully Autonomous Execution** | 60-min scan loop → signal calculation → auto order execution → on-chain settlement — zero human intervention |
| **Multi-Platform Gateway** | Real-time trade alerts via Telegram — control everything from your phone |
| **Persistent Memory** | Trade logs + learning models persist across sessions |
| **Model Agnostic** | Switch any LLM provider for decision reasoning |
| **Tool Orchestration** | Integrates weather API + on-chain CLOB trading + Telegram notifications |

---

## 🎯 What It Does

The bot monitors **6 US cities** (NYC, Chicago, Miami, Dallas, Seattle, Atlanta) and scans Polymarket temperature prediction markets for mispricing opportunities.

**Core Logic:** When weather forecast implies a different probability than what the market price suggests → calculate Expected Value (EV) → auto-bet if EV exceeds threshold.

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/nicolastinkl/hermes_weatherbot.git
cd hermes_weatherbot
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy the example env file and fill in your wallet credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Your Polygon private key (hex, without 0x prefix)
PK=your_polygon_private_key_here

# Your Polygon wallet address
WALLET=0xYourWalletAddressHere

# Signature type (0 = EOA)
SIG_TYPE=0
```

Edit `config.json` to set your trading parameters:

```json
{
  "max_bet": 2.0,
  "min_ev": 0.10,
  "min_volume": 500,
  "scan_interval": 3600,
  "telegram_bot_token": "your_token",
  "telegram_chat_id": "your_chat_id"
}
```

### 3. Start Trading

```bash
# Start the bot (runs in background)
./start_bot_v3.sh

# Stop the bot
./stop_bot_v3.sh
```

That's it! The bot will continuously scan markets and trade automatically.

---

## 🧠 Core Math: Gaussian Bucket Model

### Step 1 — True Probability from ECMWF

```python
import math

def norm_cdf(x):
    """Cumulative distribution function of standard normal"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast_temp, t_low, t_high, sigma=2.0):
    """
    Forecast says 72°F ± 2σ.
    What's the probability actual high falls in 70-75°F bucket?
    P(t_low ≤ X ≤ t_high) = CDF(z_high) - CDF(z_low)
    """
    z_low  = (t_low  - forecast_temp) / sigma
    z_high = (t_high - forecast_temp) / sigma
    return norm_cdf(z_high) - norm_cdf(z_low)
```

### Step 2 — Expected Value (EV)

```python
def calc_ev(true_prob, market_price):
    """
    EV = P(win) × payoff - P(lose) × cost
    EV > 0 → market is underpriced → BUY signal
    """
    win  = true_prob * (1 / market_price - 1)
    lose = (1 - true_prob) * 1
    return win - lose
```

**Example:**
- Forecast: 72°F → 75% chance of 70-75°F bucket
- Market price: $0.30 (implies 30% probability)
- `EV = 0.75 × (1/0.30 - 1) - 0.25 = +1.25` → **Strong BUY** 📈

### Step 3 — Kelly Criterion (Optimal Bet Sizing)

```python
def calc_kelly(p, price):
    """Kelly % = (bp - q) / b — uses 1/4 Kelly conservative fraction"""
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(f, 0.0) * KELLY_FRAC, 1.0), 4)
```

---

## 🌀 Auto-Evolution Learning System

This is a core strength of the Hermes Agent framework — the bot **learns from trading and auto-tunes**:

```
data/learning/
├── trade_log.json   # All trades: city, bucket, cost, outcome, pnl
└── model.json       # Learned parameters per city/bucket
```

**Adaptation Rules:**
- Winrate < 45% → Kelly fraction ×0.8, EV floor +10%
- Winrate > 55% + PnL > $2 → Kelly fraction ×1.1, EV floor −5%
- Per-city winrate tracking adjusts confidence per market
- Starts conservative (25% Kelly) → converges to optimal as data accumulates

---

## 📊 Architecture

```
ECMWF Weather Forecast API
        ↓
Hermes Agent (Autonomous Decision Engine)
    ├── Gaussian Bucket Model → True Probability
    ├── calc_ev() → Expected Value Calculation
    ├── calc_kelly() → Optimal Bet Sizing
    └── Adaptive Learning → Auto Parameter Tuning
        ↓
Polymarket CLOB (On-chain, Polygon)
        ↓
Telegram (Real-time Notifications)
```

---

## 🛡️ Risk Management

| Parameter | Value | Purpose |
|---|---|---|
| Max bet | $2.00 | Per-trade exposure cap |
| Kelly fraction | 25% | 1/4 Kelly conservative |
| Min EV | 10%+ | Only trade positive EV |
| Min volume | $500 | Avoid illiquid markets |
| Max spread | 3% | Avoid high-slippage |
| Adaptive floor | 10-20% | Self-tuning from performance |

---

## 🔐 Full Automated Trading Flow

```
1. Fetch ECMWF forecast (D+0 ~ D+3)
2. Query Polymarket temperature bucket markets
3. Gaussian model → true probability (σ=2°F)
4. Compare to market price → calculate EV
5. EV ≥ adaptive threshold → calculate Kelly bet size
6. Execute order on Polymarket CLOB (Polygon)
7. Record trade → update learning model
8. Telegram real-time notification
9. Repeat every 60 minutes
```

---

## 💡 Tech Stack

- **Framework:** Hermes Agent (autonomous learning + multi-platform)
- **Language:** Python 3.13
- **Trading:** [py_clob_client](https://github.com/polymarket/py-clob-client) — Polymarket CLOB
- **Weather:** ECMWF OpenMETAR / Open-Meteo API
- **Chain:** Polygon (Chain ID 137) — USDC.e stablecoin
- **Notifications:** Telegram Bot API
- **Learning:** Pure Python JSON persistence (zero DB dependency)

---

## ⚠️ Disclaimer

This bot trades real markets with real money. Past performance does not guarantee future results. Trade at your own risk. For educational and research purposes only.

---

*Built with 🐍 + Hermes Agent on Polygon — Autonomous Weather Prediction Trading.*
