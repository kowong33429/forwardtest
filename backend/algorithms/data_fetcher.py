import requests
import pandas as pd
import numpy as np

def get_top_volume_symbols(limit=30):
    """Fetch Top N USDT pairs by 24h volume on Binance (Free, No API Key)"""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        
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
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"] # Fallback

def fetch_klines(symbol, interval="4h", limit=250):
    """Fetch recent OHLCV data for a symbol"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if not isinstance(data, list):
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
