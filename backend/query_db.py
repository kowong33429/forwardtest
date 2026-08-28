import os
import sys
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text

load_dotenv('.env')
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

try:
    with engine.connect() as conn:
        print("=== Portfolios ===")
        portfolios = pd.read_sql("SELECT id, algorithm_name, file_name, balance_usd, is_deleted FROM portfolios WHERE is_deleted=0", conn)
        print(portfolios)
        
        print("\n=== Positions ===")
        positions = pd.read_sql("SELECT id, portfolio_id, symbol, amount FROM positions", conn)
        print(positions.groupby('portfolio_id').size().reset_index(name='count'))
        
        print("\n=== Engine Logs Count ===")
        logs = pd.read_sql("SELECT portfolio_id, COUNT(*) as log_count, MAX(timestamp) as last_log FROM engine_logs GROUP BY portfolio_id", conn)
        print(logs)
except Exception as e:
    print(f"Error: {e}")
