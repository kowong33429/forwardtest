import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Backtester")

def fetch_historical_4h_klines(symbol, days=730):
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    all_klines = []
    
    current_start = start_time
    while current_start < end_time:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=4h&limit=1000&startTime={current_start}&endTime={end_time}"
        try:
            res = requests.get(url, timeout=5)
            data = res.json()
            if not isinstance(data, list) or not data:
                break
            all_klines.extend(data)
            current_start = data[-1][0] + 1
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error fetching backtest data for {symbol}: {e}")
            break
            
    if not all_klines:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    df.set_index('close_time', inplace=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df[['open', 'high', 'low', 'close', 'volume']]

def run_backtest(algo_func, initial_balance=10000.0, days=730):
    """
    Simulates a backtest for the given algorithm function.
    To save time and CPU, it rebalances every 7 days (42 bars of 4H).
    """
    # Use top 10 coins instead of 30 to keep it very fast for AI iterations
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "DOGEUSDT"]
    
    logger.info(f"Downloading {days} days of historical 4H data for {len(symbols)} symbols...")
    market_data_full = {}
    for sym in symbols:
        df = fetch_historical_4h_klines(sym, days)
        if not df.empty:
            market_data_full[sym] = df
            
    if not market_data_full:
        return initial_balance
        
    # Find the common timeline based on BTC
    if "BTCUSDT" not in market_data_full:
        return initial_balance
        
    btc_index = market_data_full["BTCUSDT"].index
    
    balance = initial_balance
    current_holdings = {} # symbol -> amount
    
    # Step through history (Weekly rebalance = step 42)
    step = 42 
    for i in range(200, len(btc_index), step): # Start at 200 for moving averages
        current_time = btc_index[i]
        
        # Prepare snapshot
        snapshot = {}
        current_prices = {}
        for sym, df in market_data_full.items():
            if current_time in df.index:
                # We can just slice up to this time
                df_slice = df.loc[:current_time].copy()
                if not df_slice.empty:
                    snapshot[sym] = df_slice
                    current_prices[sym] = df_slice['close'].iloc[-1]
                
        # Calculate current total value
        total_value = balance
        for sym, amount in current_holdings.items():
            if sym in current_prices:
                total_value += amount * current_prices[sym]
                
        # Get target allocations
        try:
            targets, _ = algo_func(snapshot, current_holdings=list(current_holdings.keys()), total_value=total_value)
        except Exception as e:
            logger.error(f"Algorithm error during backtest at {current_time}: {e}")
            targets = {}
            
        # Execute sells
        for sym, amount in list(current_holdings.items()):
            price = current_prices.get(sym)
            if not price: continue
            target_weight = targets.get(sym, 0.0)
            if target_weight == 0:
                balance += amount * price
                del current_holdings[sym]
                
        # Execute buys
        for sym, target_weight in targets.items():
            if target_weight > 0:
                price = current_prices.get(sym)
                if not price: continue
                target_usd = total_value * target_weight
                
                # Full replacement for simplicity
                if sym not in current_holdings and balance >= target_usd * 0.99:
                    buy_amount = target_usd / price
                    balance -= target_usd
                    current_holdings[sym] = buy_amount
                    
    # Final liquidation
    for sym, amount in current_holdings.items():
        price = market_data_full[sym]['close'].iloc[-1]
        balance += amount * price
        
    logger.info(f"Backtest completed. Final Balance: ${balance:.2f}")
    return balance
