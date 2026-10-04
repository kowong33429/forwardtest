"""
ml_predict_entry.py — "ML Predict Entry Point" (forwardtest algorithm)

Ports the pooled XGBoost entry model trained in the backtest project
(.../personal/backtest) into the forwardtest `get_target_allocations()`
interface. For every scanned coin it reproduces the EXACT training feature
pipeline (strict n-1 shift, scale-free TA + publication-lagged macro +
Fear&Greed), scores P(a +100%/30d rally STARTS on the latest closed bar), and
allocates to the highest-probability coins whose probability clears the model's
own live threshold (meta['threshold']).

WHY THIS IS A FAITHFUL PORT (and where it is honestly NOT)
---------------------------------------------------------
  * Features are built by the ORIGINAL `FeatureEngineer` and the ORIGINAL
    macro/F&G helpers, imported from the backtest repo — not re-implemented —
    so live features cannot silently drift from training.
  * NO LOOK-AHEAD: FeatureEngineer applies .shift(1) internally; we only ever
    read the LAST closed bar's feature row. (AGENTS.md Rule #1.)
  * HISTORY: the engine hands us only ~250 bars, but several features use
    windows up to 2190 bars (1Y). We therefore RE-FETCH extended history per
    coin (paginated) so the long features are real, not zero-filled.
  * FIDELITY GAPS we state out loud (and record in each coin's reason):
      - Funding_Rate is not on spot klines -> zero-filled (1 of 108 features).
      - Macro + F&G need yfinance/FRED; if those are unavailable the macro block
        zero-fills (same behaviour as predict_entry.py --no-macro). The model
        was trained WITH them, so a zero-fill is a real degradation — hence we
        surface `macro_ok` in the SYSTEM reason.

The decision logic lives entirely in the model; unlike v4 there is no separate
hand-coded BTC regime gate — the model is the filter.

Config via environment (all optional):
  BACKTEST_DIR          repo root to import original code + model from
                        (default: /Users/nattanan/personal/backtest)
  ML_ENTRY_MODEL_DIR    model dir (default: $BACKTEST_DIR/data/model)
  ML_ENTRY_THRESHOLD    override meta threshold (float)
  ML_ENTRY_MAX_POS      max simultaneous positions (default 5)
  ML_ENTRY_MAX_WEIGHT   per-coin weight cap (default 0.40)
  ML_ENTRY_HISTORY_BARS extended bars to fetch per coin (default 2300)
  ML_ENTRY_USE_MACRO    "1"/"0" fetch macro+F&G (default "1")
"""
import os
import sys
import json
import time
import logging
import contextlib
from io import StringIO

import numpy as np
import pandas as pd

logger = logging.getLogger("MLPredictEntry")

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
# VENDORED assets live next to this file so a deploy of ONLY forwardtest is
# self-contained (model + meta + universe + the original features.py /
# entry_finder.py code). We prefer the vendored copy; BACKTEST_DIR is only a
# fallback for local dev (fresh model straight out of the backtest repo).
# To refresh after retraining: re-copy entry_xgb.json, entry_model_meta.json,
# universe.json (and features.py/entry_finder.py if they changed) into
# algorithms/ml_entry_model/.
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_entry_model")
BACKTEST_DIR = os.environ.get("BACKTEST_DIR", "/Users/nattanan/personal/backtest")


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[-1]  # last as the "intended" default even if missing


# Code dir to import the ORIGINAL FeatureEngineer / entry_finder from.
CORE_DIR = _first_existing(
    _ASSET_DIR if os.path.exists(os.path.join(_ASSET_DIR, "features.py")) else None,
    os.path.join(BACKTEST_DIR, "core"),
)
# Model + meta dir.
MODEL_DIR = os.environ.get("ML_ENTRY_MODEL_DIR") or _first_existing(
    _ASSET_DIR if os.path.exists(os.path.join(_ASSET_DIR, "entry_xgb.json")) else None,
    os.path.join(BACKTEST_DIR, "data", "model"),
)
MAX_POSITIONS = int(os.environ.get("ML_ENTRY_MAX_POS", "5"))
MAX_WEIGHT = float(os.environ.get("ML_ENTRY_MAX_WEIGHT", "0.40"))
HISTORY_BARS = int(os.environ.get("ML_ENTRY_HISTORY_BARS", "2300"))
USE_MACRO = os.environ.get("ML_ENTRY_USE_MACRO", "1") == "1"
MIN_HISTORY = 300            # too few bars -> features unstable, skip the coin
_MACRO_TTL_SEC = 6 * 3600    # refetch macro/F&G at most every 6h
_HIST_TTL_SEC = int(os.environ.get("ML_ENTRY_HIST_TTL", "3600"))  # cache klines ~1h


