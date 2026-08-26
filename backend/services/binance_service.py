import os
import time
import hmac
import hashlib
import requests
import logging

logger = logging.getLogger("BinanceService")

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BASE_URL = "https://api.binance.com" # Can be configured to fapi.binance.com for futures

def _get_signature(query_string, secret):
    return hmac.new(secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def execute_trade(symbol, direction, volume, order_type="MARKET"):
    """
    Executes a market order via Binance API.
    """
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("Binance API keys not configured. Cannot execute real trade.")
        return {"status": "error", "message": "Missing API keys"}

    endpoint = "/api/v3/order"
    
    side = "BUY" if direction.upper() == "LONG" else "SELL"
    
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": volume,
        "timestamp": int(time.time() * 1000)
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = _get_signature(query_string, BINANCE_API_SECRET)
    
    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    headers = {
        "X-MBX-APIKEY": BINANCE_API_KEY
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            logger.info(f"Binance trade executed successfully: {data.get('orderId')}")
            return {"status": "success", "ticket": str(data.get("orderId")), "data": data}
        else:
            logger.error(f"Binance trade failed: {data}")
            return {"status": "error", "message": data.get("msg", "Unknown error")}
    except Exception as e:
        logger.error(f"Exception during Binance trade: {e}")
        return {"status": "error", "message": str(e)}

def execute_futures_trade(symbol, direction, volume, order_type="MARKET"):
    """
    Executes a market order via Binance Futures API.
    """
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("Binance API keys not configured. Cannot execute real trade.")
        return {"status": "error", "message": "Missing API keys"}

    endpoint = "/fapi/v1/order"
    fapi_base_url = "https://fapi.binance.com"
    
    side = "BUY" if direction.upper() == "LONG" else "SELL"
    
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": volume,
        "timestamp": int(time.time() * 1000)
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = _get_signature(query_string, BINANCE_API_SECRET)
    
    url = f"{fapi_base_url}{endpoint}?{query_string}&signature={signature}"
    headers = {
        "X-MBX-APIKEY": BINANCE_API_KEY
    }
    
    try:
        response = requests.post(url, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            logger.info(f"Binance futures trade executed successfully: {data.get('orderId')}")
            return {"status": "success", "ticket": str(data.get("orderId")), "data": data}
        else:
            logger.error(f"Binance futures trade failed: {data}")
            return {"status": "error", "message": data.get("msg", "Unknown error")}
    except Exception as e:
        logger.error(f"Exception during Binance futures trade: {e}")
        return {"status": "error", "message": str(e)}
