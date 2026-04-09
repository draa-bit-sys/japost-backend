# Japost Backend

## Struktur File
```
japost/
├── main.py              ← FastAPI app
├── requirements.txt
├── Procfile             ← untuk Railway/Render
├── templates/
│   └── dashboard.html
└── static/
    └── uploads/         ← gambar yang diupload
```

## Cara Deploy ke Railway

1. Buat akun di https://railway.app
2. New Project → Deploy from GitHub repo
3. Upload semua file ini ke GitHub dulu
4. Set environment variables di Railway:
   - `DASHBOARD_USER` = username dashboard kamu
   - `DASHBOARD_PASS` = password dashboard kamu
5. Railway otomatis detect Procfile dan deploy

## Cara Deploy ke Render

1. Buat akun di https://render.com
2. New → Web Service → connect GitHub repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Set environment variables:
   - `DASHBOARD_USER` = username dashboard kamu
   - `DASHBOARD_PASS` = password dashboard kamu

## Akses Dashboard

Buka: `https://domain-kamu.railway.app/dashboard`
Browser akan minta username & password (HTTP Basic Auth)

## Update form post.html

Ganti `action` di form kamu:
```html
<form action="https://domain-kamu.railway.app/api/items" method="post" enctype="multipart/form-data">
```

## API Endpoints

| Method | URL | Keterangan |
|--------|-----|------------|
| POST | /api/items | Submit item baru (dari form) |
| GET | /api/items | List semua item (butuh auth) |
| GET | /api/items?status=pending | Filter by status |
| PATCH | /api/items/{id}/status | Ubah status |
| DELETE | /api/items/{id} | Hapus item |
| GET | /api/stats | Statistik ringkas |
| GET | /dashboard | Halaman dashboard |
| GET | /docs | API docs (Swagger) |
