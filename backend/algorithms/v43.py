import pandas as pd
import numpy as np
import os
import sys
from services import mt5_service
import datetime
import os
from dotenv import load_dotenv
from hmmlearn.hmm import GaussianHMM
from pykalman import KalmanFilter
import warnings
warnings.filterwarnings('ignore')

load_dotenv()

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(period).mean()
    return atr

def _get_target_allocations_internal(data_dict, symbol='XAUUSDc'):
    """
    V25: Dynamic Kelly (Probabilistic Confidence)
    Calculates Confidence (C) from 0.0 to 1.0 based on HMM Probability and Kalman Momentum.
    """
    if symbol not in data_dict or len(data_dict[symbol]) < 100:
        return None
        
    df = data_dict[symbol].copy()
    current_price = df['close'].iloc[-1]
    
    atr_series = calculate_atr(df, period=14)
    current_atr = atr_series.iloc[-1]
    
    # 1. Kalman Filter for Momentum
    kf_data = df['close'].iloc[-100:].values
    kf = KalmanFilter(transition_matrices=[1],
                      observation_matrices=[1],
                      initial_state_mean=kf_data[0],
                      initial_state_covariance=1,
                      observation_covariance=1,
                      transition_covariance=0.01)
    state_means, _ = kf.filter(kf_data)
    kalman_price = state_means[-1][0]
    kalman_price_prev = state_means[-2][0]
    kalman_momentum = kalman_price - kalman_price_prev
    
    # Normalize Momentum: Assume a move of 0.5 ATR per day is "Max Momentum" (1.0)
    m_norm = min(abs(kalman_momentum) / (0.5 * current_atr), 1.0)
    
    # 2. HMM Regime Detection & Probabilities
    returns = df['close'].pct_change().dropna()
    hist_vol = returns.rolling(window=10).std().dropna()
    
    min_len = min(len(returns), len(hist_vol))
    if min_len >= 100:
        hmm_features = np.column_stack([returns.iloc[-100:].values, hist_vol.iloc[-100:].values])
    else:
        hmm_features = None
        
    current_regime = "UNKNOWN"
    is_trending = False
    p_trend = 0.0
    
    if hmm_features is not None:
        try:
            model = GaussianHMM(n_components=2, covariance_type="full", n_iter=10, random_state=42)
            model.fit(hmm_features)
            hidden_states = model.predict(hmm_features)
            
            # Predict Probabilities
            probs = model.predict_proba(hmm_features)
            
            var_state_0 = np.var(hmm_features[hidden_states == 0, 0]) if np.sum(hidden_states == 0) > 0 else 0
            var_state_1 = np.var(hmm_features[hidden_states == 1, 0]) if np.sum(hidden_states == 1) > 0 else 0
            
            trending_state = 1 if var_state_1 > var_state_0 else 0
            
            current_state = hidden_states[-1]
            p_trend = probs[-1][trending_state] # Probability of being in trending state today
            
            if current_state == trending_state:
                current_regime = "TRENDING (High Vol)"
                is_trending = True
            else:
                current_regime = "RANGING (Low Vol)"
                is_trending = False
        except:
            pass 
            
    # 3. Confidence Score (C)
    confidence = (p_trend * 0.5) + (m_norm * 0.5)
    
    state = {
        "regime": current_regime,
        "is_trending": is_trending,
        "p_trend": p_trend,
        "kalman_momentum": kalman_momentum,
        "m_norm": m_norm,
        "confidence": confidence,
        "current_atr": current_atr,
        "current_price": current_price
    }
            
    return state

def get_1d(s):
    if isinstance(s, pd.DataFrame): return s.iloc[:, 0]
    return s

def calc_chop(df, n=14):
    high = get_1d(df['high'])
    low = get_1d(df['low'])
    close = get_1d(df['close'])
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.Series(np.maximum(tr1, np.maximum(tr2, tr3)))
    
    atr_sum = tr.rolling(n).sum()
    max_high = high.rolling(n).max()
    min_low = low.rolling(n).min()
    
    chop = 100 * np.log10(atr_sum / (max_high - min_low)) / np.log10(n)
    return chop

