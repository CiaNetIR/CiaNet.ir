# CiaNet Web Panel

Next.js + shadcn/ui frontend for the CiaNet selfbot management panel.

## Quick Start

```bash
# Install dependencies
npm install

# Dev mode (proxy /api/* to backend on port 8000)
npm run dev

# Production build
npm run build && npm start
```

## Pages

| Route | Description |
|-------|-------------|
| `/login` | Login (OWNER only) |
| `/dashboard` | Stats overview |
| `/users` | User management |
| `/accounts` | Selfbot management |
| `/finance` | Payments & MRR |
| `/tickets` | Support tickets |
| `/audit` | Audit log |
| `/version` | Update & rollback |
| `/tools` | api_id/api_hash management |
| `/settings` | System settings |

## API

The frontend proxies `/api/*` to FastAPI backend on `http://127.0.0.1:8000`.

To run the backend:
```bash
cd /opt/cianet
python3 -m uvicorn web_panel:app --host 127.0.0.1 --port 8000
```

Or use the systemd service:
```bash
sudo bash install_panel.sh
```

## Auth

Login uses `PANEL_ADMIN_USER` / `PANEL_ADMIN_PASS_HASH` env vars (bcrypt hash).
Session cookie is set with 8-hour TTL.
