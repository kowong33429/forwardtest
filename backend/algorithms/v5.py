import pandas as pd
import numpy as np
import requests
import time
import traceback
import pandas_ta as ta
from backtester import run_backtest

# --- System Constants for CMC ---
CMC_API_KEY = '5546f69e0fcd426bafd5f2d892673cc6'

_cmc_cache = None
_cmc_last_fetch = 0

def fetch_cmc_data_cached(limit=300):
    global _cmc_cache, _cmc_last_fetch
    if _cmc_cache is not None and (time.time() - _cmc_last_fetch) < 3600:
        return _cmc_cache

    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    parameters = {'start':'1', 'limit': limit, 'convert':'USD'}
    headers = {'Accepts': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, params=parameters, timeout=10)
        data = response.json().get('data', [])
        _cmc_cache = data
        _cmc_last_fetch = time.time()
        return data
    except Exception as e:
        print(f"CMC API Error: {e}")
        return []

def get_binance_listed_symbols():
    url = "https://data-api.binance.vision/api/v3/exchangeInfo"
    try:
        response = requests.get(url, timeout=10).json() 
        binance_symbols = {
            item['baseAsset']: item['symbol'] 
            for item in response.get('symbols', []) 
            if item.get('quoteAsset') == 'USDT' and item.get('status') == 'TRADING'
        }
        return binance_symbols
    except Exception as e:
        print(f"Error fetching binance symbols: {e}")
        return {}

