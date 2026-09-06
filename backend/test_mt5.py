from services.mt5_service import check_health, is_forex_market_open, fetch_historical_klines

if __name__ == "__main__":
    print("=== MT5 Bridge Connection Test ===")
    
    print("\n1. Checking MT5 Bridge Health...")
    health = check_health()
    print(f"Health Result: {health}")
    
    print("\n2. Checking Market Open Status (XAUUSD)...")
    market_open = is_forex_market_open("XAUUSD")
    print(f"Market Open Result: {market_open}")
    
    print("\n3. Fetching Historical Klines (XAUUSD, 1h, limit=5)...")
    df = fetch_historical_klines("XAUUSD", "1h", limit=5)
    if df is not None:
        print(f"Historical Data Shape: {df.shape}")
        print(df.head())
    else:
        print("Historical Data: Failed to fetch (returned None)")
