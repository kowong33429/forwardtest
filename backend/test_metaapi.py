import os
import time
from dotenv import load_dotenv
import mt5_service

load_dotenv()

def run_test():
    print("Testing MetaAPI Connection Health...")
    health = mt5_service.check_health()
    print("Health Status:", health)
    
    if health.get("status") == "connected":
        # Check available symbols or just use XAUUSDc/XAUUSDm
        symbol = "XAUUSDm" # Exness Cent is often XAUUSDc or m. We will try XAUUSDm as it's common.
        print(f"\nConnection successful. Attempting to place a test order (0.01 lot BUY {symbol})...")
        
        result = mt5_service.execute_trade(
            symbol=symbol,
            direction="LONG",
            volume=0.01,
            sl=None,
            tp=None,
            comment="Test Order via AI"
        )
        print("Trade Result:", result)
        if result.get("status") == "success":
            print("\n✅ Order successfully placed!")
            ticket = result.get("ticket")
            print(f"Ticket ID: {ticket}")
        else:
            print("\n❌ Failed to place order. You might need to change the symbol to match your broker (e.g. XAUUSDc).")
    else:
        print("\n❌ Failed to connect to MetaAPI.")

if __name__ == "__main__":
    run_test()
