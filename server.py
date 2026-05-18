#!/usr/bin/env python3
"""
FIFA 2026 World Cup Sticker Exchange App
Pure Python stdlib — SQLite by default, PostgreSQL when DATABASE_URL is set.

Usage:
  python3 server.py                  → start the web server
  python3 server.py generate [N]     → generate N invite codes (default 20) and print them
"""

import http.server
import socketserver
import json
import hashlib
import uuid
import os
import sys
import re
import secrets
import string
from urllib.parse import urlparse

# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────
PORT         = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL")   # set this for PostgreSQL
DB_PATH      = os.environ.get("DB_PATH", os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "stickers.db"))

SESSION_STORE: dict[str, int] = {}   # token -> user_id  (in-memory)
USE_PG = bool(DATABASE_URL)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# ──────────────────────────────────────────────
#  Database layer  (SQLite ↔ PostgreSQL shim)
# ──────────────────────────────────────────────
if USE_PG:
    import psycopg2
    import psycopg2.extras
    PH = "%s"

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        return conn

    def rows_to_dicts(cursor):
        if not cursor.description:
            return []
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]

    def row_to_dict(cursor):
        if not cursor.description:
            return None
        cols = [d[0] for d in cursor.description]
        r = cursor.fetchone()
        return dict(zip(cols, r)) if r else None

else:
    import sqlite3
    PH = "?"

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def rows_to_dicts(cursor):
        return [dict(r) for r in cursor.fetchall()]

    def row_to_dict(cursor):
        r = cursor.fetchone()
        return dict(r) if r else None


def run_sql(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

def fetch_one(conn, sql, params=()):
    cur = run_sql(conn, sql, params)
    return row_to_dict(cur)

def fetch_all(conn, sql, params=()):
    cur = run_sql(conn, sql, params)
    return rows_to_dicts(cur)

def last_insert_id(conn, cur):
    if USE_PG:
        return fetch_one(conn, "SELECT lastval() AS id")["id"]
    return cur.lastrowid

# ──────────────────────────────────────────────
#  Schema
# ──────────────────────────────────────────────
SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    username   TEXT    NOT NULL UNIQUE,
    password   TEXT    NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stickers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    number   TEXT    NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    UNIQUE(user_id, number)
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code      TEXT PRIMARY KEY,
    used_by   INTEGER REFERENCES users(id),
    used_at   DATETIME
);