def get_ai_win_prob(history):
    if len(history) < 5: return 0.45 
    last_outcome = history[-1]
    streak_len = 1
    for i in range(len(history)-2, -1, -1):
        if history[i] == last_outcome: streak_len += 1
        else: break
            
    pattern_matches = 0
    pattern_wins = 0
    current_count = 0
    for i in range(len(history) - 1):
        if history[i] == last_outcome: current_count += 1
        else: current_count = 0
        if current_count == streak_len:
            if i + 1 < len(history):
                pattern_matches += 1
                if history[i+1] == 1: pattern_wins += 1
            current_count = 0 
            
    global_win_rate = sum(history) / len(history)
    if pattern_matches >= 2: return (pattern_wins + global_win_rate) / (pattern_matches + 1)
    else: return sum(history[-10:]) / len(history[-10:])

def connect_mt5():
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return mt5_service.connect_mt5()

def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0, live_execute=False, trade_history=None):
    """
    V43 The Whipsaw Killer (Daily)
    Support Future Trading / Exness Cent connection if live_execute=True
    """
    symbol_reasons = {}
    targets = {}
    
    symbol = "XAUUSDc" # Exness Cent Gold
    if symbol not in data_dict:
        # Fallback to standard if missing
        symbol = list(data_dict.keys())[0] if data_dict else "XAUUSDc"
        
    if symbol not in data_dict or len(data_dict[symbol]) < 130:
        return {}, symbol_reasons
        
    df = data_dict[symbol].copy()
    df['chop'] = calc_chop(df, 14)
    
    # Run core HMM/Kalman
    state = _get_target_allocations_internal({symbol: df}, symbol=symbol)
    
    chop_val = get_1d(df['chop']).iloc[-1]
    
    if chop_val > 61.8:
        symbol_reasons[symbol] = {
            "decision_logic": "HOLD CASH: Choppiness Index > 61.8 (Fractal Consolidation). Skipping trade to avoid whipsaw.",
            "formula": "CHOP(14) > 61.8",
            "calculation": f"CHOP = {chop_val:.2f}",
            "price": get_1d(df['close']).iloc[-1]
        }
        return {}, symbol_reasons
        
    if state and state['is_trending'] and state['confidence'] >= 0.3:
        if trade_history is not None:
            history = trade_history
        else:
            # Fallback only if trade_history wasn't provided at all (e.g. testing)
            history = [1, 0, 1, 1, 0, 1, 1] 
            
        ai_prob = get_ai_win_prob(history)
        
        raw_kelly = ai_prob - ((1 - ai_prob) / 2.5)
        blended_kelly = raw_kelly * state['confidence']
        if blended_kelly <= 0: blended_kelly = 0.01 
        blended_kelly = min(blended_kelly, 0.30) # V43 Max Kelly 30%
        
        direction = "LONG" if state['kalman_momentum'] > 0 else "SHORT"
        
        # We assign target weight. For futures, negative means SHORT.
        weight = blended_kelly if direction == "LONG" else -blended_kelly
        targets[symbol] = weight
        
        atr = state['current_atr']
        price = get_1d(df['close']).iloc[-1]
        
        sl_price = price - (1.0 * atr) if direction == "LONG" else price + (1.0 * atr)
        tp_price = price + (2.5 * atr) if direction == "LONG" else price - (2.5 * atr)
        
        symbol_reasons[symbol] = {
            "decision_logic": f"V43 SIGNAL MET: Entering {direction} at Kelly {blended_kelly*100:.1f}%. CHOP is {chop_val:.1f} (Safe).",
            "direction": direction,
            "sl": sl_price,
            "tp": tp_price,
            "price": price,
            "atr": atr,
            "state_confidence": state['confidence']
        }
        
        # If we want to execute live via MetaApi Cloud
        if live_execute:
        
        
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
            
            volume = 0.1 # Should calculate properly based on balance
            result = mt5_service.execute_trade(
                symbol=symbol,
                direction=direction,
                volume=volume,
                sl=sl_price,
                tp=tp_price,
                comment="V43 Whipsaw Killer"
            )
            
            if result.get("status") == "success":
                symbol_reasons[symbol]["ticket"] = result.get("ticket")
            else:
                print(f"Order failed: {result.get('message')}")
            
    else:
        symbol_reasons[symbol] = {
            "decision_logic": "HOLD CASH: Not trending or confidence < 30%.",
            "price": get_1d(df['close']).iloc[-1]
        }
        
    return targets, symbol_reasons
