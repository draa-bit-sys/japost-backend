from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, status, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional, List
import os, shutil, secrets, uuid
from datetime import datetime
from pathlib import Path
import pg8000.dbapi

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

# Parsing manual url postgresql://user:pass@host:port/dbname 
def parse_db_url(url):
    if not url: return {}
    url = url.replace("postgresql://", "")
    user_pass, host_port_db = url.split("@")
    user, password = user_pass.split(":")
    host_port, database = host_port_db.split("/")
    host, port = host_port.split(":")
    
    # Hapus embel-embel query string dari Railway (misal: ?sslmode=disable)
    if "?" in database:
        database = database.split("?")[0]
        
    return {
        "user": user,
        "password": password,
        "host": host,
        "port": int(port),
        "database": database
    }

class DBWrapper:
    """
    Wrapper jenius pg8000 (100% Python). Anti error libpq.so.5!
    """
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        cur = self.conn.cursor()
        
        # pg8000 pakenya %s cuy sama kek psycopg2
        query = query.replace("?", "%s")
        query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        
        cur.execute(query, params or ())
        
        # Bikin helper fetchone sama fetchall biar sama persis kek sqlite3
        class CursorHelper:
            def __init__(self, cursor):
                self.cur = cursor
                
            def fetchone(self):
                row = self.cur.fetchone()
                if not row: return None
                cols = [desc[0] for desc in self.cur.description]
                return dict(zip(cols, row))
                
            def fetchall(self):
                rows = self.cur.fetchall()
                cols = [desc[0] for desc in self.cur.description]
                return [dict(zip(cols, row)) for row in rows]
                
        return CursorHelper(cur)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def get_db():
    if not DATABASE_URL:
        print("⚠️ ERROR: DATABASE_URL belom diset ngab di Variables Railway!")
        raise Exception("Database belom dikonek!")
    
    db_args = parse_db_url(DATABASE_URL)
    conn = pg8000.dbapi.connect(**db_args)
    wrapper = DBWrapper(conn)
    
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
async def submit_item(request: Request, db: DBWrapper = Depends(get_db)):
    """
    FIX: Pake Request ambil mentahan Form, biar FastAPI ga cerewet (bye 422).
    """
    form = await request.form()
    
    # Ambil data pake .get() biar kalo kosong dapet default string
    itemName = form.get("itemName", "")
    itemCategory = form.get("itemCategory", "")
    itemDescription = form.get("itemDescription", "")
    stok = form.get("stok", "0")
    harga = form.get("harga", "0")
    
    # Validasi custom manual
    if not itemName or not itemCategory:
        raise HTTPException(status_code=400, detail="Nama dan kategori wajib diisi ngab!")
    
    # Parsing angka super aman (kalo diketik huruf tetep tembus jadi 0)
    try:
        stok_int = int(stok) if stok else 0
    except Exception:
        stok_int = 0
        
    try:
        harga_int = int(harga) if harga else 0
    except Exception:
        harga_int = 0

    saved = []
    # Ambil semua file "images"
    images = form.getlist("images")
    
    for img in images:
        # Cek apakah img beneran objek file (bukan empty string dari frontend)
        if hasattr(img, "filename") and img.filename:
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
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
        (item_id, itemName, itemCategory, itemDescription, stok_int, harga_int, "|".join(saved), now)
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
    total_row   = db.execute("SELECT COUNT(*) FROM items").cur.fetchone()
    pending_row = db.execute("SELECT COUNT(*) FROM items WHERE status='pending'").cur.fetchone()
    aktif_row   = db.execute("SELECT COUNT(*) FROM items WHERE status='aktif'").cur.fetchone()
    ditolak_row = db.execute("SELECT COUNT(*) FROM items WHERE status='ditolak'").cur.fetchone()
    
    return {
        "total": total_row[0] if total_row else 0, 
        "pending": pending_row[0] if pending_row else 0, 
        "aktif": aktif_row[0] if aktif_row else 0, 
        "ditolak": ditolak_row[0] if ditolak_row else 0
    }


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
