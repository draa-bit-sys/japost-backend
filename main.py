from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional, List
import sqlite3, os, shutil, secrets, uuid
from datetime import datetime
from pathlib import Path

app = FastAPI(title="Japost Itemku API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Dirs ──
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ── Auth ──
security = HTTPBasic()
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "japost123")

def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, DASHBOARD_USER)
    ok_pass = secrets.compare_digest(credentials.password, DASHBOARD_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login salah",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ── Database ──
DB_PATH = BASE_DIR / "japost.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id               TEXT PRIMARY KEY,
            nama_penjual     TEXT NOT NULL DEFAULT 'Anonim',
            kontak_penjual   TEXT NOT NULL DEFAULT '-',
            nama_item        TEXT NOT NULL,
            kategori         TEXT NOT NULL,
            deskripsi        TEXT,
            stok             INTEGER DEFAULT 0,
            harga            INTEGER DEFAULT 0,
            gambar           TEXT,
            status           TEXT DEFAULT 'pending',
            created_at       TEXT NOT NULL
        )
    """)
    # Migrasi untuk database lama
    for col, default in [("nama_penjual", "'Anonim'"), ("kontak_penjual", "'-'")]:
        try:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
        except:
            pass
    conn.commit()
    conn.close()

init_db()

# ── Helper ──
def row_to_dict(row):
    d = dict(row)
    d["gambar"] = d["gambar"].split("|") if d.get("gambar") else []
    return d

def row_to_public(row):
    d = row_to_dict(row)
    d.pop("kontak_penjual", None)
    return d

# ════════════════════════════════════
#  API ENDPOINTS
# ════════════════════════════════════

@app.post("/api/items", status_code=201)
async def submit_item(
    namaPenjual:     str              = Form(...),
    kontakPenjual:   str              = Form(...),
    itemName:        str              = Form(...),
    gamecategory:    str              = Form(...),
    itemDescription: str              = Form(""),
    stok:            int              = Form(0),
    value:           str              = Form("0"),
    gambar:          List[UploadFile] = File(default=[]),
    db: sqlite3.Connection = Depends(get_db)
):
    harga = int(value.replace(".", "").replace(",", "")) if value else 0

    saved = []
    for f in gambar:
        if f.filename:
            ext  = Path(f.filename).suffix
            name = f"{uuid.uuid4().hex}{ext}"
            dest = UPLOAD_DIR / name
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(f"/static/uploads/{name}")

    item_id = uuid.uuid4().hex[:12]
    now     = datetime.now().isoformat(timespec="seconds")

    db.execute(
        """INSERT INTO items
           (id, nama_penjual, kontak_penjual, nama_item, kategori, deskripsi, stok, harga, gambar, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (item_id, namaPenjual, kontakPenjual, itemName, gamecategory,
         itemDescription, stok, harga, "|".join(saved), now)
    )
    db.commit()
    return {"ok": True, "id": item_id}


# ── Public endpoints (tanpa auth) ──
@app.get("/api/public/items")
def public_items(
    kategori: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    if kategori:
        rows = db.execute(
            "SELECT * FROM items WHERE status='aktif' AND kategori LIKE ? ORDER BY created_at DESC",
            (f"%{kategori}%",)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM items WHERE status='aktif' ORDER BY created_at DESC"
        ).fetchall()
    return [row_to_public(r) for r in rows]


@app.get("/api/public/kategori")
def public_kategori(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        "SELECT DISTINCT kategori FROM items WHERE status='aktif' ORDER BY kategori"
    ).fetchall()
    return [r["kategori"] for r in rows]


# ── Admin endpoints (butuh auth) ──
@app.get("/api/items")
def list_items(
    status: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _: str = Depends(require_auth)
):
    if status:
        rows = db.execute("SELECT * FROM items WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM items ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


@app.get("/api/items/{item_id}")
def get_item(item_id: str, db: sqlite3.Connection = Depends(get_db), _: str = Depends(require_auth)):
    row = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Item tidak ditemukan")
    return row_to_dict(row)


@app.patch("/api/items/{item_id}/status")
def update_status(
    item_id: str,
    body: dict,
    db: sqlite3.Connection = Depends(get_db),
    _: str = Depends(require_auth)
):
    new_status = body.get("status")
    if new_status not in ("pending", "aktif", "ditolak"):
        raise HTTPException(400, "Status tidak valid")
    db.execute("UPDATE items SET status=? WHERE id=?", (new_status, item_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str, db: sqlite3.Connection = Depends(get_db), _: str = Depends(require_auth)):
    row = db.execute("SELECT gambar FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Item tidak ditemukan")
    for path in (row["gambar"] or "").split("|"):
        if path:
            full = BASE_DIR / path.lstrip("/")
            if full.exists():
                full.unlink()
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/stats")
def stats(db: sqlite3.Connection = Depends(get_db), _: str = Depends(require_auth)):
    total   = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM items WHERE status='pending'").fetchone()[0]
    aktif   = db.execute("SELECT COUNT(*) FROM items WHERE status='aktif'").fetchone()[0]
    ditolak = db.execute("SELECT COUNT(*) FROM items WHERE status='ditolak'").fetchone()[0]
    return {"total": total, "pending": pending, "aktif": aktif, "ditolak": ditolak}


# ── Serve pages ──
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse((BASE_DIR / "templates" / "dashboard.html").read_text())

@app.get("/katalog", response_class=HTMLResponse)
def katalog():
    return HTMLResponse((BASE_DIR / "templates" / "katalog.html").read_text())

@app.get("/konfirmasi", response_class=HTMLResponse)
def konfirmasi():
    return HTMLResponse((BASE_DIR / "templates" / "konfirmasi.html").read_text())

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("<p>API aktif. Buka <a href='/dashboard'>dashboard</a>, <a href='/katalog'>katalog</a>, atau <a href='/docs'>docs</a>.</p>")
    
