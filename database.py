"""Build the SQLite database (library.db) from the fake CSV files in data/.

Dates in the CSV files are written as "days before / after today", so the demo data
always looks fresh: run this file again (python database.py) to rebuild the database.
"""

import csv
import sqlite3
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "library.db"

# Library rules that the code must enforce (they match library_rules/*.md)
LOAN_DAYS = {"student": 21, "staff": 42}
MAX_LOANS = {"student": 10, "staff": 20}
RENEW_DAYS = 14
MAX_RENEWALS = 2
FINE_PER_DAY = 5          # NT$ per book per day
FINE_CAP_PER_BOOK = 300   # NT$ per book
SUSPEND_AT = 100          # NT$ of unpaid fines that stops borrowing rights
MAX_HOLDS = 5
BOOK_AHEAD_DAYS = 7
WEEKDAY_SLOTS = ["09:00-11:00", "11:00-13:00", "13:00-15:00",
                 "15:00-17:00", "17:00-19:00", "19:00-21:00"]
WEEKEND_SLOTS = WEEKDAY_SLOTS[:4]


def read_csv(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_conn():
    if not DB_PATH.exists():
        build_database()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_database(today=None):
    today = today or date.today()
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE books (
        book_id TEXT PRIMARY KEY, title TEXT, author TEXT, call_no TEXT,
        category TEXT, location TEXT, total_copies INTEGER);
    CREATE TABLE members (
        card_no TEXT PRIMARY KEY, name TEXT, pin TEXT, member_type TEXT);
    CREATE TABLE loans (
        loan_id TEXT PRIMARY KEY, card_no TEXT, book_id TEXT,
        borrow_date TEXT, due_date TEXT, renewals INTEGER, returned INTEGER);
    CREATE TABLE holds (
        hold_id TEXT PRIMARY KEY, card_no TEXT, book_id TEXT,
        placed_date TEXT, status TEXT);
    CREATE TABLE rooms (
        room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER,
        min_people INTEGER, floor TEXT, features TEXT);
    CREATE TABLE room_bookings (
        booking_id TEXT PRIMARY KEY, card_no TEXT, room_id TEXT,
        date TEXT, slot TEXT, people INTEGER, status TEXT, created_at TEXT);
    """)

    for r in read_csv("books.csv"):
        cur.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?)",
                    (r["book_id"], r["title"], r["author"], r["call_no"],
                     r["category"], r["location"], int(r["total_copies"])))

    members = {}
    for r in read_csv("members.csv"):
        members[r["card_no"]] = r["member_type"]
        cur.execute("INSERT INTO members VALUES (?,?,?,?)",
                    (r["card_no"], r["name"], r["pin"], r["member_type"]))

    for r in read_csv("loans.csv"):
        borrow = today - timedelta(days=int(r["borrowed_days_ago"]))
        renewals = int(r["renewals"])
        due = borrow + timedelta(days=LOAN_DAYS[members[r["card_no"]]] + RENEW_DAYS * renewals)
        cur.execute("INSERT INTO loans VALUES (?,?,?,?,?,?,?)",
                    (r["loan_id"], r["card_no"], r["book_id"], borrow.isoformat(),
                     due.isoformat(), renewals, int(r["returned"])))

    for r in read_csv("holds.csv"):
        placed = today - timedelta(days=int(r["placed_days_ago"]))
        cur.execute("INSERT INTO holds VALUES (?,?,?,?,?)",
                    (r["hold_id"], r["card_no"], r["book_id"], placed.isoformat(), r["status"]))

    for r in read_csv("rooms.csv"):
        cur.execute("INSERT INTO rooms VALUES (?,?,?,?,?,?)",
                    (r["room_id"], r["name"], int(r["capacity"]), int(r["min_people"]),
                     r["floor"], r["features"]))

    for r in read_csv("room_bookings.csv"):
        d = today + timedelta(days=int(r["days_from_today"]))
        cur.execute("INSERT INTO room_bookings VALUES (?,?,?,?,?,?,?,?)",
                    (r["booking_id"], r["card_no"], r["room_id"], d.isoformat(),
                     r["slot"], int(r["people"]), r["status"], "seed data"))

    conn.commit()
    conn.close()
    print(f"Database built: {DB_PATH} (today = {today.isoformat()})")


if __name__ == "__main__":
    build_database()