def _load_universe():
    """
    The scan universe for THIS algo = the SAME basket the model was trained on
    (dataset.py's --basket), NOT the engine's top-volume list. Large caps score
    low on a +100%/30d model, so scanning top-volume rarely fires; the backtest
    basket is the honest, matched universe.

    Order: ML_ENTRY_SYMBOLS (CSV) > ML_ENTRY_UNIVERSE (json path) >
    $BACKTEST_DIR/data/scan_results/scanned_priority_coins.json. Returns a list,
    or None to fall back to scanning whatever the engine passed in data_dict.
    """
    env_syms = os.environ.get("ML_ENTRY_SYMBOLS")
    if env_syms:
        return [s.strip().upper() for s in env_syms.split(",") if s.strip()]
    path = os.environ.get("ML_ENTRY_UNIVERSE") or _first_existing(
        os.path.join(_ASSET_DIR, "universe.json"),  # vendored (deploy)
        os.path.join(BACKTEST_DIR, "data", "scan_results", "scanned_priority_coins.json"),
    )
    try:
        with open(path) as f:
            syms = json.load(f)
        return [str(s).upper() for s in syms]
    except Exception as e:
        logger.warning(f"universe file unavailable ({e}); scanning data_dict as-is")
        return None


# Module-level: the engine reads getattr(module, "UNIVERSE") to pre-fetch prices
# for these symbols so it can score AND execute them. Only this algo defines it.
UNIVERSE = _load_universe()

# Lazy singletons (populated on first call, reused across ticks).
_MODEL = None
_FEATURE_LIST = None
_THRESHOLD = None
_FEATURE_ENGINEER = None
_SELECT_SCALE_FREE = None
_ENTRY_FINDER = None         # module handle, or False if unavailable
_MACRO_CACHE = {"ts": 0.0, "table": None, "fg": None, "ok": False}
_HIST_CACHE = {}             # sym -> (fetched_ts, df); avoids refetching within a 4H bar


# --------------------------------------------------------------------------- #
# Lazy loading of the original backtest code + the trained model
# --------------------------------------------------------------------------- #
def _load_model():
    """Import the original FeatureEngineer + load the trained XGBoost model once."""
    global _MODEL, _FEATURE_LIST, _THRESHOLD, _FEATURE_ENGINEER, _SELECT_SCALE_FREE
    if _MODEL is not None:
        return

    if CORE_DIR not in sys.path:
        sys.path.insert(0, CORE_DIR)

    # Original feature pipeline (needs pandas_ta — faithful, not re-implemented).
    from features import FeatureEngineer  # noqa: E402
    _FEATURE_ENGINEER = FeatureEngineer
    _SELECT_SCALE_FREE = _make_scale_free_selector()

    meta_path = os.path.join(MODEL_DIR, "entry_model_meta.json")
    model_path = os.path.join(MODEL_DIR, "entry_xgb.json")
    with open(meta_path) as f:
        meta = json.load(f)
    _FEATURE_LIST = meta["features"]
    env_thr = os.environ.get("ML_ENTRY_THRESHOLD")
    _THRESHOLD = float(env_thr) if env_thr else float(meta.get("threshold", 0.6))

    from xgboost import XGBClassifier  # noqa: E402 (requires scikit-learn too)
    model = XGBClassifier()
    model.load_model(model_path)
    _MODEL = model
    logger.info(
        f"Loaded entry model: {len(_FEATURE_LIST)} features, threshold {_THRESHOLD:.2f}, "
        f"OOS PR-AUC {meta.get('pr_auc_xgb', float('nan')):.3f}"
    )


