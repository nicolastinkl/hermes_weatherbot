#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weather Trading Bot v3 — Polymarket CLOB Real Trading
======================================================
bot_v2 strategy logic + py_clob_client on-chain order execution.
Only trades US cities (F) for now — EU/Asia cities need CLOB market support.

Usage:
    python bot_v3.py run          # Full trading loop (scan + monitor)
    python bot_v3.py scan         # One-shot scan + trade signals
    python bot_v3.py status       # Show open positions + balance
    python bot_v3.py cancel       # Cancel all open orders
    python bot_v3.py cancel --market <market_id>  # Cancel orders for a market
"""

import re
import sys
import json
import math
import time
import os
import logging
import dotenv
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# =============================================================================
# CONFIG
# =============================================================================

BOT_DIR = Path(__file__).parent
dotenv.load_dotenv(BOT_DIR / ".env")

with open(BOT_DIR / "config.json", encoding="utf-8") as f:
    _cfg = json.load(f)

# --- Wallet ---
PK        = os.getenv("PK", "")
WALLET    = os.getenv("WALLET", "")
SIG_TYPE  = int(os.getenv("SIG_TYPE", "0"))

# --- Trading ---
MAX_BET       = _cfg.get("max_bet", 2.0)
MIN_EV        = _cfg.get("min_ev", 0.10)
MAX_PRICE     = _cfg.get("max_price", 0.45)
MIN_VOLUME    = _cfg.get("min_volume", 500)
MIN_HOURS     = _cfg.get("min_hours", 2.0)
MAX_HOURS     = _cfg.get("max_hours", 72.0)
KELLY_FRAC    = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE  = _cfg.get("max_slippage", 0.03)
SCAN_INTERVAL = _cfg.get("scan_interval", 3600)
VC_KEY        = _cfg.get("vc_key", "")

# --- CLOB ---
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID  = 137   # Polygon

# --- Telegram ---
TELEGRAM_BOT_TOKEN = _cfg.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID   = _cfg.get("telegram_chat_id", "")

# --- Contract addresses (Polygon) ---
USDC_ADDRESS            = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_EXCHANGE            = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_EXCHANGE       = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
ROUTER                  = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CONDITIONAL_TOKENS      = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# --- Gas ---
MAX_FEE_PER_GAS = 200e9   # 200 gwei

# =============================================================================
# MATH
# =============================================================================

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast, t_low, t_high, sigma=2.0):
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / sigma)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / sigma)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0

def calc_ev(p, price):
    if price <= 0 or price >= 1: return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)

def calc_kelly(p, price):
    if price <= 0 or price >= 1: return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(0.0, f) * KELLY_FRAC, 1.0), 4)

def bet_size(kelly, balance):
    raw = kelly * balance
    return round(min(raw, MAX_BET), 2)

# =============================================================================
# COLORS
# =============================================================================

class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

def ok(msg):   print(f"{C.GREEN}  ✅ {msg}{C.RESET}")
def warn(msg): print(f"{C.YELLOW}  ⚠️  {msg}{C.RESET}")
def info(msg): print(f"{C.CYAN}  {msg}{C.RESET}")
def skip(msg): print(f"{C.GRAY}  ⏸️  {msg}{C.RESET}")
def live(msg): print(f"{C.GREEN}  {msg}{C.RESET}")

# =============================================================================
# CLOB CLIENT
# =============================================================================

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType

_clob: ClobClient = None

def get_clob() -> ClobClient:
    global _clob
    if _clob is None:
        _clob = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=PK,
        )
    return _clob

# =============================================================================
# ON-CHAIN HELPERS
# =============================================================================

from web3 import Web3
from eth_account import Account

_w3: Web3 = None

def get_w3() -> Web3:
    global _w3
    if _w3 is None:
        _w3 = Web3(Web3.HTTPProvider("https://1rpc.io/matic"))
    return _w3

def get_nonce(wallet: str) -> int:
    return get_w3().eth.get_transaction_count(wallet)

def send_tx(w3, signed_txn):
    return w3.eth.send_raw_transaction(signed_txn).hex()

def wait_for_receipt(w3, tx_hash: str, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt and receipt["status"] == 1:
                return receipt
        except Exception:
            pass
        time.sleep(2)
    return None

# =============================================================================
# BALANCE CHECK
# =============================================================================

def get_usdc_balance(wallet: str) -> float:
    """Get USDC.e balance on Polygon."""
    w3 = get_w3()
    usdc_abi = [
        {
            "name": "balanceOf",
            "inputs": [{"name": "account", "type": "address"}],
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "name": "decimals",
            "inputs": [],
            "outputs": [{"name": "", "type": "uint8"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS),
        abi=usdc_abi
    )
    try:
        decimals = usdc.functions.decimals().call()
        bal = usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        return bal / (10 ** decimals)
    except Exception as e:
        warn(f"Balance check failed: {e}")
        return 0.0

def get_pol_balance(wallet: str) -> float:
    w3 = get_w3()
    bal = w3.eth.get_balance(Web3.to_checksum_address(wallet))
    return int(bal) / 1e18

# =============================================================================
# TELEGRAM NOTIFICATIONS
# =============================================================================

_tg_session = requests.Session()
_tg_session.proxies = {
    "http": "socks5h://127.0.0.1:6922",
    "https": "socks5h://127.0.0.1:6922",
}

def send_telegram(text: str, retry=2) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(retry + 1):
        try:
            r = _tg_session.post(url, json=payload, timeout=(5, 10))
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if attempt < retry:
            time.sleep(1)
    return False

def tg_signal(city: str, horizon: str, date: str, bucket_label: str,
              forecast_temp: float, entry_price: float, cost: float,
              ev: float, kelly: float, success: bool, reason: str = ""):
    """Send a trade signal notification to Telegram."""
    if success:
        msg = (
            f"📍 <b>{city} {horizon}</b> — {date}\n"
            f"🌡 Forecast: <b>{forecast_temp}°F</b>\n"
            f"🎯 Bucket: <b>{bucket_label}</b>\n"
            f"💰 Cost: <b>${cost:.2f}</b> @ <b>${entry_price:.3f}</b>\n"
            f"📈 EV: <b>+{ev:.2f}</b> | Kelly: <b>{kelly:.2f}</b>\n"
            f"✅ <b>ORDER FILLED</b>"
        )
    else:
        msg = (
            f"📍 <b>{city} {horizon}</b> — {date}\n"
            f"🌡 Forecast: <b>{forecast_temp}°F</b>\n"
            f"🎯 Bucket: <b>{bucket_label}</b>\n"
            f"❌ <b>ORDER FAILED:</b> {reason}"
        )
    send_telegram(msg)

def tg_scan_summary(new_trades: int, errors: int, balance: float, cities: int):
    """Send a scan summary to Telegram."""
    status_emoji = "✅" if errors == 0 else "⚠️"
    msg = (
        f"🔔 <b>Weather Bot Scan Complete</b>\n"
        f"{status_emoji} Cities: {cities} | New trades: {new_trades} | Errors: {errors}\n"
        f"💰 Balance: <b>${balance:.4f}</b> USDC.e"
    )
    send_telegram(msg)

# =============================================================================
# APPROVAL CHECK
# =============================================================================

def is_approved(token: str, spender: str, wallet: str) -> bool:
    """Check if spender is approved for token (USDC.e)."""
    w3 = get_w3()
    usdc_abi = [
        {
            "name": "allowance",
            "inputs": [
                {"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}
            ],
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(token),
        abi=usdc_abi
    )
    try:
        allowance = usdc.functions.allowance(
            Web3.to_checksum_address(wallet),
            Web3.to_checksum_address(spender)
        ).call()
        return allowance > 0
    except Exception:
        return False

def approve_token(token: str, spender: str, wallet: str, private_key: str,
                  amount_wei: int = 2**256 - 1, max_fee: int = MAX_FEE_PER_GAS):
    """Approve spender to spend token on behalf of wallet."""
    w3 = get_w3()
    usdc_abi = [
        {
            "name": "approve",
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}
            ],
            "outputs": [{"name": "", "type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(token),
        abi=usdc_abi
    )
    nonce = get_nonce(wallet)
    build = usdc.functions.approve(
        Web3.to_checksum_address(spender),
        amount_wei
    ).build_transaction({
        "from": wallet,
        "nonce": nonce,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": 25e9,
        "chainId": CHAIN_ID,
    })
    signed = w3.eth.account.sign_transaction(build, private_key)
    tx_hash = send_tx(w3, signed.raw_transaction)
    live(f"Approve tx: {tx_hash}")
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt:
        ok(f"Approved {spender} for {token[:10]}...")
        return True
    warn(f"Approval tx failed: {tx_hash}")
    return False

def ensure_approvals():
    """Ensure all required approvals are set before trading."""
    wallet = WALLET
    required = [
        (USDC_ADDRESS, CTF_EXCHANGE),
        (USDC_ADDRESS, NEG_RISK_EXCHANGE),
        (USDC_ADDRESS, ROUTER),
    ]
    for token, spender in required:
        if not is_approved(token, spender, wallet):
            warn(f"Missing approval: {spender[:10]} for {token[:10]}")
            ok(f"Approving {spender[:10]}...")
            approve_token(token, spender, wallet, PK)
            time.sleep(5)  # Wait for confirmation
        else:
            ok(f"Already approved: {spender[:10]}")

# =============================================================================
# ORDER EXECUTION
# =============================================================================

def place_buy_order(market_id: str, token_id: str, price: float, shares: float,
                   balance: float, private_key: str, wallet: str) -> dict:
    """
    Place a BUY order on Polymarket CLOB.
    Uses FOK (Fill-Or-Kill) market order to guarantee execution.
    Returns dict with success status and details.
    """
    w3 = get_w3()
    clob = get_clob()

    cost = round(shares * price, 4)
    if cost > balance:
        return {"success": False, "reason": f"Insufficient balance (${balance:.2f} < ${cost:.2f})"}

    if not is_approved(USDC_ADDRESS, ROUTER, wallet):
        return {"success": False, "reason": "Router approval missing"}

    # --- Market order via CLOB ---
    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=cost,   # For BUY: amount is in dollars (USDC)
        side="BUY",
        price=price,
    )

    try:
        # First check allowance
        clob.assert_level_1_auth()
        order_result = clob.create_market_order(order_args)
        live(f"Market order placed: {order_result}")
    except Exception as e:
        return {"success": False, "reason": f"Order failed: {e}"}

    return {
        "success": True,
        "market_id": market_id,
        "token_id": token_id,
        "price": price,
        "shares": shares,
        "cost": cost,
        "order_id": order_result.get("orderID") if isinstance(order_result, dict) else str(order_result),
    }

def cancel_order(order_id: str) -> bool:
    """Cancel a specific order by ID."""
    clob = get_clob()
    try:
        clob.cancel(order_id)
        ok(f"Cancelled order: {order_id[:20]}...")
        return True
    except Exception as e:
        warn(f"Cancel failed: {e}")
        return False

def cancel_all_orders() -> int:
    """Cancel all open orders. Returns count of cancelled orders."""
    clob = get_clob()
    try:
        result = clob.cancel_all()
        count = result.get("count", 0) if isinstance(result, dict) else 0
        ok(f"Cancelled {count} orders")
        return count
    except Exception as e:
        warn(f"Cancel all failed: {e}")
        return 0

# =============================================================================
# LOCATIONS & WEATHER DATA
# =============================================================================

LOCATIONS = {
    "nyc":     {"lat": 40.7772,  "lon": -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago": {"lat": 41.9742,  "lon": -87.9073, "name": "Chicago",       "station": "KORD", "unit": "F", "region": "us"},
    "miami":   {"lat": 25.7959,  "lon": -80.2870, "name": "Miami",         "station": "KMIA", "unit": "F", "region": "us"},
    "dallas":  {"lat": 32.8471,  "lon": -96.8518, "name": "Dallas",        "station": "KDAL", "unit": "F", "region": "us"},
    "seattle": {"lat": 47.4502,  "lon":-122.3088, "name": "Seattle",        "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta": {"lat": 33.6407,  "lon": -84.4277, "name": "Atlanta",        "station": "KATL", "unit": "F", "region": "us"},
}

TIMEZONES = {
    "nyc": "America/New_York", "chicago": "America/Chicago",
    "miami": "America/New_York", "dallas": "America/Chicago",
    "seattle": "America/Los_Angeles", "atlanta": "America/New_York",
}

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]

import requests

def get_ecmwf(city_slug, dates):
    """ECMWF via Open-Meteo. Returns dict {date: temp_f}."""
    loc = LOCATIONS[city_slug]
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=temperature_2m_max&temperature_unit=fahrenheit"
        f"&forecast_days=7&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        f"&models=ecmwf_ifs025&bias_correction=true"
    )
    result = {}
    for attempt in range(3):
        try:
            data = requests.get(url, timeout=(5, 10)).json()
            if "error" not in data:
                for date, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                    if date in dates and temp is not None:
                        result[date] = round(temp)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                warn(f"ECMWF error for {city_slug}: {e}")
    return result

def get_metar(city_slug):
    """Current observed temperature from METAR station. D+0 only."""
    loc = LOCATIONS[city_slug]
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={loc['station']}&format=json"
        data = requests.get(url, timeout=(5, 8)).json()
        if data and isinstance(data, list):
            temp_c = data[0].get("temp")
            if temp_c is not None:
                return round(float(temp_c) * 9/5 + 32)
    except Exception as e:
        warn(f"METAR error for {city_slug}: {e}")
    return None

def get_forecast_snapshot(city_slug, dates):
    """Get best temperature forecast for each date. Returns {date: temp_f}."""
    ecmwf = get_ecmwf(city_slug, dates)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {}
    for date in dates:
        best = ecmwf.get(date)
        best_source = "ecmwf"
        # METAR for today if available
        if date == today:
            metar = get_metar(city_slug)
            if metar is not None:
                best = metar
                best_source = "metar"
        if best is not None:
            result[date] = {"temp": best, "source": best_source}
    return result

# =============================================================================
# POLYMARKET
# =============================================================================

def get_polymarket_event(city_slug, month, day, year):
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}", timeout=(5, 8))
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
    except Exception as e:
        warn(f"Polymarket API error: {e}")
    return None

def get_market_price(market_id):
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(3, 5))
        data = r.json()
        prices = json.loads(data.get("outcomePrices", "[0.5,0.5]"))
        return float(prices[0]), float(prices[1]) if len(prices) > 1 else float(prices[0])
    except Exception:
        return None, None

def parse_temp_range(question):
    if not question: return None
    num = r'(-?\d+(?:\.\d+)?)'
    if re.search(r'or below', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or below', question, re.IGNORECASE)
        if m: return (-999.0, float(m.group(1)))
    if re.search(r'or higher', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or higher', question, re.IGNORECASE)
        if m: return (float(m.group(1)), 999.0)
    m = re.search(r'between ' + num + r'-' + num + r'[°]?[FC]', question, re.IGNORECASE)
    if m: return (float(m.group(1)), float(m.group(2)))
    m = re.search(r'be ' + num + r'[°]?[FC] on', question, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return (v, v)
    return None

def hours_to_resolution(end_date_str):
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return 999.0

def in_bucket(forecast, t_low, t_high):
    if t_low == t_high:
        return round(float(forecast)) == round(t_low)
    return t_low <= float(forecast) <= t_high

def get_condition_id(market_id: str) -> str:
    """Get condition ID for a market from Polymarket."""
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(5, 8))
        data = r.json()
        return data.get("conditionId", "")
    except Exception:
        return ""

# =============================================================================
# STATE (local JSON)
# =============================================================================

DATA_DIR = BOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
MARKETS_DIR = DATA_DIR / "markets"
MARKETS_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "state_v3.json"

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "balance": 0.0,
        "starting_balance": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "open_orders": {},
    }

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def market_path(city_slug, date_str):
    return MARKETS_DIR / f"{city_slug}_{date_str}.json"

def load_market(city_slug, date_str):
    p = market_path(city_slug, date_str)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None

def save_market(market):
    p = market_path(market["city"], market["date"])
    p.write_text(json.dumps(market, indent=2, ensure_ascii=False), encoding="utf-8")

def load_all_markets():
    markets = []
    for f in MARKETS_DIR.glob("*.json"):
        try:
            markets.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return markets

# =============================================================================
# SIGMA (weather forecast uncertainty)
# =============================================================================

SIGMA_F = 2.0

def get_sigma(city_slug):
    return SIGMA_F  # Flat sigma for now; calibration can be added later

# =============================================================================
# OPEN POSITIONS from CLOB
# =============================================================================

def get_clob_positions():
    """Get all open orders/positions from CLOB."""
    clob = get_clob()
    try:
        orders = clob.get_orders()
        return orders if orders else []
    except Exception as e:
        warn(f"Failed to fetch CLOB orders: {e}")
        return []

# =============================================================================
# SCAN & TRADE (one shot)
# =============================================================================

def scan_and_trade():
    """
    One-shot scan: check all cities for trade signals and execute real orders.
    Returns (new_trades, errors).
    """
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = get_usdc_balance(WALLET)
    if balance != state.get("balance"):
        state["balance"] = balance
        save_state(state)

    print(f"\n{C.BOLD}{C.CYAN}🌤  Weather Trading Bot v3 — Live Mode{C.RESET}")
    print("=" * 60)
    print(f"  Wallet:       {WALLET[:8]}...{WALLET[-4:]}")
    print(f"  USDC.e:       ${balance:.4f}")
    print(f"  POL balance:  {get_pol_balance(WALLET):.4f} POL")
    print(f"  Max bet:      ${MAX_BET} | Min EV: {MIN_EV*100:.0f}%")
    print()

    new_trades = 0
    errors = []

    for city_slug, loc in LOCATIONS.items():
        print(f"  -> {loc['name']}...", end=" ", flush=True)
        unit_sym = "F"

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(4)]
            forecasts = get_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"error ({e})")
            continue

        for i, date in enumerate(dates):
            dt = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(
                city_slug,
                MONTHS[dt.month - 1],
                dt.day,
                dt.year
            )
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours = hours_to_resolution(end_date) if end_date else 0
            horizon = f"D+{i}"

            if hours < MIN_HOURS or hours > MAX_HOURS:
                continue

            # Parse all outcome buckets from Polymarket
            outcomes = []
            for market in event.get("markets", []):
                question = market.get("question", "")
                mid = str(market.get("id", ""))
                volume = float(market.get("volume", 0))
                rng = parse_temp_range(question)
                if not rng:
                    continue
                try:
                    prices = json.loads(market.get("outcomePrices", "[0.5,0.5]"))
                    bid = float(prices[0])
                    ask = float(prices[1]) if len(prices) > 1 else bid
                except Exception:
                    continue
                outcomes.append({
                    "question": question,
                    "market_id": mid,
                    "range": rng,
                    "bid": round(bid, 4),
                    "ask": round(ask, 4),
                    "price": round(bid, 4),
                    "spread": round(ask - bid, 4),
                    "volume": round(volume, 0),
                })

            if not outcomes:
                continue

            forecastsnap = forecasts.get(date, {})
            forecast_temp = forecastsnap.get("temp")
            best_source = forecastsnap.get("source", "ecmwf")

            if forecast_temp is None:
                continue

            sigma = get_sigma(city_slug)
            best_signal = None

            # Find the bucket that matches our forecast
            for o in outcomes:
                t_low, t_high = o["range"]
                if not in_bucket(forecast_temp, t_low, t_high):
                    continue

                volume = o["volume"]
                ask = o["ask"]
                spread = o["spread"]

                if volume < MIN_VOLUME:
                    continue
                if ask >= MAX_PRICE:
                    continue
                if spread > MAX_SLIPPAGE:
                    continue

                p = bucket_prob(forecast_temp, t_low, t_high, sigma)
                ev = calc_ev(p, ask)
                if ev < MIN_EV:
                    continue

                kelly = calc_kelly(p, ask)
                size = bet_size(kelly, balance)
                if size < 0.50:
                    continue

                shares = round(size / ask, 2)
                token_id = get_condition_id(o["market_id"])

                best_signal = {
                    "market_id": o["market_id"],
                    "token_id": token_id,
                    "question": o["question"],
                    "bucket_low": t_low,
                    "bucket_high": t_high,
                    "entry_price": ask,
                    "bid": o["bid"],
                    "spread": spread,
                    "shares": shares,
                    "cost": round(shares * ask, 4),
                    "p": round(p, 4),
                    "ev": round(ev, 4),
                    "kelly": round(kelly, 4),
                    "forecast_temp": forecast_temp,
                    "forecast_src": best_source,
                    "sigma": sigma,
                    "volume": volume,
                }
                break  # Only one bucket per market

            if best_signal:
                bucket_label = f"{best_signal['bucket_low']}-{best_signal['bucket_high']}{unit_sym}"
                print(f"\n  {C.BOLD}📍 {loc['name']} {horizon} — {date}{C.RESET}")
                print(f"  {C.CYAN}  Forecast: {forecast_temp}°F ({best_source}) | {bucket_label}{C.RESET}")
                print(f"  {C.GREEN}  ✅ BUY SIGNAL | ${best_signal['cost']:.2f} @ ${ask:.3f} | "
                      f"EV {best_signal['ev']:+.2f} | Kel {best_signal['kelly']:.2f}{C.RESET}")

                # --- EXECUTE REAL ORDER ---
                result = place_buy_order(
                    market_id=best_signal["market_id"],
                    token_id=best_signal["token_id"],
                    price=best_signal["entry_price"],
                    shares=best_signal["shares"],
                    balance=balance,
                    private_key=PK,
                    wallet=WALLET,
                )

                if result["success"]:
                    new_trades += 1
                    state["total_trades"] += 1
                    balance -= best_signal["cost"]

                    live(f"  [LIVE] BUY {loc['name']} {horizon} | {bucket_label} @ ${best_signal['entry_price']:.3f} "
                         f"| EV {best_signal['ev']:+.2f} | ${best_signal['cost']:.2f}")

                    # Save to market record
                    mkt_record = load_market(city_slug, date) or {
                        "city": city_slug,
                        "city_name": loc["name"],
                        "date": date,
                        "unit": "F",
                        "event_end_date": end_date,
                        "status": "open",
                        "position": None,
                    }
                    mkt_record["position"] = {
                        **best_signal,
                        "order_id": result.get("order_id"),
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                        "status": "open",
                        "closed_at": None,
                        "close_reason": None,
                        "exit_price": None,
                        "pnl": None,
                    }
                    save_market(mkt_record)

                    # Telegram notification — success
                    tg_signal(
                        city=loc["name"], horizon=horizon, date=date,
                        bucket_label=bucket_label, forecast_temp=best_signal["forecast_temp"],
                        entry_price=best_signal["entry_price"], cost=best_signal["cost"],
                        ev=best_signal["ev"], kelly=best_signal["kelly"],
                        success=True,
                    )
                else:
                    errors.append(f"{loc['name']} {horizon}: {result['reason']}")
                    warn(f"  ❌ Order failed: {result['reason']}")

                    # Telegram notification — failure
                    tg_signal(
                        city=loc["name"], horizon=horizon, date=date,
                        bucket_label=bucket_label, forecast_temp=best_signal["forecast_temp"],
                        entry_price=best_signal["entry_price"], cost=best_signal.get("cost", 0),
                        ev=best_signal["ev"], kelly=best_signal["kelly"],
                        success=False, reason=result.get("reason", "unknown"),
                    )
            else:
                # No signal — show why
                for o in outcomes:
                    t_low, t_high = o["range"]
                    if not in_bucket(forecast_temp, t_low, t_high):
                        continue
                    ask = o["ask"]
                    p = bucket_prob(forecast_temp, t_low, t_high, sigma)
                    ev = calc_ev(p, ask)
                    skip(f" {forecast_temp}°F bucket {t_low}-{t_high}F @ ${ask:.3f} EV={ev:.2f} — skipped")
                    break

        print("ok")

    # Save updated balance
    state["balance"] = round(balance, 4)
    save_state(state)

    print(f"\n{'=' * 60}")
    print(f"  Scanned:    {len(LOCATIONS)} cities")
    print(f"  New trades: {C.GREEN}{new_trades}{C.RESET}")
    print(f"  Errors:     {len(errors)}")
    print(f"  Balance:    ${balance:.4f}")
    print(f"{'=' * 60}\n")

    # Telegram scan summary
    tg_scan_summary(new_trades=new_trades, errors=len(errors),
                    balance=balance, cities=len(LOCATIONS))

    return new_trades, errors

# =============================================================================
# STATUS
# =============================================================================

def show_status():
    """Show current balance, positions, and open orders."""
    balance = get_usdc_balance(WALLET)
    pol_bal = get_pol_balance(WALLET)

    print(f"\n{C.BOLD}{C.CYAN}📊 Bot v3 — Status{C.RESET}")
    print("=" * 60)
    print(f"  Wallet:    {WALLET[:8]}...{WALLET[-4:]}")
    print(f"  USDC.e:    ${balance:.4f}")
    print(f"  POL:       {pol_bal:.4f}")
    print()

    # Open orders from CLOB
    orders = get_clob_positions()
    if orders:
        print(f"  Open orders: {len(orders)}")
        for o in orders:
            print(f"    {o.get('side','?')} {o.get('size','?')} @ ${o.get('price','?')} "
                  f"[{o.get('marketID','')[:16]}...]")
    else:
        print(f"  Open orders: 0")

    # Local market positions
    markets = load_all_markets()
    open_pos = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
    if open_pos:
        print(f"\n  Open positions (local): {len(open_pos)}")
        for m in open_pos:
            pos = m["position"]
            unit_sym = "F"
            label = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"
            print(f"    {m['city_name']} {m['date']} | {label} | "
                  f"entry ${pos['entry_price']:.3f} | cost ${pos.get('cost',0):.2f}")
    else:
        print(f"\n  Open positions: 0")

    print(f"{'=' * 60}\n")

# =============================================================================
# MAIN LOOP
# =============================================================================

MONITOR_INTERVAL = 600   # 10 minutes between monitor cycles

def run_loop():
    print(f"\n{C.BOLD}{C.CYAN}🌤  Weather Trading Bot v3 — LIVE{C.RESET}")
    print("=" * 60)
    print(f"  Wallet:    {WALLET[:8]}...{WALLET[-4:]}")
    print(f"  Cities:   {len(LOCATIONS)}")
    print(f"  Max bet:  ${MAX_BET} | Kelly fraction: {KELLY_FRAC}")
    print(f"  Min EV:   {MIN_EV*100:.0f}%")
    print(f"  Scan:     every {SCAN_INTERVAL//60} min")
    print(f"  Monitor:  every {MONITOR_INTERVAL//60} min")
    print()

    # Check approvals on startup
    ok("Checking approvals...")
    ensure_approvals()

    last_full_scan = 0

    while True:
        now_ts = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if now_ts - last_full_scan >= SCAN_INTERVAL:
            print(f"[{now_str}] Full scan...")
            try:
                new_trades, errors = scan_and_trade()
                last_full_scan = time.time()
            except Exception as e:
                warn(f"Scan error: {e}")
                time.sleep(60)
                continue
        else:
            print(f"[{now_str}] Monitoring...")
            time.sleep(MONITOR_INTERVAL)

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    if not PK or not WALLET:
        print("ERROR: PK and WALLET must be set in weatherbot/.env")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "run":
        run_loop()
    elif cmd == "scan":
        scan_and_trade()
    elif cmd == "status":
        show_status()
    elif cmd == "cancel":
        market_id = sys.argv[2] if len(sys.argv) > 2 else None
        if market_id:
            print(f"Cancelling orders for market: {market_id}")
        else:
            count = cancel_all_orders()
            print(f"Cancelled {count} orders")
    else:
        print(f"Usage: python bot_v3.py [scan|run|status|cancel]")
