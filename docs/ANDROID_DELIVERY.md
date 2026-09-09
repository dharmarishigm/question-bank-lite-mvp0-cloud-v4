# Android additional client

## Architecture and scope

MeritIQra uses FastAPI, a shared role-authorized exam API, SQLite locally and PostgreSQL/Cloud SQL in production, GCS-backed sources, Vertex AI, and a vanilla HTML/JavaScript workspace. Public HTML pages and SEO routes are separate from the authenticated workspace. Capacitor 8 reuses that workspace and its existing SVG, KaTeX/mhchem, results, Performance Lab and IQraMentor rendering. Android does not duplicate scoring, exam snapshots, authorization or tutor business rules.

`mobile/` contains the Capacitor project, build script, native adapter and Android project. The build copies existing static assets into a packaged local app. Production APIs remain at `https://meritiqra.com`; the app does not load the marketing website as its shell. Backend additions are in `mobile_api.py`, `mobile_notifications.py` and migration `0006_mobile.py`. Browser behavior is preserved through native-only adapters. The public homepage shows authenticated display name and role through a private `/api/auth/me` lookup.

## Authentication and storage

Google sign-in opens the existing trusted web login in the system browser. A five-minute handoff requires explicit approval by that authenticated browser user. The app generates a random PKCE verifier held in Android Keystore-encrypted storage; the server stores its SHA-256 challenge and a hashed request identifier. A one-use atomic exchange issues the same server-managed 12-hour sessions as the web. The callback contains no access token. Role resolution remains entirely server-side. Without a verified callback, returning manually to the app still completes the approved exchange.

The native HTTP adapter stores session and CSRF cookies only in AES-GCM ciphertext protected by Android Keystore. Cookies never enter JavaScript, localStorage or plaintext SharedPreferences. Android backup and production cleartext transport are disabled. Capacitor bridge logging is disabled. Existing admin passwords, bootstrap secrets and production credentials are not included in the app.

## Exams and navigation

Student bottom navigation opens Home, Explore, My Exams, Performance and Profile; IQraMentor remains accessible outside protected assessments. Admin navigation exposes dashboard, exam operations, results and profile. Full desktop admin workflows remain available on the website. Native file selection uses Capacitor's system file chooser and the existing authenticated upload endpoints; private images and PDF pages pass through the native cookie adapter.

Answers are committed to encrypted local storage before network synchronization. Operations contain a UUID and timestamp and coalesce by session/question. The server's existing upsert makes retries idempotent. Network work runs independently of local persistence; acknowledgements remove only the matching operation, preserving a newer offline selection. A new authenticated owner clears previous local answer state. Closed/expired sessions reject late answers; the UI reports that limitation instead of claiming they were scored.

The server supplies session expiry, current time, immutable question order/version and saved answers. Resume and process recreation restore that session and last question index; timers are recalculated against server time. Starting a new assessment still requires server authorization. Submission waits for answer synchronization. Back navigation warns before leaving an active exam. Proctored sessions enable Android FLAG_SECURE; ordinary learning keeps normal capture behavior. Background events are audit signals, not automatic cheating verdicts. iPhone browsers without a Fullscreen API use labelled focus mode with server timing and scoring.

## PWA and notifications

The manifest is optional for the existing website. The service worker caches only same-origin static CSS, JavaScript, SVG and font assets. It excludes navigation HTML, authentication, APIs, questions, results and uploads. Network-first assets avoid pinning old workspace code.

FCM registration is explicitly opt-in in the Android profile. The backend stores preferences and device ownership; disabling removes registrations. Explicit assessment submission can send a generic result-ready alert through FCM, without scores, names or question data. Duplicate submissions do not send another alert. Invalid registrations are removed. Delivery failures never affect submission. Delivery is best effort, not a durable notification outbox; automatic expiration does not currently send a notification.

## Configuration and builds

Use Node 22 or newer, Java 21, Android SDK platform 36 and accepted SDK licenses. The default application ID is `com.meritiqra.app`, minimum SDK 24 and target SDK 36. Set a local SDK path in ignored `mobile/android/local.properties` or `ANDROID_HOME`.

```sh
cd mobile
npm ci
npm run sync
cd android
./gradlew :app:assembleDebug
./gradlew :app:connectedDebugAndroidTest
./gradlew :app:bundleRelease
```

Install a debug APK with `adb install -r app/build/outputs/apk/debug/app-debug.apk`. Start with `adb shell am start -n com.meritiqra.app/.MainActivity`. Build-time `API_BASE_URL` defaults to production and must match for `npm run sync` and Gradle. Local emulator testing uses `ENVIRONMENT=local API_BASE_URL=http://10.0.2.2:8020` for asset build and the same API_BASE_URL for Gradle. Only the debug manifest allows cleartext. Production release builds must use HTTPS.

To change the package ID, update `mobile/capacitor.config.json`, pass `-PapplicationId=your.package.id` to Gradle, and configure the matching Firebase application and backend `ANDROID_APPLICATION_ID`. Java namespace may remain unchanged. Configure the App Link host in the Android manifest when changing domains.