def _make_scale_free_selector():
    """
    Replicate dataset.select_scale_free WITHOUT importing dataset.py (that pulls
    the labeler + entry_finder chain). Kept byte-identical to the original rule.
    """
    SCALE_FREE_PREFIXES = (
        "RSI_", "ADX_", "BB_Width_", "Dist_SMA_", "Return_", "Dist_Low_",
        "Dist_High_", "Volume_Surge_", "Pos_In_", "Dist_VWAP_",
    )
    SCALE_FREE_EXACT = {"SMA_Cross", "ATR_Ratio"}

    def select(cols):
        keep = []
        for c in cols:
            if c in SCALE_FREE_EXACT or c.startswith(SCALE_FREE_PREFIXES):
                if c.startswith("MACD"):
                    continue
                keep.append(c)
        return keep

    return select


def _get_entry_finder():
    """Import entry_finder lazily; return module or False if unavailable."""
    global _ENTRY_FINDER
    if _ENTRY_FINDER is not None:
        return _ENTRY_FINDER
    if CORE_DIR not in sys.path:
        sys.path.insert(0, CORE_DIR)
    try:
        import entry_finder  # noqa: E402
        _ENTRY_FINDER = entry_finder
    except Exception as e:  # pragma: no cover - optional macro path
        logger.warning(f"entry_finder unavailable, macro/F&G will be zero-filled: {e}")
        _ENTRY_FINDER = False
    return _ENTRY_FINDER


# --------------------------------------------------------------------------- #
# Extended history (the engine only passes ~250 bars; long features need ~2190)
# --------------------------------------------------------------------------- #
def _binance_request():
    """Import the project's geo-block-aware Binance caller from data_fetcher."""
    try:
        from algorithms.data_fetcher import safe_binance_request
    except Exception:
        from data_fetcher import safe_binance_request
    return safe_binance_request


def _fetch_history(symbol, bars=HISTORY_BARS, interval="4h"):
    """
    Fetch up to `bars` recent 4H candles (paginated; Binance caps limit at 1000),
    returned oldest->newest as a DataFrame with Date + Capitalized OHLCV so the
    original FeatureEngineer can consume it unchanged. Cached per symbol for
    _HIST_TTL_SEC so repeated ticks inside one 4H bar don't refetch ~2300 bars.
    """
    cached = _HIST_CACHE.get(symbol)
    if cached and (time.time() - cached[0]) < _HIST_TTL_SEC and len(cached[1]) >= bars:
        return cached[1]

    req = _binance_request()
    collected = []
    end_param = ""
    guard = 0
    while len(collected) < bars and guard < 10:
        guard += 1
        ep = f"/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000{end_param}"
        chunk = req(ep)
        if not chunk or not isinstance(chunk, list):
            break
        collected = chunk + collected          # prepend older history
        earliest_open = chunk[0][0]
        end_param = f"&endTime={earliest_open - 1}"
        if len(chunk) < 1000:                   # reached the listing's start
            break

    if not collected:
        return None
    collected = collected[-bars:]
    df = pd.DataFrame(collected, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbb", "tbq", "ignore",
    ])
    df["Date"] = pd.to_datetime(df["close_time"], unit="ms")
    for src, dst in [("open", "Open"), ("high", "High"), ("low", "Low"),
                     ("close", "Close"), ("volume", "Volume")]:
        df[dst] = df[src].astype(float)
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df = df.drop_duplicates(subset="Date").sort_values("Date").reset_index(drop=True)
    _HIST_CACHE[symbol] = (time.time(), df)
    return df


