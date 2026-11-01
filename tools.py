"""The tools the AI agent can call. Every rule that is about numbers or data is checked HERE,
in code, not only in the prompt, so the model cannot break the rules even if it is tricked."""

import json
from datetime import date, datetime, timedelta

from database import (BOOK_AHEAD_DAYS, FINE_CAP_PER_BOOK, FINE_PER_DAY, MAX_HOLDS,
                      MAX_LOANS, MAX_RENEWALS, RENEW_DAYS, SUSPEND_AT, WEEKDAY_SLOTS,
                      WEEKEND_SLOTS, get_conn)

rule_searcher = None  # set by app.py (a rag.RuleSearcher)


# ---------------------------------------------------------------- helpers
def _today():
    return date.today()


def _verify(conn, card_no, pin):
    card_no = (card_no or "").strip().upper()
    row = conn.execute("SELECT * FROM members WHERE card_no = ?", (card_no,)).fetchone()
    if row is None or str(row["pin"]) != str(pin).strip():
        return None
    return row


AUTH_FAIL = {"ok": False, "error": "auth_failed",
             "message": "卡號或密碼不正確（或查無此借書證）。不可透露任何帳號資料。"}


def _available_copies(conn, book_id):
    book = conn.execute("SELECT total_copies FROM books WHERE book_id = ?", (book_id,)).fetchone()
    out = conn.execute("SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned = 0",
                       (book_id,)).fetchone()[0]
    return book["total_copies"] - out


def _waiting_holds(conn, book_id):
    return conn.execute("SELECT COUNT(*) FROM holds WHERE book_id = ? AND status = 'waiting'",
                        (book_id,)).fetchone()[0]


def _account(conn, card_no):
    """Active loans with the exact overdue days and fines (calculated in code)."""
    today = _today()
    rows = conn.execute("""SELECT l.*, b.title FROM loans l JOIN books b USING(book_id)
                           WHERE l.card_no = ? AND l.returned = 0 ORDER BY l.due_date""",
                        (card_no,)).fetchall()
    loans, total = [], 0
    for r in rows:
        due = date.fromisoformat(r["due_date"])
        overdue = max(0, (today - due).days)
        fine = min(overdue * FINE_PER_DAY, FINE_CAP_PER_BOOK)
        total += fine
        loans.append({"loan_id": r["loan_id"], "book_id": r["book_id"], "title": r["title"],
                      "borrow_date": r["borrow_date"], "due_date": r["due_date"],
                      "days_left": (due - today).days, "overdue_days": overdue,
                      "fine_NTD": fine, "renewals_used": r["renewals"]})
    return loans, total, total >= SUSPEND_AT


def _slots_for(d):
    return WEEKEND_SLOTS if d.weekday() >= 5 else WEEKDAY_SLOTS


def _parse_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return None


def _next_id(conn, table, column, prefix):
    rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    nums = [int(r[0][len(prefix):]) for r in rows if r[0][len(prefix):].isdigit()]
    return f"{prefix}{(max(nums) if nums else 0) + 1:03d}"


# ---------------------------------------------------------------- tools
def search_books(keyword):
    conn = get_conn()
    like = f"%{keyword.strip()}%"
    rows = conn.execute("""SELECT * FROM books WHERE title LIKE ? OR author LIKE ?
                           OR category LIKE ? OR book_id = ? LIMIT 8""",
                        (like, like, like, keyword.strip().upper())).fetchall()
    if not rows:
        conn.close()
        return {"ok": True, "found": 0, "books": [],
                "message": "館藏中查無符合的書。不可推測或編造書名。"}
    books = []
    for b in rows:
        books.append({"book_id": b["book_id"], "title": b["title"], "author": b["author"],
                      "call_no": b["call_no"], "location": b["location"],
                      "total_copies": b["total_copies"],
                      "available_copies": _available_copies(conn, b["book_id"]),
                      "waiting_holds": _waiting_holds(conn, b["book_id"]),
                      "can_take_out": "館內閱覽" not in b["location"],
                      "note": "指定參考書：只能在館內閱覽，不能借出館外，也不能預約" if "館內閱覽" in b["location"] else ""})
    conn.close()
    return {"ok": True, "found": len(books), "books": books}


