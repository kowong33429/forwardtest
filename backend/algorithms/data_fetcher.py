import requests
import json
import threading
from urllib.parse import quote
import pandas as pd
import numpy as np
import traceback
import time
import logging
from services import mt5_service

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataFetcher")

BINANCE_BASE_URLS = [
    "https://data-api.binance.vision", # Official data endpoint, usually bypasses US blocks
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api.binance.com"
]

_best_binance_url = None

# Cache of the USDT volume ranking. The full /ticker/24hr payload is ~2 MB, so we
# only fetch it every RANKING_TTL seconds and keep just the symbol names, not the payload.
RANKING_TTL = 300
_ranking_lock = threading.Lock()
_ranking_cache = {"ts": 0.0, "ranked": [], "all": frozenset()}

def safe_binance_request(endpoint):
    """
    Tries multiple Binance base URLs until one succeeds.
    Useful for bypassing geo-blocks on cloud servers.
    """
    global _best_binance_url
    logger.info(f"Initiating Binance API call for endpoint: {endpoint}")
    last_error = None
    
    urls_to_try = BINANCE_BASE_URLS.copy()
    if _best_binance_url and _best_binance_url in urls_to_try:
        urls_to_try.remove(_best_binance_url)
        urls_to_try.insert(0, _best_binance_url)
        
    for base_url in urls_to_try:
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
                logger.info(f"Successfully fetched data from {url}. Payload size: {len(response.content)} bytes.")
                _best_binance_url = base_url
                return data
            else:
                msg = f"Failed with status {response.status_code} at {url}: {response.text[:100]}"
                logger.warning(msg)
                last_error = Exception(msg)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error at {url}: {e}")
            last_error = e
            continue
            
    logger.error(f"CRITICAL: All Binance endpoints failed for endpoint {endpoint}. Last error: {last_error}")
    return None

def _is_tradable_usdt(sym):
    return sym.endswith('USDT') and 'UP' not in sym and 'DOWN' not in sym

def _get_usdt_ranking():
    """
    Returns (ranked_symbols, all_usdt_symbols), cached for RANKING_TTL seconds.
    Uses type=MINI to roughly halve the payload; the parsed list is discarded right after ranking.
    """
    with _ranking_lock:
        if _ranking_cache["ranked"] and time.time() - _ranking_cache["ts"] < RANKING_TTL:
            return _ranking_cache["ranked"], _ranking_cache["all"]

        data = safe_binance_request("/api/v3/ticker/24hr?type=MINI")
        if not data or not isinstance(data, list):
            # Serve stale ranking rather than nothing
            return _ranking_cache["ranked"], _ranking_cache["all"]

        usdt_pairs = [(d['symbol'], float(d['quoteVolume'])) for d in data if _is_tradable_usdt(d['symbol'])]
        del data
        usdt_pairs.sort(key=lambda x: x[1], reverse=True)

        _ranking_cache["ranked"] = [sym for sym, _ in usdt_pairs]
        _ranking_cache["all"] = frozenset(_ranking_cache["ranked"])
        _ranking_cache["ts"] = time.time()
        return _ranking_cache["ranked"], _ranking_cache["all"]

def get_top_volume_symbols(limit=30):
    """Fetch Top N USDT pairs by 24h volume on Binance (Free, No API Key)"""
    try:
        ranked, _ = _get_usdt_ranking()

        if not ranked:
            print("Binance API error: empty volume ranking")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"] # Fallback

        # Pick top limit symbols, ensuring BTC is included
        symbols = ranked[:limit]
        if 'BTCUSDT' not in symbols:
            symbols[0] = 'BTCUSDT'
            
        return symbols
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"] # Fallback

def fetch_klines(symbol, interval="4h", limit=250, algo_type="crypto"):
    """Fetch recent OHLCV data for a symbol based on algo_type"""
    if algo_type == "forex":

        return mt5_service.fetch_historical_klines(symbol, timeframe=interval, limit=limit)
    elif algo_type == "stock":
        logger.warning("Stock data fetcher not implemented yet.")
        return pd.DataFrame()
        
    # Default to crypto
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

def get_market_data(additional_symbols=None, algo_type="crypto"):
    """Returns a dictionary of DataFrames for symbols based on algo_type"""
    if algo_type == "crypto":
        symbols = set(get_top_volume_symbols(50))
    elif algo_type == "forex":
        symbols = {"XAUUSDc"}
    else:
        # For stock, we might not have a "top volume" endpoint, just use portfolio symbols
        symbols = set()
        
    if additional_symbols:
        symbols.update(additional_symbols)
        
    data_dict = {}
    for sym in symbols:
        # Forex ใช้ Daily candle, Crypto ใช้ 4h candle
        interval = "1d" if algo_type == "forex" else "4h"
        df = fetch_klines(sym, interval=interval, algo_type=algo_type)
        if df is not None and not df.empty:
            data_dict[sym] = df
    return data_dict

def get_live_prices(limit=50, additional_symbols=None):
    """Fetch live prices for the top N USDT pairs plus any additionally specified symbols"""
    try:
        ranked, all_usdt = _get_usdt_ranking()
        if not ranked:
            return []

        wanted = list(ranked[:limit])
        if 'BTCUSDT' not in wanted:
            wanted.insert(0, 'BTCUSDT')
        if additional_symbols:
            wanted.extend(s for s in additional_symbols if s in all_usdt and s not in wanted)

        # Only request the symbols we display (~KBs instead of ~2 MB)
        symbols_param = quote(json.dumps(wanted, separators=(',', ':')))
        data = safe_binance_request(f"/api/v3/ticker/24hr?symbols={symbols_param}")

        if not data or not isinstance(data, list):
            return []

        by_symbol = {d['symbol']: d for d in data}
        top_pairs = [by_symbol[s] for s in wanted if s in by_symbol]

        # Format for frontend
        prices = [{"symbol": p['symbol'], "price": float(p['lastPrice']), "change": float(p['priceChangePercent'])} for p in top_pairs]
        
        if additional_symbols:
            held_prices = [p for p in prices if p['symbol'] in additional_symbols]
            logger.info(f"Current held crypto symbols prices: {held_prices}")
            
            # Fetch missing symbols from MT5 Bridge (Forex/Futures)
            found_symbols = set(p['symbol'] for p in prices)
            missing_symbols = [s for s in additional_symbols if s not in found_symbols]
            
            for sym in missing_symbols:
                try:
                    from services.mt5_service import BASE_URL, HEADERS
                    resp = requests.get(f"{BASE_URL}/symbol", params={"symbol": sym}, headers=HEADERS, timeout=5)
                    if resp.status_code == 200:
                        spec = resp.json()
                        ask = spec.get("ask", 0)
                        bid = spec.get("bid", 0)
                        if ask > 0 and bid > 0:
                            mid_price = (ask + bid) / 2
                            prices.append({
                                "symbol": sym, 
                                "price": mid_price, 
                                "change": float(spec.get("price_change", 0.0))
                            })
                except Exception as e:
                    logger.warning(f"Failed to fetch live price for MT5 symbol {sym}: {e}")
        
        return prices
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching live prices: {e}")
        return []
