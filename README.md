# 📚 星港大學圖書館 線上服務台（Library Help Desk Agent）

A customer service chatbot for a **fictional** university library ("Star Harbor University Library").
Students and staff can ask it to look up books, check their loans and fines, renew a book,
place a hold, book or cancel a study room, and answer questions about the library rules.

It uses **tool calling** (an agent with 8 tools reading and writing a SQLite database)
and **RAG** (the library rule book is searched with an embedding model).

> All names, card numbers, PINs, books and rules in this project are **made up**.

## What it can do

| User need | How the app does it |
|---|---|
| "Is this book on the shelf?" | `search_books` reads the `books` and `loans` tables and counts the free copies |
| "When are my books due? Do I owe a fine?" | `get_my_account` checks card number + PIN, then calculates overdue days and fines in Python |
| Renew a book / place a hold | `renew_book`, `place_hold` check every rule in code, ask the user to confirm, then **write** to the database |
| Book or cancel a study room | `check_room_availability`, `book_study_room`, `cancel_room_booking` (also write to the database) |
| "Can I bring coffee?" "Can my fine be waived?" | `search_library_rules` = **RAG** over `library_rules/*.md` (33 sections), answer only from the found sections, with the source |

Rules the AI must follow (in the system prompt **and** in the code):

1. Never invent a book, a due date, a fine or a rule: every fact comes from a tool.
2. Never waive fines, extend a due date, or give "special favours".
3. Never show account data without the correct card number **and** PIN.
4. Never change anything (renew, hold, book, cancel) before the user says "confirm". The tools have a
   `confirmed` parameter: the first call only checks the rules and returns a summary.
5. Only answer library questions; refuse everything else with a fixed sentence.

## Project files

```
app.py                  Gradio chat screen + the agent loop (tool calling)
tools.py                The 8 tools and their JSON schemas; all rule checks are here
rag.py                  RAG: cut the rule files into sections, embed, cosine search (cached)
database.py             Builds library.db from the CSV files (python database.py)
prompts/system_prompt.md  The system prompt (5 parts)
data/*.csv              Fake data: books, members, loans, holds, rooms, room_bookings
library_rules/*.md      The library rule book used for RAG (7 documents)
.env.example            Settings template (copy to .env and add your key)
```

## How to install and run

1. Install Python 3.10 or newer.
2. Download this project and open a console in its folder:
   ```bash
   git clone https://github.com/<your-account>/library-helpdesk.git
   cd library-helpdesk
   ```
3. (Recommended) Make a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:  .venv\Scripts\activate
   # macOS / Linux:  source .venv/bin/activate
   ```
4. Install the packages:
   ```bash
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env` and put your API key after `API_KEY=` and `EMBEDDING_API_KEY=`
   (I used Google Gemini: get a free key at https://aistudio.google.com/apikey. NKUST AI Hub also works.)
   **Never upload `.env`.**
6. Run the app:
   ```bash
   python app.py
   ```
   Open <http://127.0.0.1:7860>. The first start builds `library.db` and embeds the rule book
   (saved in `.cache/`, so later starts are fast).

### Demo accounts (fake)

| Card | PIN | Situation to try |
|---|---|---|
| LC1001 | 1234 | 3 loans: one can be renewed (L001), one is held by another reader (L002), one already renewed twice (L003) |
| LC1002 | 5678 | One book overdue 6 days → fine NT$30, cannot renew it |
| LC1003 | 2468 | Fine NT$150 ≥ NT$100 → borrowing rights suspended |
| LC1004 | 1357 | Staff member (may book the single research room R202) |

Dates are stored as "days before / after today", so the demo always looks current.
To reset all data, run `python database.py` or press **♻️ 重建示範資料** in the "資料庫檢視" tab.

## Data sources

All data was written for this project and is fictional. No real people, student IDs or orders are used.