# --------------------------------------------------------------------------- #
# Shared macro + Fear&Greed (fetched once per tick, cached with a TTL)
# --------------------------------------------------------------------------- #
def _refresh_macro():
    """Populate _MACRO_CACHE with a macro table + F&G series (best-effort)."""
    now = time.time()
    if _MACRO_CACHE["table"] is not None and (now - _MACRO_CACHE["ts"]) < _MACRO_TTL_SEC:
        return
    ef = _get_entry_finder()
    if ef is False:
        _MACRO_CACHE.update(ts=now, table=None, fg=None, ok=False)
        return
    table, fg, ok = None, None, False
    try:
        end = pd.Timestamp.utcnow().tz_localize(None)
        start = end - pd.Timedelta(days=3 * 365)
        snap = ef.MacroSnapshot(start, end).build()
        table = snap.table
        fg = ef.fetch_fear_greed()
        ok = table is not None and not table.empty
    except Exception as e:  # pragma: no cover - external APIs
        logger.warning(f"Macro/F&G fetch failed, zero-filling: {e}")
    _MACRO_CACHE.update(ts=now, table=table, fg=fg, ok=ok)


# --------------------------------------------------------------------------- #
# Per-coin feature frame + score (reproduces predict_entry.build_live_features)
# --------------------------------------------------------------------------- #
def _score_latest(df_hist):
    """
    Build the training feature row for the LAST closed bar and return
    (probability, close_price) — or (None, close) if features can't be formed.
    """
    ef = _get_entry_finder()

    # Silence FeatureEngineer's progress prints (30 coins -> too noisy).
    with contextlib.redirect_stdout(StringIO()):
        feat = _FEATURE_ENGINEER(df_hist.copy()).generate_all_features()
    if feat is None or feat.empty:
        return None, float(df_hist["Close"].iloc[-1])

    cols = _SELECT_SCALE_FREE(feat.columns)
    m = feat[["Date"] + cols].copy()

    # Fear & Greed (backward-asof via the original helper).
    if ef is not False and _MACRO_CACHE["fg"] is not None and not _MACRO_CACHE["fg"].empty:
        fg = _MACRO_CACHE["fg"]
        m["FearGreed"] = [ef.fg_at(fg, d).get("FearGreed") for d in m["Date"]]

    # Macro (publication-lagged table, merged strictly backward).
    mt = _MACRO_CACHE["table"]
    if mt is not None and not mt.empty:
        mt_reset = mt.sort_index().reset_index().rename(columns={"index": "Date"})
        mt_reset["Date"] = pd.to_datetime(mt_reset["Date"])
        m = pd.merge_asof(m.sort_values("Date"), mt_reset.sort_values("Date"),
                          on="Date", direction="backward")

    # Align to the EXACT training feature order; anything missing (Funding_Rate,
    # macro when unavailable) -> 0.0, identical to predict_entry.py.
    for c in _FEATURE_LIST:
        if c not in m.columns:
            m[c] = 0.0
    X = m[_FEATURE_LIST].astype(float).fillna(0.0)
    if X.empty:
        return None, float(df_hist["Close"].iloc[-1])

    prob = float(_MODEL.predict_proba(X.iloc[[-1]])[:, 1][0])
    return prob, float(df_hist["Close"].iloc[-1])


