import os
import requests
import logging
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("MT5Service")

# Get base path from .env, fallback to the requested IP
BASE_URL = os.getenv("MT5_BRIDGE_URL", "http://38.54.33.151:8000")
API_SECRET_TOKEN = os.getenv("MT5_API_SECRET")
HEADERS = {"Authorization": f"Bearer {API_SECRET_TOKEN}"}

def check_health():
    """
    Checks the connection health to the MT5 account via our custom Bridge API.
    """
    try:
        # Check both bridge status and account info
        health_resp = requests.get(f"{BASE_URL}/", headers=HEADERS, timeout=10)
        health_resp.raise_for_status()
        
        acc_resp = requests.get(f"{BASE_URL}/account", headers=HEADERS, timeout=10)
        acc_resp.raise_for_status()
        
        acc_data = acc_resp.json()
        
        return {
            "status": "connected",
            "login": acc_data.get('login'),
            "server": acc_data.get('server'),
            "balance": acc_data.get('balance'),
            "equity": acc_data.get('equity'),
            "margin_free": acc_data.get('margin_free'),
            "currency": acc_data.get('currency', 'USD')
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "error", "message": str(e)}

def execute_trade(symbol, direction, volume, sl, tp, comment="ForwardTest AI"):
    """
    Executes a market order via our custom Bridge API.
    """
    try:
        payload = {
            "symbol": symbol,
            "action": "buy" if direction.upper() == "LONG" else "sell",
            "volume": float(volume),
            "sl": float(sl) if sl else 0.0,
            "tp": float(tp) if tp else 0.0,
            "comment": comment
        }
        
        resp = requests.post(f"{BASE_URL}/trade", json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        result = resp.json()
        if result.get("success"):
            return {"status": "success", "ticket": result.get("order_ticket"), "price": result.get("price"), "volume": result.get("volume")}
        else:
            return {"status": "error", "message": result.get("message", "Unknown error")}
            
    except Exception as e:
        logger.error(f"Trade execution failed: {str(e)}")
        return {"status": "error", "message": str(e)}

def close_position(ticket, comment="Close position"):
    """
    Closes a specific position by ticket via the Bridge API.
    Never send an opposite market order instead: on a hedging account that opens a new position.
    Returns realized profit/price from MT5 deal history when available.
    """
    try:
        payload = {"ticket": int(ticket), "comment": comment}
        resp = requests.post(f"{BASE_URL}/close", json=payload, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            detail = resp.json().get("detail", "")
            if "Position" not in str(detail):
                # Old bridge without /close: do NOT fall back to an opposite order (opens a hedge)
                return {"status": "error", "message": "Bridge has no /close endpoint; deploy the updated mt5-bridge"}
            return {"status": "not_found", "message": detail}
        resp.raise_for_status()

        result = resp.json()
        if result.get("success"):
            return {"status": "success", **result}
        return {"status": "error", "message": result.get("message", "Unknown error")}

    except Exception as e:
        logger.error(f"Close position {ticket} failed: {str(e)}")
        return {"status": "error", "message": str(e)}

def get_position_deals(ticket):
    """
    Fetches the realized exit (price/profit/reason) of a closed position via the Bridge API.
    Returns None if the position has no exit deals (still open or unknown).
    """
    try:
        resp = requests.get(f"{BASE_URL}/deals", params={"ticket": int(ticket)}, headers=HEADERS, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch deals for position {ticket}: {str(e)}")
        return None

def fetch_historical_klines(symbol, timeframe="4h", limit=250):
    """
    Fetches historical OHLC data from MT5 via the Bridge API.
    Returns a pandas DataFrame.
    """
    try:
        params = {
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit
        }
        resp = requests.get(f"{BASE_URL}/history", params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        
        candles = resp.json()
        if not candles:
            return None
            
        df = pd.DataFrame(candles)
        
        # Convert time to datetime (MT5 returns Unix timestamp)
        df['close_time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('close_time', inplace=True)
        
        # Ensure column names map to what the engine expects
        df['volume'] = df['tickVolume'].astype(float)
        
        return df[['open', 'high', 'low', 'close', 'volume']]
        
    except Exception as e:
        logger.error(f"Failed to fetch historical klines via API for {symbol}: {e}")
        return None

def get_open_positions():
    """
    Fetches all open positions via our custom Bridge API.
    Returns None (not []) on failure so callers can tell "no positions" from "unknown".
    """
    try:
        resp = requests.get(f"{BASE_URL}/positions", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch open positions: {str(e)}")
        return None

def modify_position(ticket, sl, tp):
    """
    Modifies the SL and TP of an existing position via our custom Bridge API.
    """
    try:
        payload = {
            "ticket": int(ticket),
            "sl": float(sl),
            "tp": float(tp)
        }
        resp = requests.post(f"{BASE_URL}/modify", json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        result = resp.json()
        if result.get("success"):
            return {"status": "success", "message": "Position modified successfully"}
        else:
            return {"status": "error", "message": result.get("message", "Unknown error")}
            
    except Exception as e:
        logger.error(f"Failed to modify position {ticket}: {str(e)}")
        return {"status": "error", "message": str(e)}

def is_forex_market_open(symbol="XAUUSDc"):
    """
    Hybrid Check:
    1. Check if the Forex market is open based on US/Eastern timezone (Weekend check).
    2. Check MT5 symbol info via Bridge API.
    Returns: (bool, str) - (is_open, reason)
    """
    try:
        import zoneinfo
        eastern = zoneinfo.ZoneInfo("US/Eastern")
    except ImportError:
        import pytz
        eastern = pytz.timezone("US/Eastern")
        
    now = datetime.now(eastern)
    
    # 1. Fast Local Timezone Check (Weekend)
    if now.weekday() == 4 and now.hour >= 17:
        return False, "MARKET CLOSED: Forex market closes on Friday at 5:00 PM EST."
    elif now.weekday() == 5:
        return False, "MARKET CLOSED: Forex market is closed on Saturday."
    elif now.weekday() == 6 and now.hour < 17:
        return False, "MARKET CLOSED: Forex market opens on Sunday at 5:00 PM EST."
        
    # 2. Check via Bridge API
    try:
        resp = requests.get(f"{BASE_URL}/symbol", params={"symbol": symbol}, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        
        spec = resp.json()
        
        # MT5 SYMBOL_TRADE_MODE_DISABLED = 0
        if spec.get("trade_mode") == 0:
            return False, f"MARKET CLOSED: Trading is disabled for {symbol} by broker."
            
        return True, "Market is open."
    except Exception as e:
        logger.error(f"Bridge market check failed for {symbol}: {e}")
        # Fallback to allowing it so the engine doesn't completely halt on API lag
        return True, "Market is open (Bridge check failed/timeout)."