Set server `ANDROID_APP_LINK_SHA256` to the comma-separated SHA-256 fingerprints of the actual app signing certificate (Play App Signing certificate for Play builds). `/.well-known/assetlinks.json` intentionally returns an empty list until configured. Do not publish a placeholder or debug signing fingerprint as a production trust statement. Verify installed links with `adb shell pm verify-app-links --re-verify com.meritiqra.app` and `adb shell pm get-app-links com.meritiqra.app`.

For push, add the matching Firebase `google-services.json` locally at `mobile/android/app/`, enable the FCM HTTP v1 API, set `FCM_PROJECT_ID`, and grant the Cloud Run service account the Firebase Cloud Messaging API Admin role for that project. Use workload identity/application default credentials; no service-account JSON is packaged. The Firebase file is ignored. No notification is sent unless the user opted in and server configuration exists.

Release signing is deliberately not fabricated. Configure a private upload key through secure Gradle/CI signing configuration, enable Play App Signing, increment versionCode, and produce a signed release AAB before uploading to Play. Complete privacy policy/data safety, content rating, tester tracks, device coverage and account-deletion review. Build artifacts alone are not Play Store approval.

## Validation and limitations

Validation results and artifact paths are recorded below after emulator execution. No physical Android phone or iPhone was available. Google account selection and live FCM delivery require the owner's account/project configuration and are not represented as verified until exercised. Verified production App Links require the release signing fingerprint. No production learner accounts or attempts are created during test runs.

### Executed checks

- Baseline web fixes: 91 backend tests plus both Node UI suites. With mobile additions: 98 backend tests pass.
- Android debug APK compiled and installed on an Android 16 / API 36 ARM64 Pixel 7 emulator.
- Instrumented Android Keystore test passed: persistence across vault recreation and authenticated-encryption tamper rejection.
- Twelve-question exam: 30 seconds offline, local persistence 17 ms, force-stop/reopen, exact question 12 restored, all 12 answers recovered, identical question order and server expiry, and duplicate submit idempotency. See `docs/validation/android-emulator.json`.
- KaTeX rendered in the native WebView and the exam had no horizontal overflow at 412 CSS pixels. Screenshots are under `/tmp/meritiqra-android-evidence`.
- WebKit phone menu and unsupported-fullscreen focus mode were exercised separately; physical iPhone behavior remains unverified.

A development dependency audit reports three moderate findings in Capacitor CLI's transitive `xcode`/`uuid` chain. `npm audit fix` does not currently resolve them. These are build-tool dependencies, not shipped Android runtime code; no forced incompatible override was introduced.

Additional validation passed for fractions, matrices, mhchem, four sharp SVG images, and a Markdown table in the native WebView. The table check found an existing shared renderer bug; table blocks now render before paragraph conversion, with a Node regression assertion. Performance Lab layout had no horizontal overflow at 360, 412, 480 and 800 CSS pixels. The native secure-window flag was verified. See `docs/validation/android-rendering.json`.

Android `:app:assembleDebug`, `:app:bundleRelease`, and `:app:lintDebug` completed successfully (lint: 0 errors, 14 warnings, mainly template resource/manifest suggestions). The release AAB is unsigned and is not ready for Play upload until the owner's signing configuration is supplied.

The real Android-to-Chrome-to-app PKCE handoff passed using synthetic authentication on the local test server. It verified server-derived Student role, clearing the previous owner's queued answers/session position, and withholding session cookies from JavaScript. The test found Capacitor's default java.net/WebView cookie handler retaining a prior identity. `MainActivity` now disables that automatic bridge and clears/disables WebView cookie storage; the native Keystore adapter alone controls API session cookies. This is distinct from live Google account selection, which remains untested. See `docs/validation/android-handoff.json`.

## Production deployment

The additive backend/web commit `bafbab6` was built by Cloud Build `bfba0ff6-0182-4877-acd2-10b332f414be` and deployed as Cloud Run revision `question-bank-cloud-v4-00045-vuk`. Image digest: `sha256:afbb3abfc38034632f7c47f80d70bef58cc0aa142e42abde5a478276f5d9dc4a`. The production site is at 100% on that revision. Because all service `run.app` URLs returned a Google routing 404 while the custom domain was healthy, validation used a brief 10% custom-domain canary before promotion. Live website, SEO, health, mobile configuration, callback, App Links document and service worker returned 200; protected anonymous requests were denied, mock authentication stayed disabled, and downloaded UI assets matched the committed source. See `docs/validation/mobile-live.json`. Previous revision `00043-vap` remains available for rollback.

Final native-only hardening also binds encrypted state to the API origin, so switching a development build to production cannot replay development sessions or answers. Native-only files are excluded from the Cloud Run image; the delivered APK/AAB include this hardening and the cookie-isolation fix. APK and AAB checksums are recorded in `docs/validation/android-artifacts.json`.

Final production-targeted debug APK installation was verified against the live `/api/mobile/config` endpoint and displayed the unauthenticated branded welcome screen. Packaged workspace JavaScript matched repository source, and the APK contained the production origin rather than the emulator test address. Both final APK/AAB builds and the instrumented Keystore test passed again after native hardening.