def get_my_account(card_no, pin):
    conn = get_conn()
    m = _verify(conn, card_no, pin)
    if m is None:
        conn.close()
        return AUTH_FAIL
    loans, total, suspended = _account(conn, m["card_no"])
    holds = [dict(h) for h in conn.execute(
        """SELECT h.hold_id, h.book_id, b.title, h.placed_date, h.status FROM holds h
           JOIN books b USING(book_id) WHERE h.card_no = ? AND h.status = 'waiting'""",
        (m["card_no"],))]
    rooms = [dict(r) for r in conn.execute(
        """SELECT booking_id, room_id, date, slot, people FROM room_bookings
           WHERE card_no = ? AND status = 'booked' AND date >= ? ORDER BY date""",
        (m["card_no"], _today().isoformat()))]
    conn.close()
    return {"ok": True, "name": m["name"], "member_type": m["member_type"],
            "today": _today().isoformat(), "loans": loans,
            "loan_limit": MAX_LOANS[m["member_type"]],
            "total_unpaid_fine_NTD": total, "borrowing_suspended": suspended,
            "holds": holds, "room_bookings": rooms}


def renew_book(card_no, pin, loan_id, confirmed=False):
    conn = get_conn()
    m = _verify(conn, card_no, pin)
    if m is None:
        conn.close()
        return AUTH_FAIL
    loans, total, suspended = _account(conn, m["card_no"])
    loan = next((l for l in loans if l["loan_id"] == str(loan_id).strip().upper()), None)
    reason = None
    if loan is None:
        reason = "查無這筆借閱紀錄（或不是這張借書證借的、或已歸還）。"
    elif suspended:
        reason = f"未繳罰款合計 NT${total}，已達 NT${SUSPEND_AT}，借閱權利已停止，不能續借。"
    elif loan["overdue_days"] > 0:
        reason = "這本書已經逾期，不能續借，請先歸還並繳清罰款。"
    elif loan["renewals_used"] >= MAX_RENEWALS:
        reason = f"這本書已經續借 {MAX_RENEWALS} 次，已達上限。"
    elif _waiting_holds(conn, loan["book_id"]) > 0:
        reason = "這本書已經有其他讀者預約，不能續借。"
    if reason:
        conn.close()
        return {"ok": False, "error": "not_allowed", "message": reason}

    new_due = (date.fromisoformat(loan["due_date"]) + timedelta(days=RENEW_DAYS)).isoformat()
    if not confirmed:
        conn.close()
        return {"ok": True, "status": "need_confirmation",
                "message": "可以續借。請先把以下內容告訴使用者，等使用者明確同意後，再以 confirmed=true 呼叫一次。",
                "title": loan["title"], "old_due_date": loan["due_date"], "new_due_date": new_due}
    conn.execute("UPDATE loans SET due_date = ?, renewals = renewals + 1 WHERE loan_id = ?",
                 (new_due, loan["loan_id"]))
    conn.commit()
    conn.close()
    return {"ok": True, "status": "renewed", "loan_id": loan["loan_id"], "title": loan["title"],
            "new_due_date": new_due, "renewals_used": loan["renewals_used"] + 1}


