from database import SessionLocal, Portfolio

def fix_initial_balance():
    db = SessionLocal()
    try:
        port = db.query(Portfolio).filter(Portfolio.algorithm_name == "V43 Whipsaw Killer").first()
        if port:
            port.initial_balance = 10068.0
            db.commit()
            print("Successfully updated initial_balance for V43 to 10068.0")
        else:
            print("V43 portfolio not found")
    finally:
        db.close()

if __name__ == "__main__":
    fix_initial_balance()
