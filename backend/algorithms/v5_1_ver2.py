import pandas as pd
import numpy as np

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    symbol_reasons = {}
    if 'BTCUSDT' not in data_dict: return {}, {}
    btc_df = data_dict['BTCUSDT'].copy()
    if len(btc_df) < 200: return {}, {}
        
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    if btc_df['close'].iloc[-1] <= btc_sma_200:
        for sym in current_holdings or []:
            symbol_reasons[sym] = {"decision_logic": "SELL: BEAR Regime"}
        return {}, symbol_reasons

    scores = {}
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        ret_20 = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
        # V5_1_ver2: Median Volume
        vol_median = df['volume'].rolling(20).median().iloc[-1]
        vol_anomaly = df['volume'].iloc[-1] / (vol_median + 1e-8)
        vol_anomaly = min(vol_anomaly, 3.0)
        
        # V5_1_ver2: Anti-FOMO block
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        std_20 = df['close'].rolling(20).std().iloc[-1]
        if df['close'].iloc[-1] > sma_20 + (2.5 * std_20) and sym not in (current_holdings or []):
            continue
            
        score = ret_20 * vol_anomaly
        if score > 0:
            if sym in (current_holdings or []): score *= 1.15
            scores[sym] = score
            
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
    targets = {}
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(sorted_scores):
        df = data_dict[sym]
        current_price = df['close'].iloc[-1]
        
        volatility = df['close'].pct_change().rolling(20).std().iloc[-1]
        vol_penalty = 1.0 if volatility <= 0.05 else 0.5
        
        final_w = weights[i] * vol_penalty
        
        # Scale out
        atr_14 = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        lowest_10 = df['low'].rolling(10).min().iloc[-1]
        if sym in (current_holdings or []) and current_price > lowest_10 + (2.5 * atr_14):
            final_w *= 0.5
            
        targets[sym] = final_w
        symbol_reasons[sym] = {"decision_logic": f"BUY/HOLD. Alloc: {final_w*100}%", "price": current_price}
        
    for sym in current_holdings or []:
        if sym not in targets:
            symbol_reasons[sym] = {"decision_logic": "SELL"}
            
    return targets, symbol_reasons
