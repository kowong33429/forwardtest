import os
from dotenv import load_dotenv
load_dotenv()
import logging
import asyncio
import threading
from metaapi_cloud_sdk import MetaApi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger("MT5Service")

# Global variables to cache the MetaApi connection
_api = None
_account = None
_connection = None
_loop = asyncio.new_event_loop()

def _start_background_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Start the event loop in a background thread once
_thread = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True)
_thread.start()

def execute_sync(coro):
    """Run an async coroutine synchronously using the cached background loop"""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

async def _get_connection():
    global _api, _account, _connection
    token = os.getenv("METAAPI_TOKEN", "")
    account_id = os.getenv("METAAPI_ACCOUNT_ID", "")
    
    if not token or not account_id:
        raise Exception("METAAPI_TOKEN or METAAPI_ACCOUNT_ID not set")
        
    if _connection is None:
        logger.info("Initializing new MetaApi connection...")
        _api = MetaApi(token)
        _account = await _api.metatrader_account_api.get_account(account_id)
        
        if _account.state != 'DEPLOYED':
            raise Exception(f"Account state is {_account.state}, needs to be DEPLOYED.")
            
        _connection = _account.get_rpc_connection()
        await _connection.connect()
        await _connection.wait_synchronized()
        logger.info("MetaApi connection synchronized!")
        
    return _connection

async def _check_health_async():
    try:
        connection = await _get_connection()
        global _account
        account_info = await connection.get_account_information()
        
        health_data = {
            "status": "connected",
            "login": account_info.get('login'),
            "server": _account.server,
            "balance": account_info.get('balance'),
            "equity": account_info.get('equity'),
            "margin_free": account_info.get('marginFree'),
            "currency": account_info.get('currency')
        }
        return health_data
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        # Reset connection on error to force a reconnect next time
        global _connection
        _connection = None
        return {"status": "error", "message": str(e)}

def check_health():
    """
    Checks the connection health to the MT5 account via MetaApi Cloud.
    Uses a cached connection so it is lightning fast after the first call.
    """
    return execute_sync(_check_health_async())

async def _execute_trade_async(symbol, direction, volume, sl, tp, comment):
    try:
        connection = await _get_connection()
        options = {"comment": comment}
        
        if direction.upper() == "LONG":
            result = await connection.create_market_buy_order(symbol, volume, sl, tp, options)
        else:
            result = await connection.create_market_sell_order(symbol, volume, sl, tp, options)
            
        return {"status": "success", "ticket": result.get('orderId')}
    except Exception as e:
        logger.error(f"Trade execution failed: {str(e)}")
        # Reset connection on error
        global _connection
        _connection = None
        return {"status": "error", "message": str(e)}

def execute_trade(symbol, direction, volume, sl, tp, comment="ForwardTest AI"):
    """
    Executes a market order via MetaApi Cloud.
    """
    return execute_sync(_execute_trade_async(symbol, direction, volume, sl, tp, comment))

async def _fetch_historical_klines_async(symbol, timeframe="4h", limit=250):
    try:
        connection = await _get_connection()
        # Ensure timeframe is formatted correctly for MetaApi (e.g., '1h', '4h', '1d')
        # MetaApi Python SDK usually uses `get_history_storage().get_historical_candles()` or `connection.get_historical_candles()`
        # We will try the direct connection method.
        
        # In MetaApi, timeframes are typically '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1mn'
        mt5_timeframe = timeframe
        if timeframe == "1d":
            mt5_timeframe = "1d"
            
        logger.info(f"Fetching {limit} historical candles for {symbol} ({mt5_timeframe}) via MetaApi...")
        candles = await connection.get_historical_candles(symbol, mt5_timeframe, None, limit)
        
        if not candles:
            logger.warning(f"MetaApi returned no historical candles for {symbol}.")
            return None
            
        # Convert to DataFrame matching expected format
        df = pd.DataFrame(candles)
        # Rename columns if necessary. MetaApi usually returns: time, open, high, low, close, tickVolume
        if 'time' in df.columns:
            df['close_time'] = pd.to_datetime(df['time'])
            df.set_index('close_time', inplace=True)
            
        # Ensure standard column names
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = df[col].astype(float)
                
        # Map tickVolume to volume
        if 'tickVolume' in df.columns and 'volume' not in df.columns:
            df['volume'] = df['tickVolume'].astype(float)
        elif 'volume' not in df.columns:
            df['volume'] = 0.0
            
        return df[['open', 'high', 'low', 'close', 'volume']]
        
    except Exception as e:
        logger.error(f"Failed to fetch historical klines via MetaApi for {symbol}: {e}")
        error_msg = str(e).lower()
        if "not connected to broker" in error_msg or "timeout" in error_msg:
            logger.critical("ACTION REQUIRED: Your MetaApi account is NOT connected to the broker (e.g. Exness). Please go to the MetaApi dashboard and check your MT5 server, login, and password!")
        
        # Reset connection so it can attempt to reconnect later
        global _connection
        _connection = None
        return None

def fetch_historical_klines(symbol, timeframe="4h", limit=250):
    """
    Fetches historical OHLC data from MT5.
    Returns a pandas DataFrame.
    """
    return execute_sync(_fetch_historical_klines_async(symbol, timeframe, limit))

async def _check_market_metaapi_async(symbol):
    try:
        connection = await _get_connection()
        
        # You can fetch the symbol specification
        spec = await connection.get_symbol_specification(symbol)
        
        # Usually brokers will set tradeMode to 0 (SYMBOL_TRADE_MODE_DISABLED) during holidays or unexpected closures
        if hasattr(spec, 'tradeMode') and spec.tradeMode == 0:
            return False, f"MARKET CLOSED: Trading is disabled for {symbol} by broker."
            
        return True, "Market is open."
    except Exception as e:
        logger.error(f"MetaApi market check failed for {symbol}: {e}")
        error_msg = str(e).lower()
        if "not connected to broker" in error_msg or "timeout" in error_msg:
            logger.critical("ACTION REQUIRED: Your MetaApi account is NOT connected to the broker (e.g. Exness). Please go to the MetaApi dashboard and check your MT5 server, login, and password!")
            
        # If API fails (e.g. timeout), we fallback to allowing it so the engine doesn't completely halt on API lag,
        # but the subsequent historical data fetch will likely fail anyway.
        return True, "Market is open (MetaApi check failed/timeout)."

def is_forex_market_open(symbol="XAUUSDc"):
    """
    Hybrid Check:
    1. Check if the Forex market is open based on US/Eastern timezone (Weekend check).
    2. Check MetaApi for specific broker holiday closures.
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
        
    # 2. MetaApi Check (Holidays / Broker closures)
    return execute_sync(_check_market_metaapi_async(symbol))
