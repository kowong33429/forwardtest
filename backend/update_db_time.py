import os
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://postgres:Tonzazahaha_33429@db.zopiretbklxzfnjicksq.supabase.co:5432/postgres"
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    tables = [
        ("portfolios", ["created_at", "updated_at"]),
        ("trades", ["timestamp"]),
        ("futures_trades", ["timestamp"]),
        ("ai_insights", ["created_at"]),
        ("futures_ai_insights", ["created_at"]),
        ("engine_logs", ["timestamp"]),
        ("daily_optimization_results", ["timestamp"])
    ]
    for table, cols in tables:
        for col in cols:
            conn.execute(text(f"UPDATE {table} SET {col} = {col} + INTERVAL '7 hours'"))
    print("Successfully updated database timestamps.")
