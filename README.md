# ⚽ FIFA 2026 Sticker Exchange App

A web app for your son and his friends to register, track sticker collections, and coordinate physical swaps.

---

## ✅ Requirements

- **Python 3.8+** (no extra libraries for local / SQLite mode)
- `psycopg2-binary` only needed for Railway PostgreSQL deployment (`pip install psycopg2-binary`)

---

## 🚀 Deploy to Railway (free, recommended)

### Step 1 — Put files on GitHub

1. Go to [github.com](https://github.com) → sign in (or create a free account)
2. Click **New repository** → name it `sticker-exchange` → **Create**
3. On the next screen click **"uploading an existing file"**
4. Upload all files keeping the folder structure:
   ```
   server.py
   requirements.txt
   Procfile
   railway.json
   public/index.html
   public/app.js
   public/style.css
   ```
5. Click **Commit changes**

### Step 2 — Create the app on Railway

1. Go to [railway.app](https://railway.app) → sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo** → select `sticker-exchange`
3. Railway detects Python automatically and deploys

### Step 3 — Add a PostgreSQL database (persistent!)

1. Inside your Railway project, click **+ New** → **Database** → **PostgreSQL**
2. Click on the PostgreSQL service → **Variables** tab
3. Copy the value of `DATABASE_URL`
4. Click on your `sticker-exchange` service → **Variables** tab
5. Add a variable: `DATABASE_URL` = *(paste the value)*
6. Railway will redeploy automatically — your data now persists forever

### Step 4 — Generate invite codes

Once deployed, open a terminal on Railway (or locally):

```bash
# Locally (generates codes into the SQLite DB):
python3 server.py generate 20

# Or set DATABASE_URL first to generate into the PostgreSQL DB:
DATABASE_URL="your-url-here" python3 server.py generate 20
```

Codes are printed to the console and saved to `invite_codes.txt`.
Distribute one code per friend — each code can only be used once.

### Step 5 — Share the URL

Railway gives you a public URL like `https://sticker-exchange.up.railway.app`.
Share it with the group!

---

## 💻 Run locally (for testing)

```bash
python3 server.py
# → http://localhost:5000

# Generate codes first:
python3 server.py generate 15
```

---

## 🔄 How swaps work

| Step | What happens |
|------|-------------|
| 1. System suggests | App matches who can swap with whom based on duplicates |
| 2. Propose | User A clicks "Propose Swap" — sends offer to User B |
| 3. Accept | User B reviews the sticker list and clicks "Accept" |
| 4. Swap code | A unique code (e.g. `SW-K3MP`) is generated automatically |
| 5. Prepare envelopes | Both friends put their stickers in an envelope/pouch labeled with the code |
| 6. Physical exchange | Friends hand each other their envelopes |
| 7. Confirm done | Either friend clicks "Mark as done" — both collections update automatically |

---

## 📁 File structure

```
sticker-exchange/
├── server.py           ← Full backend (Python stdlib + optional psycopg2)
├── requirements.txt    ← psycopg2-binary for PostgreSQL
├── Procfile            ← Railway/Heroku start command
├── railway.json        ← Railway config
├── public/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── stickers.db         ← SQLite DB (auto-created, local only)
└── invite_codes.txt    ← Generated codes (auto-created)
```

---

## 🔑 Invite codes

- Run `python3 server.py generate N` to generate N codes
- Each code works for one registration only
- Once used, the code is permanently marked as used
- Generate more any time by running the command again
