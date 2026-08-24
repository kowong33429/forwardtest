import pandas as pd
import numpy as np
from scipy.stats import skew

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0, btc_symbol='BTCUSDT'):
    """
    V9 Kinetic God Engine (Production Live Quant Scanner)
    Integrates:
    1. Physics Kinetic Energy: E_k = 0.5 * Mass(Vol_Anomaly) * Velocity(Alpha)^2
    2. Calculus: 3rd Derivative Deceleration Penalty (Jerk / OptStop)
    3. Statistics: Dynamic Z-Score Extreme Alpha Filtering
    4. Linear Algebra: Conviction Sizing with Volatility & Tail-Risk Parity
    5. Execution Optimization: Fast Stop Loss (-10%) & Take Profit (+30%) Re-deployment
    """
    symbol_reasons = {}
    if current_holdings is None:
        current_holdings = []
        
    btc_key = None
    for k in [btc_symbol, 'BTCUSDT', 'BTC/USDT']:
        if k in data_dict:
            btc_key = k
            break
            
    if not btc_key or len(data_dict[btc_key]) < 200:
        return {}, {}
        
    btc_df = data_dict[btc_key].copy()
    
    # 1. Macro Regime Filter (BTC 200 SMA on 4H)
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    btc_current_price = btc_df['close'].iloc[-1]
    current_regime = 'BULL' if btc_current_price > btc_sma_200 else 'BEAR'
    
    # 2. Altcoin Kinetic Energy Scoring
    scores = {}
    score_details = {}
    
    btc_ret = btc_df['close'].pct_change()
    var_btc = btc_ret.rolling(50).var().iloc[-1]
    
    for sym, df in data_dict.items():
        if sym == btc_key or len(df) < 130:
            continue
            
        alt_ret = df['close'].pct_change()
        cov = alt_ret.rolling(50).cov(btc_ret).iloc[-1]
        beta = cov / (var_btc + 1e-8) if not np.isnan(cov) else 1.0
        
        residual = alt_ret - (beta * btc_ret)
        
        # Fast TEMA 21
        ema1 = residual.ewm(span=21, adjust=False).mean()
        ema2 = ema1.ewm(span=21, adjust=False).mean()
        ema3 = ema2.ewm(span=21, adjust=False).mean()
        tema_res = (3 * ema1) - (3 * ema2) + ema3
        
        rm_score_series = tema_res.rolling(50).sum().fillna(0)
        rm_score = rm_score_series.iloc[-1]
        
        vel_series = rm_score_series.diff().fillna(0)
        accel_series = vel_series.diff().fillna(0)
        jerk_series = accel_series.diff().fillna(0)
        
        velocity = vel_series.iloc[-1]
        accel = accel_series.iloc[-1]
        jerk = jerk_series.iloc[-1]
        
        # MTFA Slow TEMA 126
        slow_ema1 = residual.ewm(span=126, adjust=False).mean()
        slow_ema2 = slow_ema1.ewm(span=126, adjust=False).mean()
        slow_ema3 = slow_ema2.ewm(span=126, adjust=False).mean()
        slow_tema = (3 * slow_ema1) - (3 * slow_ema2) + slow_ema3
        slow_accel = slow_tema.diff().diff().iloc[-1]
        
        accel_factor = 1 + (np.tanh(accel * 1000) * 0.5)
        resonance = accel_factor if slow_accel > 0 else 0.5
        
        # Calculus OptStop
        decel_penalty = 0.2 if (accel < 0 and jerk < -0.01) else 1.0
        
        final_mult = resonance * decel_penalty
        if rm_score > 0:
            rm_score *= final_mult
            
        # Volume Anomaly (Mass m)
        vol_sma_20 = df['volume'].rolling(window=20).mean().iloc[-1]
        current_vol = df['volume'].iloc[-1]
        vol_anomaly = current_vol / (vol_sma_20 + 1e-8) if vol_sma_20 > 0 else 1.0
        
        base_score = rm_score * vol_anomaly
        
        # Quant Physics Kinetic Energy: Ek = 0.5 * m * v^2
        norm_vel = np.tanh(velocity * 100)
        kinetic_energy = 0.5 * vol_anomaly * (norm_vel ** 2)
        total_score = base_score * (1.0 + kinetic_energy)
        
        # Hysteresis boost (+15% for existing positions)
        hysteresis = 1.15 if sym in current_holdings else 1.0
        total_score *= hysteresis
        
        if total_score > 0:
            scores[sym] = total_score
            score_details[sym] = {
                'rm_score': rm_score,
                'vol_anomaly': vol_anomaly,
                'velocity': velocity,
                'kinetic_energy': kinetic_energy,
                'hysteresis': hysteresis
            }
            
    if not scores:
        for sym in current_holdings:
            symbol_reasons[sym] = {
                "decision_logic": "LIQUIDATE: No coin qualified with positive momentum.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    # 3. Dynamic Z-Score Regime Filter
    score_vals = pd.Series(scores)
    if current_regime == 'BEAR':
        mean_s = score_vals.mean()
        std_s = score_vals.std()
        z_thresh = max(5.0, mean_s + (3 * std_s)) if std_s > 0 else 5.0
        qualified_scores = score_vals[score_vals > z_thresh]
    else:
        qualified_scores = score_vals[score_vals > 0]
        
    if qualified_scores.empty:
        for sym in current_holdings:
            symbol_reasons[sym] = {
                "decision_logic": f"LIQUIDATE: In {current_regime} market, no coin passed Dynamic Z-Score filter (Threshold={z_thresh:.2f}).",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    top_2 = qualified_scores.nlargest(2)
    total_top_score = top_2.sum()
    
    targets = {}
    for rank, (sym, score) in enumerate(top_2.items()):
        df = data_dict[sym]
        current_price = df['close'].iloc[-1]
        returns = df['close'].pct_change().dropna()
        
        base_w = score / total_top_score if total_top_score > 0 else 0.5
        
        vol = returns.rolling(window=20).std().iloc[-1]
        if np.isnan(vol) or vol == 0: vol = 0.05
        vol_scalar = min(1.0, 0.05 / vol)
        
        skew_val = skew(returns.iloc[-20:]) if len(returns) >= 20 else 0.0
        skew_penalty = 1.0
        if not np.isnan(skew_val):
            if skew_val < -1.0: skew_penalty = 0.5
            elif skew_val < -0.5: skew_penalty = 0.8
            
        final_weight = base_w * vol_scalar * skew_penalty
        targets[sym] = final_weight
        
        sl_price = current_price * 0.90 # SL -10%
        tp_price = current_price * 1.30 # TP +30%
        est_invest = total_value * final_weight
        
        s_det = score_details[sym]
        symbol_reasons[sym] = {
            "decision_logic": f"BUY / HOLD (Rank {rank+1}): Score={score:.2f} | Kinetic Energy Boost=+{s_det['kinetic_energy']*100:.1f}%. Target Allocation: {final_weight*100:.1f}%.",
            "formula": "V9 Kinetic God: Ek = 0.5 * Vol_Anomaly * Velocity^2",
            "price": current_price,
            "regime": current_regime,
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "allocated_usd": est_invest
        }
        
    for sym in current_holdings:
        if sym not in targets:
            symbol_reasons[sym] = {
                "decision_logic": "SELL (ROTATION): Coin dropped out of Top 2 momentum rankings.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
            
    return targets, symbol_reasons
