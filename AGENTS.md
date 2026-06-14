# RTLS Repository Guidance

## Scope

These instructions apply to the entire repository.

## Architecture

- `server.py`: HTTP routing, authorization and monitoring domain state.
- `auth.py`: SQLite users, sessions, roles and guardian links.
- `notifications.py`: asynchronous signed n8n-compatible webhooks.
- `disaster_rag.py`: local source-grounded disaster document retrieval.
- `public_data.py`: external public alert adapters and polling.
- `static/`: dependency-light HTML, CSS and JavaScript frontends.
- `tests/`: Python domain and adapter tests.
- `e2e/`: Playwright browser and visual regression tests.

## Change Rules

- Preserve the Python standard-library-only runtime unless a dependency is clearly justified.
- Never commit `.env`, API keys, passwords, precise user locations or production database files.
- Treat location, route, age, gender and guardian relationships as sensitive data.
- Enforce role and regional authorization on the server, not only in the UI.
- External notifications must be asynchronous and must not block location or SOS requests.
- Disaster guidance must display its source. Do not present generated text as official guidance.
- Keep map data attribution and third-party licenses visible.
- Work with existing uncommitted changes and do not revert unrelated edits.

## Verification

Run after backend or shared-domain changes:

```bash
python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/rtls-pycache python3 -m py_compile \
  auth.py disaster_rag.py geocoding.py notifications.py public_data.py regions.py server.py
```

Run after frontend or layout changes when Node.js is installed:

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

Use `npm run test:e2e:update` only when an intentional design change requires new
visual baselines. Review the generated image diff before accepting it.

## UI Regression Checklist

- Desktop and mobile layouts contain no horizontal overflow.
- The map fits inside its panel and does not create excessive empty space.
- Client detail actions remain readable and reachable by scrolling.
- Region and group filters remain usable.
- Modal dialogs fit within the viewport and can be closed with Escape.
- Korean text renders without clipping or overlap.

## Documentation

When behavior, roles, API settings or test counts change, update `README.md` and
the relevant Analysis, Conceptualization and Design documents.
