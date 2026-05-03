# NYC Urban Violations — Dashboard (Python server)

A Python (Flask) port of the original Node/Express server. Same dashboard,
same endpoints, same data — only the runtime is different.

## Quick start

Requires **Python 3.9 or newer**. From this folder (`dashboard/server-py/`):

```bash
pip install -r requirements.txt
cp .env.example .env          # then edit .env to add the PG_URI credentials
python app.py
```

Then open **http://localhost:3000** in any modern browser.

## What's running

```
┌──────────────────┐   fetch /api/*    ┌──────────────────┐    SQL    ┌──────────────┐
│  index.html +    │ ────────────────► │ Flask server     │ ────────► │  Postgres    │
│  Plotly charts   │ ◄──────────────── │ (app.py)         │ ◄──────── │  (Supabase)  │
└──────────────────┘   JSON responses  └──────────────────┘           └──────────────┘
```

| Endpoint | Returns |
|---|---|
| `GET /api/overview` | Total counts + cross-borough volume |
| `GET /api/parking`  | Top violations, fine ladder, borough share, time-of-day, fine-sensitivity heatmap, precinct aggression, state-leakage, year trend |
| `GET /api/housing`  | Class severity, borough × class, ZIP hotspots, repeat-offender buildings, rent-impairing analysis, category mix |
| `GET /api/dob`      | Borough share, type frequency, top streets, status × borough, resolution lag, geo-clusters |
| `GET /api/combined` | Cross-dataset correlation matrix, DOB×HPD synergy, urban distress, slumlord index, multi-agency streets, revenue-vs-risk |
| `GET /api/health`   | Liveness probe |
| `POST /api/cache/clear` | Drop the in-memory cache |

Each `/api/*` response is cached for 5 minutes server-side. Filters are passed
as query params: `?borough=Bronx&period=Morning&class=C&status=Active`.

## File layout

```
server-py/
├─ app.py             # Flask app — routes, cache, static-file serving
├─ db.py              # Postgres connection pool + SQL runner
├─ queries.py         # SQL aggregations (one function per endpoint)
├─ requirements.txt   # Flask, psycopg2-binary, python-dotenv, flask-cors
├─ .env.example       # Template — copy to .env
└─ README.md
```

## Troubleshooting

- **`Missing PG_URI in .env`** — copy `.env.example` to `.env` and fill in credentials.
- **`psycopg2.OperationalError: SSL ... required`** — already handled (the pool sets `sslmode=require`); check the host/port in `PG_URI`.
- **Port 3000 already in use** — set `PORT=3001` (or any free port) in `.env`.
- **Want to see every SQL query the server runs?** Set `LOG_SQL=1` in `.env`.
