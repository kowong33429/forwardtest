import pandas as pd
import numpy as np

def get_target_allocations(data_dict, current_holdings=None):
    """
    V4.0 Aggressive Quant Live Scanner
    Returns a dictionary of target allocations, e.g., {'BTCUSDT': 0.7, 'ETHUSDT': 0.3}
    """
    if 'BTCUSDT' not in data_dict:
        return {}
        
    btc_df = data_dict['BTCUSDT'].copy()
    
    # 1. Macro Filter
    if len(btc_df) < 200:
        return {} # Not enough data
        
    btc_df['btc_sma_200'] = btc_df['close'].rolling(window=200).mean()
    current_regime = 'BULL' if btc_df['close'].iloc[-1] > btc_df['btc_sma_200'].iloc[-1] else 'BEAR'
    
    if current_regime == 'BEAR':
        return {} # 0% allocation (liquidate to USDT)
        
    # 2. Scoring
    scores = {}
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        # Momentum (20-period return)
        ret_20 = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
        
        # Volume Anomaly
        vol_20_sma = df['volume'].rolling(window=20).mean().iloc[-1]
        vol_anomaly = df['volume'].iloc[-1] / vol_20_sma if vol_20_sma > 0 else 0
        
        # Total Score
        score = ret_20 * vol_anomaly
        if score > 0:
            scores[sym] = score
            
    if not scores:
        return {}
        
    # Sort top 2
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_2 = sorted_scores[:2]
    
    targets = {}
    # Base weight 70/30
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(top_2):
        df = data_dict[sym]
        volatility = df['close'].pct_change().rolling(window=20).std().iloc[-1]
        vol_penalty = 1.0
        
        if volatility > 0.05:
            vol_penalty = 0.5
            
        targets[sym] = weights[i] * vol_penalty
        
    return targets
