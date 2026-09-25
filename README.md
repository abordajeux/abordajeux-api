# À L'Abordajeux — Subscription API

FastAPI + SQLite service for anonymous, capacity-tracked event signups with double opt-in email
verification and a FIFO waiting list. Hosted on a Raspberry Pi behind a Cloudflare Tunnel; serves
the static site ([abordajeux.github.io](https://github.com/abordajeux/abordajeux.github.io)) via
CORS-restricted JSON endpoints.

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | none | container healthcheck |
| GET | `/schedule` | none, `Cache-Control: max-age=300` | the programme JSON **verbatim** — the same file that seeds the DB; the site's single source for the program |
| GET | `/activities` | none | capacity counts (confirmed / pending / waitlisted) |
| GET | `/activities/{id}` | none | one activity's counts |
| POST | `/activities/{id}/signup` | rate-limited 1/30s/IP (keyed on `CF-Connecting-IP`) | anonymous signup (≤ 10 participants, names ≤ 50 chars; waiting list capped at `max_participants`) |
| POST | `/verify` | none | double opt-in confirmation — token in the JSON body so it stays out of URL logs; POST-only so email link scanners can't auto-confirm (the static verify page issues the call) |
| POST | `/forms/contact` | rate-limited (same knob as signup) | contact-form intake — sanitized, emailed to `MAIL_CONTACT_EMAIL` with the submitter as `reply_to`; no DB |
| POST | `/forms/feedback` | rate-limited (same knob as signup) | event-feedback intake (event + message + two 0–5 ratings) — same sanitize-and-email flow |

## Deploy (Docker on the Pi)

Requires Docker + the compose plugin. Clone the repo, then:

```bash
mkdir -p data                   # first time only — must be owned by the operator (UID 1000)
cp .env.example .env
nano .env                       # fill in the secrets
docker compose build
docker compose up -d
docker compose logs -f          # verify startup
```

The container runs as `apiuser` (UID 1000, matching the default Pi user). If Docker creates
`data/` itself it will be root-owned and the app cannot write its SQLite file — hence the
manual `mkdir`.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `MAIL_API_KEY` | API key from the Resend account (mail sending is provider-agnostic in code) |
| `CORS_ORIGINS` | allowed origin, `https://abordajeux.github.io` — no wildcard |
| `DATABASE_PATH` | SQLite file path; keep under `/app/data` (bind-mounted) |
| `PROGRAMME_PATH` | programme JSON — served by `GET /schedule` and auto-seeded at startup; keep under `/app/data` |
| `MAIL_SENDER` | sender email for outgoing mail (must be on a Resend-verified domain) |
| `MAIL_CONTACT_EMAIL` | association inbox — quoted in signup emails and the recipient of form submissions |
| `RATE_LIMIT_SECONDS` | minimum seconds between POSTs (signup + form endpoints) per IP |
| `MAX_BODY_BYTES` | request-body cap (413 before parsing); 64 KB ≈ 10× the largest legit payload |
| `VERIFY_BASE_URL` | static site's verify page; the API appends `?token=…` |

### Verify the deployment

```bash
curl http://127.0.0.1:8000/health       # {"status":"ok"}
curl http://127.0.0.1:8000/activities   # {"activities":[...]}
```

The port is bound to `127.0.0.1` only — public exposure is the Cloudflare Tunnel's job
(`cloudflared` on the Pi host maps the tunnel hostname to `http://localhost:8000`).

### Traffic hardening model

No reverse-proxy container — the layers are: **Cloudflare** (public TLS, DDoS/bot filtering,
edge caching incl. `/schedule`), **slowapi** (per-IP POST rate limit, keyed on
`CF-Connecting-IP`), and an **in-app body cap** (`MAX_BODY_BYTES`, default 64 KB — rejects
oversized bodies with 413 before they are read or parsed; covers chunked requests too). A front
proxy (Caddy/nginx) becomes worth adding only when a second service lands on the Pi.

## Updating the programme (single source of truth)

The programme JSON (authored + versioned in the static repo) is deployed to the Pi's bind mount
and feeds **both** the website (`GET /schedule`) and the API's DB (startup seed) — the view and
the signups can never disagree:

```bash
scp presque-programme.json pi@<pi>:~/abordajeux-api/data/programme.json
docker compose restart          # startup re-seeds (idempotent upsert, never deletes)
```

A missing file is skipped quietly (first boot before any programme exists); a malformed file is
logged (`docker compose logs`) and `GET /schedule` returns `{"status": "schedule_invalid"}` —
the app stays up. Raising `max_participants` promotes confirmed waitlisted people on the next
purge run. Activities absent from the JSON are never deleted (manual DB access on the Pi for
removals). The seed CLI (`docker exec abordajeux_api python -m app.seed [path]`) remains for
explicit re-seeds; with no argument it reads `PROGRAMME_PATH`.

## Cron jobs (host crontab)

```cron
# hourly purge: delete >24h-unconfirmed signups, then promote + email the waiting list
0 * * * * docker exec abordajeux_api python -m app.purge

# daily backup of the bind-mounted SQLite file
30 3 * * * cp /home/pi/abordajeux-api/data/abordajeux.db /home/pi/backups/abordajeux-$(date +\%F).db
```

Promotion emails are at-least-once: a failed send is retried on the next hourly run (the seat is
kept either way).

## Form intake (`/forms/*`)

`POST /forms/contact` (`{subject, sender_email, message}`) and `POST /forms/feedback`
(`{event, sender_email, message, planning_rating, welcome_rating}`) relay site forms to the
association inbox (`MAIL_CONTACT_EMAIL`) with the submitter's address as `reply_to`. Nothing is
stored: validation (Pydantic bounds, `EmailStr`), control-character stripping (single-line fields
lose all C0/C1 chars — no email-header injection; messages keep newlines), then an HTML-escaped
fr-FR email body. The same `RATE_LIMIT_SECONDS` window applies per form endpoint and per IP.

## Operations

- **Logs:** `docker compose logs -f`
- **Re-deploy on code change:** `git pull && docker compose build && docker compose up -d`
  (the bind mount keeps `./data/abordajeux.db` across rebuilds)
- **Participant lists / cancellations:** host-side only (`sqlite3 data/abordajeux.db`) — the
  admin HTTP route was removed for security; cancellations are manual (delete the row; the next
  purge run promotes the queue accordingly)

## Development

Python 3.12 (venv or `uv`); gates:

```bash
ruff check .
mypy app
pytest
```

The pure core (`app/signups.py` — capacity enforcement, waiting-list derivation, promotion) is
unit-tested against in-memory SQLite; routes are tested with a stubbed mail sender; no test
touches the network.
