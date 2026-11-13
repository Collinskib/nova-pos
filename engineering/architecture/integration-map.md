# Integration Map

## External services

| Service | Used by | How | Secret |
|---|---|---|---|
| Supabase PostgREST | `cloud_api.py`, `web/app.html` | `pg()` (service role) / `supabase-js` (anon) | service key `.env`; anon `web/config.js` |
| Supabase GoTrue | `cloud_api.py`, `web/app.html` | `/auth/v1/user`, `/auth/v1/token`, `/auth/v1/admin/users`, OAuth | service key / anon |
| Wikimedia Commons API | hub `/api/image-search`, `localize_image` | outbound image search + thumbnail caching to `static/imgcache` | none |
| Render | hosts `cloud_api.py` | `CONF.api = https://shujaapos.onrender.com` | env on host |
| Vercel | hosts `web/` | `web/vercel.json` | — |
| Google OAuth | `web/app.html` sign-in | `signInWithOAuth({provider:"google"})` via Supabase | `client_secret_*.json` (local, **committed in git history** — rotation TODO) |

## Internal APIs

| Producer → Consumer | Contract |
|---|---|
| mobile → hub | `X-Device-Key` REST `/api/v1/*` (JSON) |
| hub → cloud_api | `X-Hub-Key` REST `/api/v1/sync/*` + `/api/web/*` |
| web → cloud_api | `Authorization: Bearer <user JWT>` `/api/web/*`, `/api/onboarding`, `/api/branches*` |
| web → PostgREST | anon reads, RLS-scoped |
| hub UI → hub | cookie session `/api/*` |

## Env contract (`.env`)

`POS_DB`, `POS_HOST`, `POS_PORT`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`, `CLOUD_API_URL`, `CLOUD_API_PORT`, `CLOUD_API_KEY`, `CLOUD_BUSINESS_ID`, `CLOUD_BRANCH_ID`, `CLOUD_DEVICE_ID`, `POS_AUTOSYNC`, `SUPABASE_ACCESS_TOKEN`, optional `POS_DEV_SHOTS` (dev screenshot login).
