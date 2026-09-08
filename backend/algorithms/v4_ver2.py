import pandas as pd
import numpy as np

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    symbol_reasons = {}
    if 'BTCUSDT' not in data_dict: return {}, {}
        
    btc_df = data_dict['BTCUSDT'].copy()
    if len(btc_df) < 200: return {}, {}
        
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    btc_current_price = btc_df['close'].iloc[-1]
    current_regime = 'BULL' if btc_current_price > btc_sma_200 else 'BEAR'
    
    if current_regime == 'BEAR':
        if current_holdings:
            for sym in current_holdings:
                symbol_reasons[sym] = {
                    "decision_logic": "SELL CRITERIA MET: Liquidating position because BTC Macro Regime is BEAR.",
                    "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
                }
        else:
            symbol_reasons["BTCUSDT"] = {"decision_logic": "HOLD CASH: Macro Regime is BEAR."}
        return {}, symbol_reasons
        
    scores = {}
    score_details = {}
    
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        # V4_ver2 Improvement: Faster momentum (10 periods instead of 20) to reduce lag
        ret_10 = (df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10]
        
        # V4_ver2 Improvement: EMA smoothed volume & capped anomaly to prevent outlier distortion
        vol_20_ema = df['volume'].ewm(span=20, adjust=False).mean().iloc[-1]
        vol_anomaly = df['volume'].iloc[-1] / vol_20_ema if vol_20_ema > 0 else 0
        vol_anomaly = min(vol_anomaly, 5.0) 
        
        score = ret_10 * vol_anomaly
        if score > 0:
            scores[sym] = score
            score_details[sym] = {"ret_10": ret_10, "vol_anomaly": vol_anomaly}
            
    if not scores:
        for sym in current_holdings if current_holdings else []:
            symbol_reasons[sym] = {"decision_logic": "SELL: Momentum score fell to 0.", "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0}
        return {}, symbol_reasons
        
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_2 = sorted_scores[:2]
    
    targets = {}
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(top_2):
        df = data_dict[sym]
        current_price = df['close'].iloc[-1]
        
        # V4_ver2 Improvement: ATR Trailing Stop & Scale-out logic
        high_14 = df['high'].rolling(14).max().iloc[-1]
        low_14 = df['low'].rolling(14).min().iloc[-1]
        atr_14 = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        
        trailing_stop_price = high_14 - (2.0 * atr_14)
        take_profit_target = low_14 + (3.0 * atr_14)
        
        if sym in (current_holdings or []) and current_price < trailing_stop_price:
            # Trailing stop hit, skip buying/holding
            continue
            
        volatility = df['close'].pct_change().rolling(window=20).std().iloc[-1]
        vol_penalty = 1.0 if volatility <= 0.05 else 0.5
            
        final_weight = weights[i] * vol_penalty
        
        # Partial Scale-out if price exceeded TP target
        if sym in (current_holdings or []) and current_price > take_profit_target:
            final_weight *= 0.5 # Scale out 50%
            
        targets[sym] = final_weight
        
        symbol_reasons[sym] = {
            "decision_logic": f"BUY/HOLD: Top 2 score. Allocating {final_weight*100:.0f}%.",
            "score": score,
            "price": current_price
        }
        
    for sym in current_holdings if current_holdings else []:
        if sym not in targets:
            symbol_reasons[sym] = {"decision_logic": "SELL: Dropped from Top 2 or Hit Trailing Stop.", "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0}
            
    return targets, symbol_reasons
