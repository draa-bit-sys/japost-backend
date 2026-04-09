from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional, List
import os, shutil, secrets, uuid
from datetime import datetime
from pathlib import Path
import psycopg2
import psycopg2.extras

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
    return credentials

# ── Database PostgreSQL Setup ──
DATABASE_URL = os.getenv("DATABASE_URL")

class DBWrapper:
    """
    Wrapper jenius biar kodingan SQLite lama lu tetep jalan di Postgres
    tanpa perlu rombak Endpoint logic sama sekali.
    """
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # 1. Postgres pake %s, SQLite pake ?
        query = query.replace("?", "%s")
        # 2. Convert syntax ID dari gaya SQLite ke gaya Postgres
        query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        
        cur.execute(query, params or ())
        return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def get_db():
    if not DATABASE_URL:
        print("⚠️ ERROR: DATABASE_URL belom diset ngab di Variables Railway!")
        raise Exception("Database belom dikonek!")
    
    # Setup koneksi ke Postgres
    conn = psycopg2.connect(DATABASE_URL)
    wrapper = DBWrapper(conn)
    
    # Init Table (dijalankan pas tiap koneksi dapet, aman karena IF NOT EXISTS)
    wrapper.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            nama_item TEXT NOT NULL,
            kategori TEXT NOT NULL,
            deskripsi TEXT,
            stok INTEGER NOT NULL,
            harga INTEGER NOT NULL,
            gambar TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    wrapper.commit()

    try:
        yield wrapper
    finally:
        wrapper.close()

# ── Endpoints ──

@app.post("/api/items")
async def submit_item(
    itemName: str = Form(...),
    itemCategory: str = Form(...),
    itemDescription: str = Form(""),
    stok: int = Form(...),
    harga: int = Form(...),
    images: List[UploadFile] = File([]),
    db: DBWrapper = Depends(get_db)
):
    saved = []
    for img in images:
        if not img.filename: continue
        ext = img.filename.split('.')[-1]
        fname = f"{uuid.uuid4().hex}.{ext}"
        path = UPLOAD_DIR / fname
        with path.open("wb") as buffer:
            shutil.copyfileobj(img.file, buffer)
        saved.append(f"/static/uploads/{fname}")
    
    item_id = uuid.uuid4().hex[:8]
    now = datetime.now().isoformat()
    
    db.execute(
        """INSERT INTO items 
           (id, nama_item, kategori, deskripsi, stok, harga, gambar, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", # Di Postgres langsung pake %s, soalnya ini DBWrapper nerjemahin manual
        (item_id, itemName, itemCategory, itemDescription, stok, harga, "|".join(saved), now)
    )
    db.commit()
    return {"ok": True, "id": item_id}


@app.get("/api/items")
def list_items(status: Optional[str] = None, db: DBWrapper = Depends(get_db), _: str = Depends(require_auth)):
    if status:
        rows = db.execute("SELECT * FROM items WHERE status=%s ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM items ORDER BY created_at DESC").fetchall()
    
    res = []
    for r in rows:
        d = dict(r)
        d["gambar"] = [g for g in (d["gambar"] or "").split("|") if g]
        res.append(d)
    return res


@app.patch("/api/items/{item_id}/status")
def update_status(item_id: str, payload: dict, db: DBWrapper = Depends(get_db), _: str = Depends(require_auth)):
    new_status = payload.get("status")
    if new_status not in ["pending", "aktif", "ditolak"]:
        raise HTTPException(400, "Status nggak valid")
    db.execute("UPDATE items SET status=%s WHERE id=%s", (new_status, item_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str, db: DBWrapper = Depends(get_db), _: str = Depends(require_auth)):
    row = db.execute("SELECT gambar FROM items WHERE id=%s", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Item nggak ditemukan")
    for path in (row["gambar"] or "").split("|"):
        if path:
            full = BASE_DIR / path.lstrip("/")
            if full.exists():
                full.unlink()
    db.execute("DELETE FROM items WHERE id=%s", (item_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/stats")
def stats(db: DBWrapper = Depends(get_db), _: str = Depends(require_auth)):
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
    return HTMLResponse((BASE_DIR / "templates" / "post.html").read_text())