# Responsive frontend

The attached ZIP is the source project. The Python backend is unchanged.

## Design contract

Local reference: the ZIP's existing dark interface and vanilla HTML/CSS/JS stack. Audience: merchants checking receipts at the counter. Primary action: upload and analyse a screenshot, visible in the first desktop screen. Direction: quiet charcoal dashboard, mint actions, amber review indicators and coral warnings. Distinctive detail: a receipt illustration and numbered upload/report workflow, with compact sidebar navigation.

Targets: **390x844**, **768x1024**, **1440x900**; also check 320px width and long content. No external fonts, images, icon services or framework dependencies. Keyboard focus, text status labels, reduced motion and 44px action targets are required.

| State | Feedback and recovery |
|---|---|
| Empty | Upload prompt and report placeholder; browse, drop or capture a screenshot. |
| Loading | Locked input controls, indeterminate indicator, elapsed timer; cancel waiting. |
| Error | Specific validation/server/network message; replace file or retry. |
| Partial | Missing checks explicitly marked unavailable; verify through bank records. |
| Success | Verdict, reasons, checks, transaction ID and OCR; save report or start another scan. |
| Permission | Native camera/file chooser owns device permission; dismiss and use Browse files as fallback. No bank, clipboard or notification permissions are requested. |

Changed files: `static/index.html`, `static/style.css`, `static/script.js`. Complete source files are included. Existing endpoint contracts: `/api/analyze`, `/api/history?limit=100`, `/api/stats`, `/api/health`.

Run the Python server as described in `README.md`, then open `http://127.0.0.1:8000`. Do not open the HTML file directly; it requires same-origin backend routes. Scanner, history and guide navigation use URL hashes and support browser back/forward.

History and statistics come from the server. Search/filter/export operate on the latest 100 history records. Report downloads include the current complete JSON response and can contain personal payment text. No fake metrics or samples are included in the shipped interface.

The UI does not claim real payment verification or a three-second guarantee. Cancellation stops waiting in the browser; the backend may still finish and store the request. Mobile camera support depends on the browser; native camera permission and actual hardware must be tested on a phone.

## Verification

The 36 assertions in `tests/browser/checks.cjs` passed in Chrome at each of 390×844, 768×1024 and 1440×900, for 108 passing assertions. They use the explicit synthetic API fixtures in `tests/browser/fixtures.cjs`; these files are never loaded by the application. Screenshots and an evidence record are in `frontend-evidence/`. Browser tests covered validation, locked controls, cancellation, server errors, all verdicts, missing-check coverage, inert OCR markup, navigation, search, filters, export triggers and offline recovery.

An additional keyboard Tab check confirmed visible focus. All 81 checked visible desktop text nodes met the applicable contrast threshold. The reduced-motion rule was activated and confirmed to remove animation. These are targeted accessibility checks, not a full screen-reader or real-phone audit.

The Python regression suite stalled at the first TestClient request in this environment and was interrupted. No backend-test pass or live browser-to-backend verification is claimed. The Python files and existing dependencies are unchanged from the ZIP.

Optional browser runner (requires Node.js):

```sh
npm install
npx playwright install chromium
npm run test:frontend
```

The reusable runner runs the same assertion function against a temporary local static server with fixture responses and writes screenshots to `frontend-evidence/local-run/`. The assertion function was executed through the available Chrome tools here because direct Playwright browser launch was unavailable. The runner itself should be verified in your local environment.
