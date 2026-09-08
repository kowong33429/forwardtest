import pandas as pd
import numpy as np
from scipy.stats import skew

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0, btc_symbol='BTCUSDT'):
    symbol_reasons = {}
    if current_holdings is None: current_holdings = []
    btc_key = next((k for k in [btc_symbol, 'BTCUSDT', 'BTC/USDT'] if k in data_dict), None)
    if not btc_key or len(data_dict[btc_key]) < 200: return {}, {}
        
    btc_df = data_dict[btc_key].copy()
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    btc_current_price = btc_df['close'].iloc[-1]
    current_regime = 'BULL' if btc_current_price > btc_sma_200 else 'BEAR'
    
    scores = {}
    score_details = {}
    btc_ret = btc_df['close'].pct_change()
    var_btc = btc_ret.rolling(50).var().iloc[-1]
    
    for sym, df in data_dict.items():
        if sym == btc_key or len(df) < 130: continue
            
        # V9_ver2 Improvement: Upper Wick Filter to prevent Volume Trap
        latest = df.iloc[-1]
        candle_range = latest['high'] - latest['low']
        upper_wick = latest['high'] - max(latest['open'], latest['close'])
        wick_ratio = upper_wick / candle_range if candle_range > 0 else 0
        if wick_ratio > 0.5 and sym not in current_holdings:
            continue # Skip buy if heavy rejection
            
        # V9_ver2 Improvement: Cap Volume anomaly
        vol_sma_20 = df['volume'].rolling(window=20).mean().iloc[-1]
        current_vol = latest['volume']
        vol_anomaly = current_vol / (vol_sma_20 + 1e-8) if vol_sma_20 > 0 else 1.0
        vol_anomaly = min(vol_anomaly, 5.0)
        
        # Adaptive Lookback for TEMA if vol_anomaly > 3
        lookback = 20 if vol_anomaly > 3.0 else 50
        
        alt_ret = df['close'].pct_change()
        cov = alt_ret.rolling(lookback).cov(btc_ret).iloc[-1]
        beta = cov / (var_btc + 1e-8) if not np.isnan(cov) else 1.0
        residual = alt_ret - (beta * btc_ret)
        
        ema1 = residual.ewm(span=21, adjust=False).mean()
        ema2 = ema1.ewm(span=21, adjust=False).mean()
        ema3 = ema2.ewm(span=21, adjust=False).mean()
        tema_res = (3 * ema1) - (3 * ema2) + ema3
        
        rm_score_series = tema_res.rolling(lookback).sum().fillna(0)
        rm_score = rm_score_series.iloc[-1]
        
        vel_series = rm_score_series.diff().fillna(0)
        accel_series = vel_series.diff().fillna(0)
        jerk_series = accel_series.diff().fillna(0)
        
        velocity = vel_series.iloc[-1]
        accel = accel_series.iloc[-1]
        jerk = jerk_series.iloc[-1]
        
        # Kinetic Scale Out: Decelerating peak
        scale_out = False
        if sym in current_holdings and velocity > 0 and accel < 0 and jerk < -0.005:
            scale_out = True
        
        decel_penalty = 0.2 if (accel < 0 and jerk < -0.01) else 1.0
        rm_score *= decel_penalty
        base_score = rm_score * vol_anomaly
        
        norm_vel = np.tanh(velocity * 100)
        kinetic_energy = 0.5 * vol_anomaly * (norm_vel ** 2)
        total_score = base_score * (1.0 + kinetic_energy)
        
        hysteresis = 1.15 if sym in current_holdings else 1.0
        total_score *= hysteresis
        
        # V9_ver2 Improvement: Chandelier Trailing Stop
        atr_14 = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        trailing_stop = df['high'].rolling(14).max().iloc[-1] - (1.5 * atr_14)
        if sym in current_holdings and latest['close'] < trailing_stop:
            total_score = -1 # Force sell
        
        if total_score > 0:
            scores[sym] = total_score
            score_details[sym] = {'scale_out': scale_out, 'kinetic_energy': kinetic_energy}
            
    if not scores:
        for sym in current_holdings: symbol_reasons[sym] = {"decision_logic": "LIQUIDATE: No positive momentum."}
        return {}, symbol_reasons
        
    score_vals = pd.Series(scores)
    if current_regime == 'BEAR':
        z_thresh = max(5.0, score_vals.mean() + (3 * score_vals.std())) if score_vals.std() > 0 else 5.0
        qualified_scores = score_vals[score_vals > z_thresh]
    else:
        qualified_scores = score_vals[score_vals > 0]
        
    if qualified_scores.empty:
        for sym in current_holdings: symbol_reasons[sym] = {"decision_logic": "LIQUIDATE: Failed Z-Score filter."}
        return {}, symbol_reasons
        
    top_2 = qualified_scores.nlargest(2)
    targets = {}
    for rank, (sym, score) in enumerate(top_2.items()):
        df = data_dict[sym]
        returns = df['close'].pct_change().dropna()
        base_w = score / top_2.sum() if top_2.sum() > 0 else 0.5
        
        vol = returns.rolling(window=20).std().iloc[-1]
        vol = 0.05 if np.isnan(vol) or vol == 0 else vol
        vol_scalar = min(1.0, 0.05 / vol)
        
        skew_val = skew(returns.iloc[-20:]) if len(returns) >= 20 else 0.0
        skew_penalty = 0.5 if skew_val < -1.0 else (0.8 if skew_val < -0.5 else 1.0)
            
        final_weight = base_w * vol_scalar * skew_penalty
        
        # Apply Kinetic Scale Out
        if score_details[sym]['scale_out']:
            final_weight *= 0.5
            
        targets[sym] = final_weight
        symbol_reasons[sym] = {
            "decision_logic": f"BUY / HOLD (Rank {rank+1}): Target Allocation {final_weight*100:.1f}%.",
            "price": df['close'].iloc[-1]
        }
        
    for sym in current_holdings:
        if sym not in targets:
            symbol_reasons[sym] = {"decision_logic": "SELL (ROTATION or SL).", "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0}
            
    return targets, symbol_reasons