def place_hold(card_no, pin, book_id, confirmed=False):
    conn = get_conn()
    m = _verify(conn, card_no, pin)
    if m is None:
        conn.close()
        return AUTH_FAIL
    book_id = str(book_id).strip().upper()
    book = conn.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
    _, total, suspended = _account(conn, m["card_no"])
    my_holds = conn.execute("SELECT book_id FROM holds WHERE card_no = ? AND status = 'waiting'",
                            (m["card_no"],)).fetchall()
    has_it = conn.execute("SELECT 1 FROM loans WHERE card_no = ? AND book_id = ? AND returned = 0",
                          (m["card_no"], book_id)).fetchone()
    reason = None
    if book is None:
        reason = "館藏中查無這本書。"
    elif "館內閱覽" in book["location"]:
        reason = "指定參考書（館內閱覽）不能預約。"
    elif suspended:
        reason = f"未繳罰款合計 NT${total}，借閱權利已停止，不能預約。"
    elif _available_copies(conn, book_id) > 0:
        reason = "架上還有可借的複本，不需要預約，請直接到書架取書借閱。"
    elif has_it:
        reason = "你目前已經借了這本書。"
    elif any(h["book_id"] == book_id for h in my_holds):
        reason = "你已經預約過這本書了。"
    elif len(my_holds) >= MAX_HOLDS:
        reason = f"每張借書證最多同時預約 {MAX_HOLDS} 本，已達上限。"
    if reason:
        conn.close()
        return {"ok": False, "error": "not_allowed", "message": reason}
    queue = _waiting_holds(conn, book_id) + 1
    if not confirmed:
        conn.close()
        return {"ok": True, "status": "need_confirmation",
                "message": "可以預約。請先向使用者確認，使用者同意後再以 confirmed=true 呼叫一次。",
                "title": book["title"], "your_queue_position": queue}
    hold_id = _next_id(conn, "holds", "hold_id", "H")
    conn.execute("INSERT INTO holds VALUES (?,?,?,?,?)",
                 (hold_id, m["card_no"], book_id, _today().isoformat(), "waiting"))
    conn.commit()
    conn.close()
    return {"ok": True, "status": "hold_placed", "hold_id": hold_id, "title": book["title"],
            "your_queue_position": queue}


def check_room_availability(date_text, people=None):
    d = _parse_date(date_text)
    today = _today()
    if d is None:
        return {"ok": False, "error": "bad_date", "message": "日期格式要是 YYYY-MM-DD。"}
    if d < today or d > today + timedelta(days=BOOK_AHEAD_DAYS):
        return {"ok": False, "error": "out_of_range",
                "message": f"只能查詢今天（{today}）到 {BOOK_AHEAD_DAYS} 天後（{today + timedelta(days=BOOK_AHEAD_DAYS)}）的討論室。"}
    conn = get_conn()
    rooms = conn.execute("SELECT * FROM rooms").fetchall()
    booked = {(r["room_id"], r["slot"]) for r in conn.execute(
        "SELECT room_id, slot FROM room_bookings WHERE date = ? AND status = 'booked'",
        (d.isoformat(),))}
    conn.close()
    now_hour = datetime.now().hour
    result = []
    for room in rooms:
        if people and not (room["min_people"] <= int(people) <= room["capacity"]):
            continue
        free = [s for s in _slots_for(d) if (room["room_id"], s) not in booked
                and not (d == today and int(s[:2]) <= now_hour)]
        result.append({"room_id": room["room_id"], "name": room["name"],
                       "people": f"{room['min_people']}-{room['capacity']}",
                       "features": room["features"], "free_slots": free})
    return {"ok": True, "date": d.isoformat(), "weekday": "一二三四五六日"[d.weekday()],
            "rooms": result}


