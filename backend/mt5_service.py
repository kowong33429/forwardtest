import os
import logging
import asyncio
import threading
from metaapi_cloud_sdk import MetaApi

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
