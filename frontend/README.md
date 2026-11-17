# Gate Console — web & mobile

One React codebase for the campus security console: the website, an installable web app, and the
Capacitor Android / iOS app. It shows what cameras and guards observed, how it links to the registry,
and the movement record. It never opens or closes a barrier and makes no access decision.

Stack: React 19, TypeScript, Vite 6, Tailwind CSS 3, TanStack Query 5, React Router 7 (hash routing),
lucide icons, Capacitor 7.

## Run the website

```bash
# backend first (repo root): PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --port 8000
npm install
npm run dev          # http://localhost:5173, proxies /api to BACKEND_URL (default http://127.0.0.1:8000)
npm run typecheck
npm run build        # dist/
npm run preview      # serves dist/ on :4173 with the same /api proxy
```

To host the build elsewhere, serve `dist/` and forward `/api/*` to the backend with the `/api` prefix
stripped (as `vite.config.ts` does), or build with `VITE_API_BASE_URL=https://console.example/api-root`
and add the site's origin to the backend's `CORS_ALLOW_ORIGINS`.

Phones can open the website directly (`npm run dev -- --host`, backend reachable from the LAN) and add
it to the home screen; the manifest and icons are in `public/`.

## Build the Android app

Needs JDK 21 and the Android SDK.

```bash
JAVA_HOME=~/.local/temurin-21 ANDROID_HOME=~/Android/Sdk npm run android:build
# -> android/app/build/outputs/apk/debug/app-debug.apk
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
npm run android:open   # or open the project in Android Studio (release builds, signing)
```

`npm run cap:sync` rebuilds the web assets and copies them into the native project; run it after any
frontend change before building the app.

The app has no proxy. On first launch, open **Connection settings** on the sign-in screen and enter the
backend address, e.g. `http://192.168.1.20:8000` (run uvicorn with `--host 0.0.0.0`), or
`http://10.0.2.2:8000` from the Android emulator. **Test & save** checks `/health` and stores it on
the device. The backend's default `CORS_ALLOW_ORIGINS` already allows the app's origins
(`https://localhost`, `capacitor://localhost`). `capacitor.config.ts` allows plain HTTP and mixed
content for LAN development; use HTTPS in production and turn those off.

## Build the iOS app (on a Mac)

```bash
npm install @capacitor/ios@^7 && npx cap add ios && npm run cap:sync && npx cap open ios
```

## Layout

```
src/
  api/          client.ts (fetch, base URL, errors), types.ts (mirrors backend schemas), queries.ts (TanStack Query hooks)
  app/          AppShell (sidebar / top bar / tab bar), nav, router
  auth/         session (sessionStorage on the web, app-private storage on phones), role refresh via /auth/me
  feed/         SSE parser, live feed with polling fallback, shared context
  components/   ui/ (buttons, forms, dialog / bottom sheet, toasts), feed/, forms/, charts/, movement/, registry/, delivery/
  pages/        one file per screen
  lib/          formatting, theme, platform & server URL, Android back button, CSV
```

## Pages

| Route | Page |
| --- | --- |
| `#/` | Overview: vehicles on campus, entries / exits, plates to review, unlinked on campus, delivery flags, activity chart, system health |
| `#/feed` | Live plate feed (guard console): stat tiles, gate filter (All / Gate 1–3), chips All / Linked / Unlinked / Review, "Plates read · LIVE" list (plate, ENTERED / LEFT, gate · time, owner type + masked SID / department, LINKED / UNLINKED / NEEDS REVIEW) and the plate detail panel (camera frame + OCR read, registry explanation, owner / reference / residence, close-match confirmation, direction confirmation, **Link this vehicle**: belongs to Student / Faculty / Staff + SID or department, **Mark as visitor**, audit trail), "+ Add vehicle entry", the latest **Delivery screening** panel, and an ADMIN-only **Simulate a plate** demo button. `?view=cards` keeps the earlier card grid |
| `#/inside`, `#/logs` | Who is on campus now; entry / exit movement log with corrections |
| `#/deliveries` | Delivery screening list: verdict chips (Alert / Review / Allow), awaiting-guard filter, order-ID search ("the rider's order ID opens the item list"), **Upload invoice**, the local intake URL |
| `#/deliveries/<order id>` | Invoice image, each line with qty, amount, category · reason code and ALLOW / REVIEW / ALERT, totals check ("Lines add up: 675.00 + 25.00 = 700.00"), chat reply, source, guard decision Cleared / Hold / Escalate with note and append-only history |
| `#/alerts` | Everything needing attention (plates to review, unlinked plates, flagged delivery lines) with severity, linking to the plate or the delivery |
| `#/vehicles`, `#/owners` | Registry; link a plate to a Student (SID), Faculty or Staff owner |
| `#/gates`, `#/users`, `#/system`, `#/settings` | Gates & lanes, accounts (ADMIN), system status incl. the WhatsApp provider and intake URL, settings |

Riders without the console send invoices from a phone at the backend's public page
`http://<server-ip>:8000/intake` (WhatsApp Business API is not connected yet; the provider is swappable).

## UI rules carried over from the guard dashboard

- Neutral palette for plates: no green/red pass/stop semantics. "Unlinked" is plain slate; BLACKLISTED
  stands out only because an administrator recorded it. Invoice lines are the one exception: their
  ALLOW / REVIEW / ALERT policy verdicts use green / amber / red as on the slides, and the page always
  states that the guard decides and nothing is blocked automatically.
- Registry status is shown exactly as recorded. Fuzzy registry candidates are never applied automatically.
- Direction comes only from a declared lane role, a declared zone order, or a guard's confirmation.
- Corrections, links and resolutions are new records; nothing is edited in place or deleted.

Icons and splash screens are generated from the SVGs in `public/` and `assets/`: `scripts/generate-icons.sh`.
