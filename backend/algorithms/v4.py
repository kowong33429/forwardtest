import pandas as pd
import numpy as np

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    """
    V4.0 Aggressive Quant Live Scanner
    Returns a dictionary of target allocations, e.g., {'BTCUSDT': 0.7, 'ETHUSDT': 0.3}
    and a dict of symbol reasons.
    """
    symbol_reasons = {}
    if 'BTCUSDT' not in data_dict:
        return {}, {}
        
    btc_df = data_dict['BTCUSDT'].copy()
    
    # 1. Macro Filter
    if len(btc_df) < 200:
        return {}, {}
        
    btc_sma_200 = btc_df['close'].rolling(window=200).mean().iloc[-1]
    btc_current_price = btc_df['close'].iloc[-1]
    current_regime = 'BULL' if btc_current_price > btc_sma_200 else 'BEAR'
    
    if current_regime == 'BEAR':
        for sym in current_holdings if current_holdings else []:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Liquidating position because BTC Macro Regime is BEAR.",
                "formula": "BTC Price > 200 SMA = BULL",
                "calculation": f"{btc_current_price:.2f} > {btc_sma_200:.2f} = False",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    scores = {}
    score_details = {}
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
            score_details[sym] = {
                "ret_20": ret_20,
                "vol_anomaly": vol_anomaly
            }
            
    if not scores:
        for sym in current_holdings if current_holdings else []:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Target allocation is 0% because the momentum score fell to 0 or below.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
        return {}, symbol_reasons
        
    # Sort top 2
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_2 = sorted_scores[:2]
    
    targets = {}
    # Base weight 70/30
    weights = [0.7, 0.3]
    
    for i, (sym, score) in enumerate(top_2):
        df = data_dict[sym]
        current_price = df['close'].iloc[-1]
        volatility = df['close'].pct_change().rolling(window=20).std().iloc[-1]
        vol_penalty = 1.0
        
        if volatility > 0.05:
            vol_penalty = 0.5
            
        final_weight = weights[i] * vol_penalty
        targets[sym] = final_weight
        
        # Stop loss based on volatility (e.g. 2x std dev or min 5%)
        sl_pct = max(0.05, volatility * 2) if not np.isnan(volatility) else 0.05
        sl_price = current_price * (1 - sl_pct)
        est_loss_usd = (total_value * final_weight) * sl_pct
        
        s_det = score_details[sym]
        symbol_reasons[sym] = {
            "decision_logic": f"BUY CRITERIA MET: Coin is in Top 2 highest positive scores during a BULL macro regime. Allocating {final_weight*100:.0f}% portfolio.",
            "formula": "Score = Momentum(20d) * Volume_Anomaly",
            "calculation": f"{score:.4f} = {s_det['ret_20']:.4f} * {s_det['vol_anomaly']:.2f}",
            "price": current_price,
            "sma_200": btc_sma_200,
            "stop_loss_price": sl_price,
            "est_loss_usd": est_loss_usd
        }
        
    # Also log sells for anything in current_holdings not in targets
    for sym in current_holdings if current_holdings else []:
        if sym not in targets:
            symbol_reasons[sym] = {
                "decision_logic": "SELL CRITERIA MET: Coin fell out of the Top 2 momentum rankings. Liquidating position.",
                "price": data_dict[sym]['close'].iloc[-1] if sym in data_dict else 0
            }
            
    return targets, symbol_reasons
