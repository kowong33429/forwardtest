import pandas as pd
import numpy as np
from scipy.stats import skew

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    """
    V5.1 God Mode Quant Live Scanner
    (200 SMA Macro, Hysteresis Band, Tail-Risk Parity)
    """
    symbol_reasons = {}
    if current_holdings is None:
        current_holdings = []
        
    if 'BTCUSDT' not in data_dict:
        return {}, {}
        
    btc_df = data_dict['BTCUSDT'].copy()
    
    # 1. Macro Filter (200 SMA)
    if len(btc_df) < 200:
        return {}, {}
        
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    btc_current_price = btc_df['close'].iloc[-1]
    current_regime = 'BULL' if btc_current_price > btc_sma_200 else 'BEAR'
    
    if current_regime == 'BEAR':
        for sym in current_holdings:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Liquidating position because BTC Macro Regime is BEAR.",
                "formula": "BTC Price > 200 SMA = BULL",
                "calculation": f"{btc_current_price:.2f} > {btc_sma_200:.2f} = False",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    # 2. Scoring with Hysteresis
    scores = {}
    score_details = {}
    for sym, df in data_dict.items():
        if len(df) < 20: continue
            
        ret_20 = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
        vol_20_sma = df['volume'].rolling(window=20).mean().iloc[-1]
        vol_anomaly = df['volume'].iloc[-1] / vol_20_sma if vol_20_sma > 0 else 0
        
        score = ret_20 * vol_anomaly
        if score > 0:
            hysteresis_boost = 1.0
            # Hysteresis Band: Give 15% boost if already holding
            if sym in current_holdings:
                hysteresis_boost = 1.15
                score *= 1.15
            scores[sym] = score
            score_details[sym] = {
                "ret_20": ret_20,
                "vol_anomaly": vol_anomaly,
                "hysteresis_boost": hysteresis_boost
            }
            
    if not scores:
        for sym in current_holdings:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Target allocation is 0% because the momentum score fell to 0 or below.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_2 = sorted_scores[:2]
    
    targets = {}
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(top_2):
        df = data_dict[sym]
        current_price = df['close'].iloc[-1]
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
            
        final_weight = weights[i] * vol_penalty * skew_penalty
        targets[sym] = final_weight
        
        sl_pct = max(0.05, volatility * 2) if not np.isnan(volatility) else 0.05
        sl_price = current_price * (1 - sl_pct)
        est_loss_usd = (total_value * final_weight) * sl_pct
        
        s_det = score_details[sym]
        formula_str = "Score = Momentum(20d) * Volume_Anomaly"
        calc_str = f"{s_det['ret_20']:.4f} * {s_det['vol_anomaly']:.2f}"
        if s_det['hysteresis_boost'] > 1.0:
            formula_str += " * Hysteresis_Boost"
            calc_str += f" * {s_det['hysteresis_boost']:.2f}"
            
        decision_logic = f"BUY CRITERIA MET: Coin is in Top 2 highest scores during a BULL macro regime. Allocating {final_weight*100:.0f}% portfolio."
        if vol_penalty < 1.0:
            decision_logic += f" Applied Volatility Penalty ({vol_penalty}x)."
        if skew_penalty < 1.0:
            decision_logic += f" Applied Skew Penalty ({skew_penalty}x)."
            
        symbol_reasons[sym] = {
            "decision_logic": decision_logic,
            "formula": formula_str,
            "calculation": f"{score:.4f} = {calc_str}",
            "price": current_price,
            "sma_200": btc_sma_200,
            "stop_loss_price": sl_price,
            "est_loss_usd": est_loss_usd
        }
        
    for sym in current_holdings:
        if sym not in targets:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Coin fell out of the Top 2 momentum rankings. Liquidating position.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
            
    return targets, symbol_reasons
