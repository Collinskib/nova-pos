# Deployment (BUILD.md §4.1, §15)

## Processes

| Service | File | Port | Env required |
|---|---|---|---|
| Hub (POS + LAN sync API) | `app.py` | 5050 | `.env` |
| Cloud API (Supabase bridge) | `cloud_api.py` | 5060 | `.env` |

## Production serving (do not use Flask dev server)

```bash
uv run --with flask --with waitress waitress-serve --listen=127.0.0.1:5050 app:app
uv run --with flask --with waitress waitress-serve --listen=127.0.0.1:5060 cloud_api:app
```

## systemd (Linux hub)

```ini
[Unit]
Description=Nova POS hub
After=network.target
[Service]
WorkingDirectory=/opt/pos-system
EnvironmentFile=/opt/pos-system/.env
ExecStart=/usr/bin/env python3 -m waitress --listen=0.0.0.0:5050 app:app
Restart=always
[Install]
WantedBy=multi-user.target
```

Bind `0.0.0.0` on the hub so LAN devices can reach it; keep the cloud API
behind TLS (Caddy/nginx reverse proxy or the Supabase Edge runtime).

## Security checklist (§4.3, §15)

- `SUPABASE_SERVICE_ROLE_KEY` lives only in `.env` on the server — never in
  JS, mobile builds, or git (`.env` is gitignored).
- Rotate `CLOUD_API_KEY` periodically; use a real secret manager at scale.
- LAN: prefer HTTPS via local CA/Caddy; at minimum the device-key auth
  already prevents unauthenticated sync.
- Backups: `/api/admin/backup` (hub) + Supabase PITR on paid plans.
- RLS stays enabled on all tenant tables — writes go through this API.
