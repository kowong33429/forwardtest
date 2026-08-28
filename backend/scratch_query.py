import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv('.env')
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    print("\n--- Recent SELL trades ---")
    result = conn.execute(text("SELECT p.algorithm_name, t.symbol, t.action, t.timestamp FROM portfolios p JOIN trades t ON p.id = t.portfolio_id WHERE t.action = 'SELL' ORDER BY t.timestamp DESC LIMIT 20;"))
    for row in result:
        print(f"[{row[3]}] {row[0]} sold {row[1]}")