def book_study_room(card_no, pin, room_id, date_text, slot, people, confirmed=False):
    conn = get_conn()
    m = _verify(conn, card_no, pin)
    if m is None:
        conn.close()
        return AUTH_FAIL
    today, d = _today(), _parse_date(date_text)
    room = conn.execute("SELECT * FROM rooms WHERE room_id = ?",
                        (str(room_id).strip().upper(),)).fetchone()
    _, total, suspended = _account(conn, m["card_no"])
    reason = None
    try:
        people = int(people)
    except (TypeError, ValueError):
        people = 0
    if room is None:
        reason = "查無這間討論室。"
    elif d is None:
        reason = "日期格式要是 YYYY-MM-DD。"
    elif d < today or d > today + timedelta(days=BOOK_AHEAD_DAYS):
        reason = f"只能預約今天到 {BOOK_AHEAD_DAYS} 天後的時段，不能預約過去的日期。"
    elif slot not in _slots_for(d):
        reason = f"這天可預約的時段只有：{'、'.join(_slots_for(d))}。"
    elif d == today and int(slot[:2]) <= datetime.now().hour:
        reason = "這個時段已經開始或已經過去，不能預約。"
    elif not (room["min_people"] <= people <= room["capacity"]):
        reason = f"{room['name']} 的使用人數必須是 {room['min_people']} 到 {room['capacity']} 人。"
    elif room["room_id"] == "R202" and m["member_type"] != "staff":
        reason = "個人研究小間 202 只開放研究生與教職員。"
    elif suspended:
        reason = f"未繳罰款合計 NT${total}，借閱權利已停止，不能預約討論室。"
    elif conn.execute("""SELECT 1 FROM room_bookings WHERE room_id = ? AND date = ? AND slot = ?
                         AND status = 'booked'""", (room["room_id"], d.isoformat(), slot)).fetchone():
        reason = "這個時段已經被預約了，請選其他時段或討論室。"
    elif conn.execute("""SELECT 1 FROM room_bookings WHERE card_no = ? AND date = ?
                         AND status = 'booked'""", (m["card_no"], d.isoformat())).fetchone():
        reason = "每張借書證每天最多只能預約 1 個時段，你這天已經有預約了。"
    if reason:
        conn.close()
        return {"ok": False, "error": "not_allowed", "message": reason}
    details = {"room": room["name"], "date": d.isoformat(),
               "weekday": "一二三四五六日"[d.weekday()], "slot": slot, "people": people}
    if not confirmed:
        conn.close()
        return {"ok": True, "status": "need_confirmation",
                "message": "可以預約。請把預約內容告訴使用者，等使用者明確同意後，再以 confirmed=true 呼叫一次。",
                **details}
    booking_id = _next_id(conn, "room_bookings", "booking_id", "RB")
    conn.execute("INSERT INTO room_bookings VALUES (?,?,?,?,?,?,?,?)",
                 (booking_id, m["card_no"], room["room_id"], d.isoformat(), slot, people,
                  "booked", datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    return {"ok": True, "status": "booked", "booking_id": booking_id, **details,
            "reminder": "請在時段開始後 15 分鐘內到 1F 流通櫃台報到。"}


def cancel_room_booking(card_no, pin, booking_id, confirmed=False):
    conn = get_conn()
    m = _verify(conn, card_no, pin)
    if m is None:
        conn.close()
        return AUTH_FAIL
    b = conn.execute("""SELECT rb.*, r.name FROM room_bookings rb JOIN rooms r USING(room_id)
                        WHERE booking_id = ? AND card_no = ? AND status = 'booked'""",
                     (str(booking_id).strip().upper(), m["card_no"])).fetchone()
    if b is None:
        conn.close()
        return {"ok": False, "error": "not_found",
                "message": "查無這筆預約（或不是這張借書證的預約、或已取消）。"}
    d = date.fromisoformat(b["date"])
    if d < _today() or (d == _today() and int(b["slot"][:2]) <= datetime.now().hour):
        conn.close()
        return {"ok": False, "error": "not_allowed", "message": "時段已經開始或已經過去，不能取消。"}
    details = {"booking_id": b["booking_id"], "room": b["name"], "date": b["date"], "slot": b["slot"]}
    if not confirmed:
        conn.close()
        return {"ok": True, "status": "need_confirmation",
                "message": "請向使用者確認是否取消，同意後再以 confirmed=true 呼叫一次。", **details}
    conn.execute("UPDATE room_bookings SET status = 'cancelled' WHERE booking_id = ?",
                 (b["booking_id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "status": "cancelled", **details}


def search_library_rules(query):
    if rule_searcher is None:
        return {"ok": False, "error": "rag_not_ready", "message": "館規搜尋目前無法使用。"}
    hits = rule_searcher.search(query, top_k=3)
    return {"ok": True, "note": "只能根據以下段落回答；若段落沒有答案，就說館規中沒有這項說明。",
            "results": [{"source": h["source"], "section": h["section"], "text": h["text"],
                         "score": h["score"]} for h in hits]}


# ---------------------------------------------------------------- schemas for the model
def _fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


CARD = {"type": "string", "description": "借書證卡號，例如 LC1001"}
PIN = {"type": "string", "description": "借書證的 4 位數密碼"}
CONFIRMED = {"type": "boolean",
             "description": "只有在使用者看過內容並明確說『確認／好／是』之後才設為 true；第一次呼叫一律 false"}

TOOLS = [
    _fn("search_books", "用關鍵字（書名、作者或類別）查詢館藏，回傳索書號、位置與目前可借冊數。",
        {"keyword": {"type": "string"}}, ["keyword"]),
    _fn("get_my_account", "查詢讀者自己的借閱紀錄、到期日、逾期罰款、預約與討論室預約。需要卡號與密碼。",
        {"card_no": CARD, "pin": PIN}, ["card_no", "pin"]),
    _fn("renew_book", "續借一筆借閱（loan_id）。程式會檢查所有續借規則。",
        {"card_no": CARD, "pin": PIN, "loan_id": {"type": "string", "description": "例如 L001"},
         "confirmed": CONFIRMED}, ["card_no", "pin", "loan_id"]),
    _fn("place_hold", "預約一本所有複本都已借出的書。",
        {"card_no": CARD, "pin": PIN, "book_id": {"type": "string", "description": "例如 B003"},
         "confirmed": CONFIRMED}, ["card_no", "pin", "book_id"]),
    _fn("check_room_availability", "查詢某一天各討論室還有哪些空的時段。",
        {"date_text": {"type": "string", "description": "YYYY-MM-DD"},
         "people": {"type": "integer", "description": "使用人數（可省略）"}}, ["date_text"]),
    _fn("book_study_room", "預約討論室的一個時段。",
        {"card_no": CARD, "pin": PIN, "room_id": {"type": "string", "description": "例如 R101"},
         "date_text": {"type": "string", "description": "YYYY-MM-DD"},
         "slot": {"type": "string", "description": "例如 13:00-15:00"},
         "people": {"type": "integer"}, "confirmed": CONFIRMED},
        ["card_no", "pin", "room_id", "date_text", "slot", "people"]),
    _fn("cancel_room_booking", "取消自己的討論室預約。",
        {"card_no": CARD, "pin": PIN, "booking_id": {"type": "string", "description": "例如 RB005"},
         "confirmed": CONFIRMED}, ["card_no", "pin", "booking_id"]),
    _fn("search_library_rules",
        "搜尋圖書館規則文件（借閱、續借、罰款、遺失賠償、討論室規定、預約、開放時間、飲食、影印、校友、VPN 等）。回答任何規則問題前都必須先呼叫。",
        {"query": {"type": "string", "description": "用完整的中文問句搜尋效果最好"}}, ["query"]),
]

FUNCTIONS = {f.__name__: f for f in [search_books, get_my_account, renew_book, place_hold,
                                     check_room_availability, book_study_room,
                                     cancel_room_booking, search_library_rules]}


def run_tool(name, arguments_json):
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad_arguments"}
    func = FUNCTIONS.get(name)
    if func is None:
        return {"ok": False, "error": f"unknown tool {name}"}
    try:
        return func(**args)
    except TypeError as e:
        return {"ok": False, "error": f"wrong arguments: {e}"}
