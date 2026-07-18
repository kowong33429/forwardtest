import pandas as pd
import numpy as np
from scipy.stats import skew

def get_target_allocations(data_dict, current_holdings=None):
    """
    V5.1 God Mode Quant Live Scanner
    (200 SMA Macro, Hysteresis Band, Tail-Risk Parity)
    """
    if current_holdings is None:
        current_holdings = []
        
    if 'BTCUSDT' not in data_dict:
        return {}
        
    btc_df = data_dict['BTCUSDT'].copy()
    
    # 1. Macro Filter (200 SMA)
    if len(btc_df) < 200:
        return {}
        
    btc_df['btc_sma_200'] = btc_df['close'].rolling(window=200).mean()
    current_regime = 'BULL' if btc_df['close'].iloc[-1] > btc_df['btc_sma_200'].iloc[-1] else 'BEAR'
    
    if current_regime == 'BEAR':
        return {}
        
    # 2. Scoring with Hysteresis
    scores = {}
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        ret_20 = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
        vol_20_sma = df['volume'].rolling(window=20).mean().iloc[-1]
        vol_anomaly = df['volume'].iloc[-1] / vol_20_sma if vol_20_sma > 0 else 0
        
        score = ret_20 * vol_anomaly
        if score > 0:
            # Hysteresis Band: Give 15% boost if already holding
            if sym in current_holdings:
                score *= 1.15
            scores[sym] = score
            
    if not scores:
        return {}
        
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_2 = sorted_scores[:2]
    
    targets = {}
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(top_2):
        df = data_dict[sym]
        returns = df['close'].pct_change().dropna()
        
        # Volatility penalty
        volatility = returns.rolling(window=20).std().iloc[-1]
        vol_penalty = 1.0
        if volatility > 0.05:
            vol_penalty = 0.5
            
        # Tail-Risk Parity (Skewness penalty)
        skew_val = 0
        if len(returns) >= 20:
            skew_val = skew(returns.iloc[-20:])
            
        skew_penalty = 1.0
        if skew_val < -1.0:
            skew_penalty = 0.5
        elif skew_val < -0.5:
            skew_penalty = 0.8
            
        targets[sym] = weights[i] * vol_penalty * skew_penalty
        
    return targets