CREATE TABLE IF NOT EXISTS swaps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a       INTEGER NOT NULL REFERENCES users(id),
    user_b       INTEGER NOT NULL REFERENCES users(id),
    a_gives      TEXT NOT NULL,
    b_gives      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed',
    swap_code    TEXT UNIQUE,
    proposed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    accepted_at  DATETIME,
    completed_at DATETIME
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    name       TEXT    NOT NULL,
    username   TEXT    NOT NULL UNIQUE,
    password   TEXT    NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stickers (
    id       SERIAL PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    number   TEXT    NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    UNIQUE(user_id, number)
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code    TEXT PRIMARY KEY,
    used_by INTEGER REFERENCES users(id),
    used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS swaps (
    id           SERIAL PRIMARY KEY,
    user_a       INTEGER NOT NULL REFERENCES users(id),
    user_b       INTEGER NOT NULL REFERENCES users(id),
    a_gives      TEXT NOT NULL,
    b_gives      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed',
    swap_code    TEXT UNIQUE,
    proposed_at  TIMESTAMPTZ DEFAULT NOW(),
    accepted_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
"""

def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
        if USE_PG:
            for stmt in SCHEMA_PG.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        else:
            conn.executescript(SCHEMA_SQLITE)
        conn.commit()
    finally:
        conn.close()

# ──────────────────────────────────────────────
#  Invite code helpers
# ──────────────────────────────────────────────
_CHARS = string.ascii_uppercase + string.digits

def _make_code(n=5) -> str:
    return ''.join(secrets.choice(_CHARS) for _ in range(n))

def make_invite_code() -> str:
    return f"{_make_code(5)}-{_make_code(5)}"

def make_swap_code() -> str:
    return f"SW-{_make_code(4)}"

def generate_codes(n: int = 20) -> list[str]:
    codes = []
    conn = get_db()
    try:
        existing = {r["code"] for r in fetch_all(conn, "SELECT code FROM invite_codes")}
        for _ in range(n):
            code = make_invite_code()
            while code in existing:
                code = make_invite_code()
            existing.add(code)
            if USE_PG:
                run_sql(conn, "INSERT INTO invite_codes (code) VALUES (%s) ON CONFLICT DO NOTHING", (code,))
            else:
                run_sql(conn, "INSERT OR IGNORE INTO invite_codes (code) VALUES (?)", (code,))
            codes.append(code)
        conn.commit()
    finally:
        conn.close()
    return codes

# ──────────────────────────────────────────────
#  Auth helpers
# ──────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user(token: str | None):
    if not token:
        return None
    user_id = SESSION_STORE.get(token)
    if not user_id:
        return None
    conn = get_db()
    try:
        return fetch_one(conn, f"SELECT id, name, username FROM users WHERE id={PH}", (user_id,))
    finally:
        conn.close()

def token_from_headers(headers) -> str | None:
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None

# ──────────────────────────────────────────────
#  Exchange matching (read-only suggestions)
# ──────────────────────────────────────────────
def compute_exchanges(my_user_id: int):
    """Suggest which friends I can swap with, and what stickers would move."""
    conn = get_db()
    try:
        others = fetch_all(conn,
            f"SELECT id, name, username FROM users WHERE id != {PH}", (my_user_id,))

        my = {r["number"]: r["quantity"]
              for r in fetch_all(conn,
                  f"SELECT number, quantity FROM stickers WHERE user_id={PH}", (my_user_id,))}

        results = []
        for o in others:
            theirs = {r["number"]: r["quantity"]
                      for r in fetch_all(conn,
                          f"SELECT number, quantity FROM stickers WHERE user_id={PH}", (o["id"],))}

            i_can_give    = sorted([n for n, q in my.items()     if q > 1 and n not in theirs],
                                   key=lambda x: x.zfill(20))
            they_can_give = sorted([n for n, q in theirs.items() if q > 1 and n not in my],
                                   key=lambda x: x.zfill(20))

            # Check for existing open swap between these two users
            open_swap = fetch_one(conn, f"""
                SELECT id, status, swap_code
                FROM swaps
                WHERE status NOT IN ('done','cancelled')
                  AND ((user_a={PH} AND user_b={PH}) OR (user_a={PH} AND user_b={PH}))
            """, (my_user_id, o["id"], o["id"], my_user_id))

            if i_can_give or they_can_give:
                results.append({
                    "user_id":       o["id"],
                    "name":          o["name"],
                    "username":      o["username"],
                    "i_can_give":    i_can_give,
                    "they_can_give": they_can_give,
                    "score":         len(i_can_give) + len(they_can_give),
                    "open_swap":     open_swap,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results
    finally:
        conn.close()

def enrich_swap(conn, swap: dict, my_user_id: int) -> dict:
    """Add name/username of the other party to a swap dict."""
    other_id = swap["user_b"] if swap["user_a"] == my_user_id else swap["user_a"]
    other = fetch_one(conn, f"SELECT name, username FROM users WHERE id={PH}", (other_id,))
    swap["other_name"]     = other["name"]     if other else "?"
    swap["other_username"] = other["username"] if other else "?"
    swap["i_am_a"]         = (swap["user_a"] == my_user_id)
    swap["a_gives"]        = json.loads(swap["a_gives"])
    swap["b_gives"]        = json.loads(swap["b_gives"])
    return swap

# ──────────────────────────────────────────────
#  HTTP Handler
# ──────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, status=400):
        self.send_json({"error": msg}, status)

    def read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def require_auth(self):
        u = get_current_user(token_from_headers(self.headers))
        if not u:
            self.send_error_json("Not authenticated", 401)
        return u

    # ── routing ──────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        static = {
            "/":           ("index.html", "text/html"),
            "/index.html": ("index.html", "text/html"),
            "/admin.html": ("admin.html", "text/html"),
            "/app.js":     ("app.js",     "application/javascript"),
            "/style.css":  ("style.css",  "text/css"),
        }
        if path in static:
            f, ct = static[path]
            return self.serve_static(f, ct)

        if path == "/admin":
            return self.admin_page()

        apis = {
            "/api/me":        self.api_me,
            "/api/users":     self.api_users,
            "/api/stickers":  self.api_get_stickers,
            "/api/exchanges": self.api_exchanges,
            "/api/swaps":     self.api_get_swaps,
            "/api/admin/codes": self.api_list_codes,
        }
        if path in apis:
            return apis[path]()

        m = re.match(r"^/api/stickers/user/(\d+)$", path)
        if m:
            return self.api_get_stickers_for_user(int(m.group(1)))

        self.send_error_json("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        apis = {
            "/api/register":      self.api_register,
            "/api/login":         self.api_login,
            "/api/logout":        self.api_logout,
            "/api/stickers":      self.api_add_stickers,
            "/api/swaps":         self.api_propose_swap,
            "/api/admin/generate": self.api_admin_generate,
        }
        if path in apis:
            return apis[path]()

        m = re.match(r"^/api/swaps/(\d+)/(accept|complete|cancel)$", path)
        if m:
            return self.api_swap_action(int(m.group(1)), m.group(2))

        self.send_error_json("Not found", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        m = re.match(r"^/api/stickers/(.+)$", path)
        if m:
            return self.api_delete_sticker(m.group(1))
        self.send_error_json("Not found", 404)

    # ── static ────────────────────────────────
    def serve_static(self, filename, ct):
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            data = open(fp, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error_json("Not found", 404)

    # ── auth ──────────────────────────────────
    def api_register(self):
        b = self.read_body()
        name     = (b.get("name")        or "").strip()
        username = (b.get("username")    or "").strip().lower()
        password =  b.get("password")    or ""
        code     = (b.get("invite_code") or "").strip().upper()

        if not all([name, username, password, code]):
            return self.send_error_json("Name, username, password, and invite code are required")
        if len(username) < 3:
            return self.send_error_json("Username must be at least 3 characters")
        if len(password) < 4:
            return self.send_error_json("Password must be at least 4 characters")
        if not re.match(r"^[a-z0-9_]+$", username):
            return self.send_error_json("Username: letters, numbers, and underscores only")

        conn = get_db()
        try:
            ic = fetch_one(conn, f"SELECT code, used_by FROM invite_codes WHERE code={PH}", (code,))
            if not ic:
                return self.send_error_json("Invalid invite code")
            if ic["used_by"] is not None:
                return self.send_error_json("That invite code has already been used")

            try:
                cur = run_sql(conn,
                    f"INSERT INTO users (name, username, password) VALUES ({PH},{PH},{PH})",
                    (name, username, hash_password(password)))
                user_id = last_insert_id(conn, cur)
            except Exception as e:
                if "unique" in str(e).lower():
                    return self.send_error_json("Username already taken")
                raise

            if USE_PG:
                run_sql(conn, "UPDATE invite_codes SET used_by=%s, used_at=NOW() WHERE code=%s",
                        (user_id, code))
            else:
                run_sql(conn, "UPDATE invite_codes SET used_by=?, used_at=CURRENT_TIMESTAMP WHERE code=?",
                        (user_id, code))
            conn.commit()
        finally:
            conn.close()

        token = str(uuid.uuid4())
        SESSION_STORE[token] = user_id
        self.send_json({"token": token, "user": {"id": user_id, "name": name, "username": username}})

    def api_login(self):
        b = self.read_body()
        username = (b.get("username") or "").strip().lower()
        password =  b.get("password") or ""
        conn = get_db()
        try:
            row = fetch_one(conn,
                f"SELECT id, name, username FROM users WHERE username={PH} AND password={PH}",
                (username, hash_password(password)))
        finally:
            conn.close()
        if not row:
            return self.send_error_json("Invalid username or password", 401)
        token = str(uuid.uuid4())
        SESSION_STORE[token] = row["id"]
        self.send_json({"token": token, "user": row})

    def api_logout(self):
        t = token_from_headers(self.headers)
        if t in SESSION_STORE:
            del SESSION_STORE[t]
        self.send_json({"ok": True})

    # ── me / users ─────────────────────────────
    def api_me(self):
        u = self.require_auth()
        if not u:
            return
        conn = get_db()
        try:
            c = fetch_one(conn,
                f"SELECT COUNT(*) as unique_count, COALESCE(SUM(quantity),0) as total "
                f"FROM stickers WHERE user_id={PH}", (u["id"],))
            pending = fetch_one(conn,
                f"SELECT COUNT(*) as n FROM swaps "
                f"WHERE status='proposed' AND user_b={PH}", (u["id"],))
        finally:
            conn.close()
        u["unique_stickers"] = c["unique_count"] or 0
        u["total_stickers"]  = c["total"] or 0
        u["pending_swaps"]   = pending["n"] or 0
        self.send_json(u)

    def api_users(self):
        if not self.require_auth():
            return
        conn = get_db()
        try:
            rows = fetch_all(conn, f"""
                SELECT u.id, u.name, u.username,
                       COUNT(s.id) as unique_stickers,
                       COALESCE(SUM(s.quantity),0) as total_stickers
                FROM users u
                LEFT JOIN stickers s ON s.user_id = u.id
                GROUP BY u.id, u.name, u.username
                ORDER BY u.name
            """)
        finally:
            conn.close()
        self.send_json(rows)

    # ── stickers ──────────────────────────────
    def api_get_stickers(self):
        u = self.require_auth()
        if not u:
            return
        conn = get_db()
        try:
            rows = fetch_all(conn,
                f"SELECT number, quantity FROM stickers WHERE user_id={PH} ORDER BY number",
                (u["id"],))
        finally:
            conn.close()
        self.send_json(rows)

    def api_get_stickers_for_user(self, uid):
        if not self.require_auth():
            return
        conn = get_db()
        try:
            rows = fetch_all(conn,
                f"SELECT number, quantity FROM stickers WHERE user_id={PH} ORDER BY number",
                (uid,))
        finally:
            conn.close()
        self.send_json(rows)

    def api_add_stickers(self):
        u = self.require_auth()
        if not u:
            return
        b    = self.read_body()
        raw  = b.get("stickers", [])
        if not isinstance(raw, list) or not raw:
            return self.send_error_json("Provide a non-empty 'stickers' array")

        additions: dict[str, int] = {}
        for item in raw:
            if isinstance(item, str):
                n = item.strip().upper()
                if n:
                    additions[n] = additions.get(n, 0) + 1
            elif isinstance(item, dict):
                n = str(item.get("number", "")).strip().upper()
                q = max(1, int(item.get("quantity", 1)))
                if n:
                    additions[n] = additions.get(n, 0) + q

        if not additions:
            return self.send_error_json("No valid sticker numbers found")

        conn = get_db()
        try:
            for number, qty in additions.items():
                if USE_PG:
                    run_sql(conn, """
                        INSERT INTO stickers (user_id, number, quantity) VALUES (%s,%s,%s)
                        ON CONFLICT (user_id, number)
                        DO UPDATE SET quantity = stickers.quantity + EXCLUDED.quantity
                    """, (u["id"], number, qty))
                else:
                    run_sql(conn, """
                        INSERT INTO stickers (user_id, number, quantity) VALUES (?,?,?)
                        ON CONFLICT(user_id, number)
                        DO UPDATE SET quantity = quantity + excluded.quantity
                    """, (u["id"], number, qty))
            conn.commit()
            rows = fetch_all(conn,
                f"SELECT number, quantity FROM stickers WHERE user_id={PH} ORDER BY number",
                (u["id"],))
        finally:
            conn.close()
        self.send_json({"added": len(additions), "stickers": rows})

    def api_delete_sticker(self, number):
        u = self.require_auth()
        if not u:
            return
        conn = get_db()
        try:
            run_sql(conn,
                f"DELETE FROM stickers WHERE user_id={PH} AND number={PH}",
                (u["id"], number.upper()))
            conn.commit()
        finally:
            conn.close()
        self.send_json({"ok": True})

    # ── exchange suggestions ───────────────────
    def api_exchanges(self):
        u = self.require_auth()
        if not u:
            return
        self.send_json(compute_exchanges(u["id"]))

    # ── swaps (propose / accept / complete / cancel) ──
    def api_propose_swap(self):
        u = self.require_auth()
        if not u:
            return
        b = self.read_body()
        other_id = b.get("other_user_id")
        if not other_id:
            return self.send_error_json("other_user_id is required")
        other_id = int(other_id)
        if other_id == u["id"]:
            return self.send_error_json("You can't swap with yourself")

        conn = get_db()
        try:
            # Check other user exists
            other = fetch_one(conn, f"SELECT id, name FROM users WHERE id={PH}", (other_id,))
            if not other:
                return self.send_error_json("User not found")

            # Check no open swap already
            existing = fetch_one(conn, f"""
                SELECT id FROM swaps
                WHERE status NOT IN ('done','cancelled')
                  AND ((user_a={PH} AND user_b={PH}) OR (user_a={PH} AND user_b={PH}))
            """, (u["id"], other_id, other_id, u["id"]))
            if existing:
                return self.send_error_json("There is already an open swap with this user")

            # Compute stickers to swap
            my     = {r["number"]: r["quantity"] for r in fetch_all(conn,
                        f"SELECT number, quantity FROM stickers WHERE user_id={PH}", (u["id"],))}
            theirs = {r["number"]: r["quantity"] for r in fetch_all(conn,
                        f"SELECT number, quantity FROM stickers WHERE user_id={PH}", (other_id,))}

            a_gives = sorted([n for n, q in my.items()     if q > 1 and n not in theirs], key=lambda x: x.zfill(20))
            b_gives = sorted([n for n, q in theirs.items() if q > 1 and n not in my],     key=lambda x: x.zfill(20))

            if not a_gives and not b_gives:
                return self.send_error_json("No stickers to swap with this user right now")

            cur = run_sql(conn,
                f"INSERT INTO swaps (user_a, user_b, a_gives, b_gives) VALUES ({PH},{PH},{PH},{PH})",
                (u["id"], other_id, json.dumps(a_gives), json.dumps(b_gives)))
            swap_id = last_insert_id(conn, cur)
            conn.commit()
            swap = fetch_one(conn, f"SELECT * FROM swaps WHERE id={PH}", (swap_id,))
            swap = enrich_swap(conn, swap, u["id"])
        finally:
            conn.close()
        self.send_json(swap)

    def api_get_swaps(self):
        u = self.require_auth()
        if not u:
            return
        conn = get_db()
        try:
            rows = fetch_all(conn,
                f"SELECT * FROM swaps WHERE (user_a={PH} OR user_b={PH}) ORDER BY proposed_at DESC",
                (u["id"], u["id"]))
            enriched = [enrich_swap(conn, r, u["id"]) for r in rows]
        finally:
            conn.close()
        self.send_json(enriched)

    def api_swap_action(self, swap_id: int, action: str):
        u = self.require_auth()
        if not u:
            return

        conn = get_db()
        try:
            swap = fetch_one(conn, f"SELECT * FROM swaps WHERE id={PH}", (swap_id,))
            if not swap:
                return self.send_error_json("Swap not found", 404)
            if swap["user_a"] != u["id"] and swap["user_b"] != u["id"]:
                return self.send_error_json("Not your swap", 403)

            if action == "accept":
                if swap["status"] != "proposed":
                    return self.send_error_json("This swap is not in 'proposed' state")
                if swap["user_b"] != u["id"]:
                    return self.send_error_json("Only the recipient can accept")

                # Generate swap code — ensure uniqueness
                existing_codes = {r["swap_code"] for r in
                    fetch_all(conn, "SELECT swap_code FROM swaps WHERE swap_code IS NOT NULL")}
                code = make_swap_code()
                while code in existing_codes:
                    code = make_swap_code()

                if USE_PG:
                    run_sql(conn,
                        "UPDATE swaps SET status='accepted', swap_code=%s, accepted_at=NOW() WHERE id=%s",
                        (code, swap_id))
                else:
                    run_sql(conn,
                        "UPDATE swaps SET status='accepted', swap_code=?, accepted_at=CURRENT_TIMESTAMP WHERE id=?",
                        (code, swap_id))
                conn.commit()

            elif action == "complete":
                if swap["status"] != "accepted":
                    return self.send_error_json("Swap must be accepted before marking complete")

                # Update both collections
                a_gives = json.loads(swap["a_gives"])
                b_gives = json.loads(swap["b_gives"])

                # User A gives stickers to B: reduce A's qty, add to B
                for num in a_gives:
                    self._transfer_sticker(conn, swap["user_a"], swap["user_b"], num)

                # User B gives stickers to A: reduce B's qty, add to A
                for num in b_gives:
                    self._transfer_sticker(conn, swap["user_b"], swap["user_a"], num)

                if USE_PG:
                    run_sql(conn,
                        "UPDATE swaps SET status='done', completed_at=NOW() WHERE id=%s",
                        (swap_id,))
                else:
                    run_sql(conn,
                        "UPDATE swaps SET status='done', completed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (swap_id,))
                conn.commit()

            elif action == "cancel":
                if swap["status"] in ("done",):
                    return self.send_error_json("Cannot cancel a completed swap")
                run_sql(conn, f"UPDATE swaps SET status='cancelled' WHERE id={PH}", (swap_id,))
                conn.commit()

            swap = fetch_one(conn, f"SELECT * FROM swaps WHERE id={PH}", (swap_id,))
            swap = enrich_swap(conn, swap, u["id"])
        finally:
            conn.close()
        self.send_json(swap)

    def _transfer_sticker(self, conn, from_user: int, to_user: int, number: str):
        """Reduce qty by 1 for giver; remove if hits 0. Add to receiver's collection."""
        # Giver: decrement
        run_sql(conn,
            f"UPDATE stickers SET quantity = quantity - 1 WHERE user_id={PH} AND number={PH}",
            (from_user, number))
        run_sql(conn,
            f"DELETE FROM stickers WHERE user_id={PH} AND number={PH} AND quantity <= 0",
            (from_user, number))
        # Receiver: upsert
        if USE_PG:
            run_sql(conn, """
                INSERT INTO stickers (user_id, number, quantity) VALUES (%s,%s,1)
                ON CONFLICT (user_id, number)
                DO UPDATE SET quantity = stickers.quantity + 1
            """, (to_user, number))
        else:
            run_sql(conn, """
                INSERT INTO stickers (user_id, number, quantity) VALUES (?,?,1)
                ON CONFLICT(user_id, number)
                DO UPDATE SET quantity = quantity + 1
            """, (to_user, number))

    # ── Admin ─────────────────────────────────
    def _check_admin(self) -> bool:
        b = self.read_body()
        if b.get("password") == ADMIN_PASSWORD:
            return True
        self.send_error_json("Wrong admin password", 403)
        return False

    def admin_page(self):
        self.serve_static("admin.html", "text/html")

    def api_admin_generate(self):
        b = self.read_body()
        if b.get("password") != ADMIN_PASSWORD:
            return self.send_error_json("Wrong admin password", 403)
        count = min(int(b.get("count", 10)), 100)
        codes = generate_codes(count)
        self.send_json({"codes": codes})

    def api_list_codes(self):
        pw = self.headers.get("X-Admin-Password", "")
        if pw != ADMIN_PASSWORD:
            return self.send_error_json("Wrong admin password", 403)
        conn = get_db()
        try:
            rows = fetch_all(conn,
                "SELECT code, used_by FROM invite_codes ORDER BY code")
        finally:
            conn.close()
        self.send_json([{"code": r["code"], "used": r["used_by"] is not None} for r in rows])


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────
def cmd_generate(n: int):
    init_db()
    codes = generate_codes(n)
    print(f"\n✅  Generated {len(codes)} invite codes:\n")
    for i, code in enumerate(codes, 1):
        print(f"  {i:>3}.  {code}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invite_codes.txt")
    with open(out, "a") as f:
        f.write("\n".join(codes) + "\n")
    print(f"\n  Saved to: {out}\n")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_generate(n)
        return

    init_db()
    print(f"\n⚽  FIFA 2026 Sticker Exchange")
    print(f"    http://localhost:{PORT}")
    print(f"    Database: {'PostgreSQL' if USE_PG else DB_PATH}")
    print(f"    Press Ctrl+C to stop\n")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")

if __name__ == "__main__":
    main()
