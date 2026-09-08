import pandas as pd
import numpy as np

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    symbol_reasons = {}
    targets = {}
    
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
        ema_20 = df['close'].ewm(span=20).mean().iloc[-1]
        vol_ema_20 = df['volume'].ewm(span=20).mean().iloc[-1]
        
        is_bullish = ema_9 > ema_20
        # V5_ver2 Improvement: Cap Vol Anomaly & smooth it
        vol_anomaly = latest['volume'] / (vol_ema_20 + 1e-8)
        vol_anomaly = min(vol_anomaly, 3.0)
        is_vol_anomaly = vol_anomaly > 1.5
        
        ta_score = 0
        if is_bullish: ta_score += 20
        if is_vol_anomaly: ta_score += 40
        if latest['close'] > prev['high']: ta_score += 40
        
        # V5_ver2 Improvement: Anti-FOMO & Wick Filters
        candle_range = latest['high'] - latest['low']
        upper_wick = latest['high'] - max(latest['open'], latest['close'])
        wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
        
        # Penalty if chasing too far above EMA9
        dist_ema9 = (latest['close'] - ema_9) / ema_9
        if dist_ema9 > 0.05: ta_score -= 30
        if wick_ratio > 0.4: ta_score -= 30
        
        # V5_ver2 Improvement: Volume Exhaustion Exit
        vol_decay = latest['volume'] / (prev['volume'] + 1e-8)
        if sym in (current_holdings or []) and vol_decay < 0.3:
            ta_score = 0 # Force exit
            
        # V5_ver2 Improvement: ATR Trailing Stop
        atr_14 = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        trailing_stop = df['high'].rolling(14).max().iloc[-1] - (1.5 * atr_14)
        if sym in (current_holdings or []) and latest['close'] < trailing_stop:
            ta_score = 0
            
        if ta_score >= 80 or (sym in (current_holdings or []) and ta_score > 40):
            targets[sym] = 0.5 # Allocate 50% for top picks (simplified low-cap logic for paper test)
            symbol_reasons[sym] = {"decision_logic": f"BUY/HOLD. TA Score: {ta_score}", "price": latest['close']}
            
    # Normalize targets if exceeding 1.0
    total_w = sum(targets.values())
    if total_w > 1.0:
        for k in targets: targets[k] /= total_w
        
    for sym in current_holdings or []:
        if sym not in targets:
            symbol_reasons[sym] = {"decision_logic": "SELL: Dropped below TA threshold or hit SL.", "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0}
            
    return targets, symbol_reasons
