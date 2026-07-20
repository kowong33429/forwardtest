import requests
import pandas as pd
import numpy as np
import traceback
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataFetcher")

BINANCE_BASE_URLS = [
    "https://data-api.binance.vision", # Official data endpoint, usually bypasses US blocks
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api.binance.com"
]

def safe_binance_request(endpoint):
    """
    Tries multiple Binance base URLs until one succeeds.
    Useful for bypassing geo-blocks on cloud servers.
    """
    logger.info(f"Initiating Binance API call for endpoint: {endpoint}")
    last_error = None
    for base_url in BINANCE_BASE_URLS:
        url = f"{base_url}{endpoint}"
        logger.info(f"Attempting GET {url}")
        try:
            response = requests.get(url, timeout=5)
            logger.info(f"Response from {url} - Status Code: {response.status_code}")
            
            # If we get a 451 (Unavailable For Legal Reasons) or similar geo-block code, we continue
            if response.status_code == 200:
                data = response.json()
                # Sometimes it returns 200 but contains an error msg inside json
                if isinstance(data, dict) and data.get("code") and data.get("msg"):
                    if "restricted location" in data.get("msg").lower():
                        logger.warning(f"Geo-blocked at {url}: {data.get('msg')}")
                        continue # Try next URL
                logger.info(f"Successfully fetched data from {url}. Payload size: {len(str(data))} characters.")
                return data
            else:
                logger.warning(f"Failed with status {response.status_code} at {url}: {response.text[:100]}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error at {url}: {e}")
            last_error = e
            continue
            
    logger.error(f"CRITICAL: All Binance endpoints failed for endpoint {endpoint}. Last error: {last_error}")
    return None

def get_top_volume_symbols(limit=30):
    """Fetch Top N USDT pairs by 24h volume on Binance (Free, No API Key)"""
    try:
        data = safe_binance_request("/api/v3/ticker/24hr")
        
        if not data or not isinstance(data, list):
            print(f"Binance API error or unexpected format: {data}")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"] # Fallback
            
        # Filter for USDT pairs, exclude stablecoins/derivatives if possible
        usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and 'UP' not in d['symbol'] and 'DOWN' not in d['symbol']]
        
        # Sort by volume (quote volume is usually better for USD value)
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        
        # Pick top limit symbols, ensuring BTC is included
        symbols = [p['symbol'] for p in usdt_pairs[:limit]]
        if 'BTCUSDT' not in symbols:
            symbols[0] = 'BTCUSDT'
            
        return symbols
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"] # Fallback

def fetch_klines(symbol, interval="4h", limit=250):
    """Fetch recent OHLCV data for a symbol"""
    try:
        data = safe_binance_request(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
        
        if not data or not isinstance(data, list):
            return None
            
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        df.set_index('close_time', inplace=True)
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        return df[['open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching klines for {symbol}: {e}")
        return None

def get_market_data():
    """Returns a dictionary of DataFrames for the top 30 coins"""
    symbols = get_top_volume_symbols(30)
    data_dict = {}
    for sym in symbols:
        df = fetch_klines(sym)
        if df is not None and not df.empty:
            data_dict[sym] = df
    return data_dict

def get_live_prices(limit=10):
    """Fetch live prices for the top N USDT pairs"""
    try:
        data = safe_binance_request("/api/v3/ticker/24hr")
        
        if not data or not isinstance(data, list):
            return []
            
        usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and 'UP' not in d['symbol'] and 'DOWN' not in d['symbol']]
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        
        # Format for frontend
        prices = [{"symbol": p['symbol'], "price": float(p['lastPrice']), "change": float(p['priceChangePercent'])} for p in usdt_pairs[:limit]]
        
        # Ensure BTC is always there for demo purposes
        if not any(p['symbol'] == 'BTCUSDT' for p in prices):
            btc_data = next((p for p in usdt_pairs if p['symbol'] == 'BTCUSDT'), None)
            if btc_data:
                prices[0] = {"symbol": btc_data['symbol'], "price": float(btc_data['lastPrice']), "change": float(btc_data['priceChangePercent'])}
                
        return prices
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching live prices: {e}")
        return []
