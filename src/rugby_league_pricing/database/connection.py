from pathlib import Path
import sqlite3

DB_PATH = Path("data/rugby_league.db")

def get_connection():
    return sqlite3.connect(DB_PATH)