def fetch_binance_4h_klines(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit=50"
        response = requests.get(url, timeout=10).json()
        if not response or type(response) != list: return None
        df = pd.DataFrame(response, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'quote_asset_volume', 'number_of_trades', 
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def analyze_4h_technicals(df_ohlcv):
    df_ohlcv['RSI_14'] = ta.rsi(df_ohlcv['close'], length=14)
    df_ohlcv['EMA_9'] = ta.ema(df_ohlcv['close'], length=9)
    df_ohlcv['EMA_20'] = ta.ema(df_ohlcv['close'], length=20)
    df_ohlcv['Vol_SMA_20'] = ta.sma(df_ohlcv['volume'], length=20)
    
    df_ohlcv = df_ohlcv.dropna()
    if df_ohlcv.empty: return 0, 50, 0

    latest = df_ohlcv.iloc[-1]
    prev_high = df_ohlcv['high'].iloc[-2] if len(df_ohlcv) >= 2 else df_ohlcv['high'].iloc[-1]
    
    is_bullish_cross = latest['EMA_9'] > latest['EMA_20']
    is_vol_anomaly = latest['volume'] > (latest['Vol_SMA_20'] * 1.5)
    is_mss = latest['close'] > prev_high 
    rsi = latest['RSI_14']
    
    ta_score = 0
    if is_bullish_cross: ta_score += 20
    if is_vol_anomaly: ta_score += 40
    if is_mss: ta_score += 40
    
    if rsi > 70:
        ta_score -= 20
        
    return max(0, ta_score), rsi, latest['close']

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0, **kwargs):
    """
    V5.2 Binance Low-Cap Sniper (Specifically targeted for 10M-300M Market Cap)
    Scans the market independently for Forward Test, ignores default High-Cap data_dict.
    """
    symbol_reasons = {}
    targets = {}
    coins_list = []
    
    # Check if we are running in a Backtest environment
    is_backtest = "BTCUSDT" in data_dict and len(data_dict) <= 15
    
    cmc_data = fetch_cmc_data_cached(limit=300)
    binance_symbols = get_binance_listed_symbols() if not is_backtest else {}
    
    if is_backtest:
        # ---- BACKTEST MODE: Test TA logic on provided data (bypasses MC limit) ----
        for sym, df in data_dict.items():
            if len(df) < 20: continue
            ta_score, rsi, current_price = analyze_4h_technicals(df.copy())
            
            if (ta_score >= 80 and 40 <= rsi <= 65) or (current_holdings and sym in current_holdings):
                coins_list.append({
                    'Symbol': sym, 'MarketCap': 0, 'FDV': 0, 'Vol_24h': 0,
                    'FDV_MC_Ratio': 0, 'Vol_MC_Ratio': 0,
                    'TA_Score': ta_score, 'RSI_4H': rsi, 'Price': current_price
                })
    else:
        # ---- FORWARD TEST / LIVE MODE: Scan CMC for Low-Caps, then fetch their charts ----
        low_cap_symbols = []
        for coin in cmc_data:
            base_symbol = coin['symbol']
            quote = coin['quote']['USD']
            mc = quote.get('market_cap', 0)
            fdv = quote.get('fully_diluted_market_cap', 0)
            vol = quote.get('volume_24h', 0)
            
            fdv_mc_ratio = (fdv / mc) if mc > 0 else 0
            vol_mc_ratio = (vol / mc) if mc > 0 else 0
            
            # 💎 STRICT LOW-CAP FILTERS (10M - 300M) 💎
            if 10_000_000 <= mc <= 300_000_000 and fdv_mc_ratio < 2.5 and vol_mc_ratio > 0.05:
                if base_symbol in binance_symbols:
                    trading_pair = binance_symbols[base_symbol]
                    low_cap_symbols.append({
                        'Symbol': trading_pair, 'MarketCap': mc, 'FDV': fdv, 'Vol_24h': vol,
                        'FDV_MC_Ratio': fdv_mc_ratio, 'Vol_MC_Ratio': vol_mc_ratio
                    })
                    
        # Add current holdings to ensure we evaluate them for selling even if they left the low-cap range
        if current_holdings:
            for sym in current_holdings:
                if not any(c['Symbol'] == sym for c in low_cap_symbols):
                    low_cap_symbols.append({
                        'Symbol': sym, 'MarketCap': 0, 'FDV': 0, 'Vol_24h': 0,
                        'FDV_MC_Ratio': 0, 'Vol_MC_Ratio': 0
                    })
                    
        # Fetch Charts only for the filtered Low-Caps
        print(f"Found {len(low_cap_symbols)} Low-Cap candidates. Analyzing TA...")
        for coin_info in low_cap_symbols:
            sym = coin_info['Symbol']
            df = fetch_binance_4h_klines(sym)
            if df is None or df.empty:
                continue
                
            ta_score, rsi, current_price = analyze_4h_technicals(df)
            
            if (ta_score >= 80 and 40 <= rsi <= 65) or (current_holdings and sym in current_holdings):
                coins_list.append({
                    'Symbol': sym,
                    'MarketCap': coin_info['MarketCap'],
                    'FDV': coin_info['FDV'],
                    'Vol_24h': coin_info['Vol_24h'],
                    'FDV_MC_Ratio': coin_info['FDV_MC_Ratio'],
                    'Vol_MC_Ratio': coin_info['Vol_MC_Ratio'],
                    'TA_Score': ta_score,
                    'RSI_4H': rsi,
                    'Price': current_price
                })
            time.sleep(0.1)
            
    # --- EVALUATION ---
    df_coins = pd.DataFrame(coins_list)
    if df_coins.empty:
        for sym in current_holdings if current_holdings else []:
            symbol_reasons[sym] = {"decision_logic": "SELL: No coins met criteria.", "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0}
        symbol_reasons["MARKET"] = {"decision_logic": "HOLD CASH: No low-caps met the criteria."}
        return {}, symbol_reasons
        
    if is_backtest:
        df_coins['Fund_Score'] = 50
    else:
        df_coins['Fund_Score'] = ((2.5 - df_coins['FDV_MC_Ratio']) * 20 + (df_coins['Vol_MC_Ratio'] * 100).clip(upper=50))
        df_coins['Fund_Score'] = np.where(df_coins['MarketCap'] == 0, 50, df_coins['Fund_Score'])
        
    df_coins['Total_Gem_Score'] = (df_coins['Fund_Score'] + (df_coins['TA_Score'] * 0.5)).round(1)
    df_coins = df_coins.sort_values(by='Total_Gem_Score', ascending=False)
    
    top_gems = df_coins[df_coins['TA_Score'] >= 80].head(2) 
    
    weights = [0.7, 0.3] if len(top_gems) == 2 else [1.0] if len(top_gems) == 1 else []
    
    for i, row in enumerate(top_gems.itertuples()):
        sym = row.Symbol
        target_weight = weights[i]
        targets[sym] = target_weight
        symbol_reasons[sym] = {
            "decision_logic": f"BUY: Low-Cap (Fund: {row.Fund_Score:.1f}, TA: {row.TA_Score:.1f}). Allocate {target_weight*100:.0f}%",
            "calculation": f"Gem Score: {row.Total_Gem_Score}",
            "price": row.Price
        }
        
    for sym in current_holdings if current_holdings else []:
        if sym not in targets:
            symbol_reasons[sym] = {
                "decision_logic": "SELL: Fell out of Top Low-Cap rankings or lost TA momentum.",
                "price": df_coins[df_coins['Symbol'] == sym]['Price'].iloc[0] if sym in df_coins['Symbol'].values else (data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0)
            }
            
    return targets, symbol_reasons

if __name__ == "__main__":

    final_balance = run_backtest(get_target_allocations, initial_balance=10000.0, days=1825)
    print(f"5-Year Backtest Finished. Final Balance: ${final_balance:.2f}")