# --------------------------------------------------------------------------- #
# Entry point (forwardtest interface)
# --------------------------------------------------------------------------- #
def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):
    """
    ML Predict Entry Point — score every scanned coin with the pooled XGBoost
    entry model and allocate to the top probabilities above threshold.
    Returns (targets, symbol_reasons) exactly like the other algorithms.
    """
    current_holdings = current_holdings or []
    symbol_reasons = {}

    try:
        _load_model()
    except Exception as e:
        logger.error(f"Entry model unavailable: {e}")
        symbol_reasons["SYSTEM"] = {
            "decision_logic": (
                "HOLD CASH: ML entry model could not be loaded "
                f"({type(e).__name__}: {e}). Check BACKTEST_DIR / model files / "
                "xgboost+scikit-learn install."
            ),
        }
        return {}, symbol_reasons

    if USE_MACRO:
        _refresh_macro()
    macro_ok = bool(_MACRO_CACHE.get("ok"))

    # ---- Scan set: the trained BASKET (universe), restricted to what the engine
    #      actually fetched prices for (only those are executable). Falls back to
    #      the engine's data_dict when no universe file is configured. ----
    if UNIVERSE:
        scan_syms = [s for s in UNIVERSE if s in data_dict]
    else:
        scan_syms = list(data_dict.keys())

    # ---- Score every scanned coin on its LAST closed bar ----
    scores = {}          # sym -> prob
    details = {}         # sym -> {close, prob}
    for sym in scan_syms:
        try:
            hist = _fetch_history(sym)
            if hist is None or len(hist) < MIN_HISTORY:
                # Fall back to the ~250 bars the engine already fetched.
                fallback = data_dict.get(sym)
                if fallback is not None and len(fallback) >= MIN_HISTORY:
                    fb = fallback.rename(columns={
                        "open": "Open", "high": "High", "low": "Low",
                        "close": "Close", "volume": "Volume"}).copy()
                    fb["Date"] = pd.to_datetime(fb.index)
                    hist = fb[["Date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)
                else:
                    continue
            prob, close = _score_latest(hist)
            if prob is None:
                continue
            scores[sym] = prob
            details[sym] = {"close": close, "prob": prob}
        except Exception as e:
            logger.warning(f"{sym}: scoring failed ({e})")
            continue

    thr = _THRESHOLD
    signals = {s: p for s, p in scores.items() if p >= thr}

    # ---- No signal: hold cash, mark any holdings for liquidation ----
    if not signals:
        best = max(scores.items(), key=lambda kv: kv[1]) if scores else (None, 0.0)
        if current_holdings:
            for sym in current_holdings:
                symbol_reasons[sym] = {
                    "decision_logic": (
                        "SELL CRITERIA MET: entry probability no longer clears the "
                        f"model threshold ({thr:.2f}). Liquidating."
                    ),
                    "price": details.get(sym, {}).get("close",
                             data_dict[sym]["close"].iloc[-1] if sym in data_dict else 0),
                }
        else:
            symbol_reasons["MARKET"] = {
                "decision_logic": (
                    f"HOLD CASH: no coin's entry probability reached the threshold "
                    f"{thr:.2f}. Best was {best[0]} at {best[1]:.3f}."
                ),
                "formula": "signal = P(entry) >= threshold",
                "macro_ok": macro_ok,
            }
        return {}, symbol_reasons

    # ---- Rank signals, keep top N, weight by probability (capped) ----
    ranked = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)[:MAX_POSITIONS]
    prob_sum = sum(p for _, p in ranked) or 1.0

    targets = {}
    for sym, prob in ranked:
        weight = min(prob / prob_sum, MAX_WEIGHT)
        targets[sym] = weight

        df = data_dict.get(sym)
        close = details[sym]["close"]
        # Volatility-based stop (mirrors v4's reporting fields for the UI).
        vol = np.nan
        if df is not None and len(df) >= 20:
            vol = df["close"].pct_change().rolling(20).std().iloc[-1]
        sl_pct = max(0.05, vol * 2) if np.isfinite(vol) else 0.05
        symbol_reasons[sym] = {
            "decision_logic": (
                f"BUY CRITERIA MET: model entry probability {prob:.3f} >= threshold "
                f"{thr:.2f} (top {MAX_POSITIONS}). Allocating {weight*100:.0f}%."
            ),
            "formula": "P(+100%/30d rally starts here) via pooled XGBoost (n-1 features)",
            "calculation": f"prob {prob:.3f} >= thr {thr:.2f}",
            "price": close,
            "stop_loss_price": close * (1 - sl_pct),
            "est_loss_usd": (total_value * weight) * sl_pct,
            "macro_ok": macro_ok,
        }

    # ---- Liquidate holdings that dropped out of the target set ----
    for sym in current_holdings:
        if sym not in targets:
            symbol_reasons[sym] = {
                "decision_logic": (
                    "SELL CRITERIA MET: fell out of the top entry-probability "
                    "ranking (or below threshold). Liquidating."
                ),
                "price": details.get(sym, {}).get("close",
                         data_dict[sym]["close"].iloc[-1] if sym in data_dict else 0),
            }

    return targets, symbol_reasons
