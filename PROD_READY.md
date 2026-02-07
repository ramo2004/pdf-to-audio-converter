# Production Readiness Notes

Status: The app works end-to-end, but there are a few production blockers to address before a public launch.

## Production Blockers

1. Client-side debug logging
   - The browser console logs include request bodies, GCS paths, and operational steps.
   - This can leak user identifiers and file names, and adds noise.
   - Files:
     - text-to-audio-frontend/src/app/page.tsx

2. Server-side verbose logging of user data
   - The backend prints user IDs, file names, and full GCS paths.
   - This can be considered PII and increases log volume/cost.
   - Files:
     - main.py
     - storage.py
     - quota.py

3. Public Cloud Run endpoint without authenticated transport
   - Cloud Run is deployed with --allow-unauthenticated.
   - Access is protected by API key or short-lived token, but traffic is still public.
   - If the API key is compromised, anyone can mint signed URLs.
   - Consider adding Cloud Run IAM authentication for /upload_url or rotating the API key regularly.
   - Files / config:
     - main.py
     - Cloud Run deploy config

## Recommendations (Non-blockers)

1. Netlify function timeout
   - /process now bypasses Netlify functions, so this is resolved.
   - Keep the proxy route only for local/dev or remove it to reduce confusion.

2. Multiple lockfile warning in Next build
   - Builds warn about multiple lockfiles in the repo.
   - Not a functional issue, but can be cleaned up by removing the top-level lockfile if unused
     or setting outputFileTracingRoot in next.config.js.

3. Quota persistence
   - Quota is stored in GCS JSON and updated at runtime.
   - Consider adding retries/backoff or alerting for quota storage failures.

4. Structured logging
   - Consider replacing print/console with structured logs and log levels.
   - This makes it easier to filter/alert in Cloud Logging.

## Minimal Checklist to Ship

1. Remove or gate client-side console logs behind a debug flag.
2. Reduce backend log verbosity or redact PII.
3. Decide on API key rotation policy or enforce Cloud Run auth.
