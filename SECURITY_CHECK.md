# Security Check (2026-02-07)

Scope: local repo review of backend + frontend code paths, configs, and deploy posture.

## Findings (Ordered by Severity)

### High
1) Public Cloud Run + API key only
   - Cloud Run is deployed with `--allow-unauthenticated`.
   - Protection relies on `API_KEY` or a short‑lived `process_token`.
   - If the API key leaks, an attacker can mint signed upload URLs and run TTS at your cost.
   - Files / config:
     - `main.py` (API key enforcement)
     - Cloud Run deploy in `PROJECT.md`
   - Mitigations:
     - Require Cloud Run IAM authentication for `/upload_url` and `/cleanup`.
     - Rotate `API_KEY` regularly, store it in Secret Manager, and restrict who can read it.

### Medium
2) `/quota` endpoint is unauthenticated
   - `/quota` returns usage/limits without `_require_api_key`.
   - This can leak service usage data and makes it easier to probe quotas.
   - File:
     - `main.py`
   - Mitigation:
     - Require API key for `/quota`, or remove the endpoint in production.

3) PII/metadata logging in backend
   - Backend prints user IDs, filenames, and full GCS paths.
   - This can be considered PII and inflates log volume/cost.
   - Files:
     - `main.py`
     - `storage.py`
     - `quota.py`
   - Mitigation:
     - Switch to structured logs with redaction and levels.
     - Gate verbose logs behind a `DEBUG` env var.

### Low
4) Client-side console logs contain request metadata
   - Browser console logs request bodies and GCS paths.
   - Not a direct exploit, but unnecessary exposure and noise in production.
   - File:
     - `text-to-audio-frontend/src/app/page.tsx`
   - Mitigation:
     - Remove logs or gate them behind `NEXT_PUBLIC_DEBUG`.

5) Multiple lockfile warning (build-time)
   - Next warns about multiple lockfiles; not a security bug but can affect build trace scope.
   - Consider setting `outputFileTracingRoot` or removing unused lockfiles.

## What’s Good
- Signed upload URLs are time‑limited and scoped to a specific object path.
- Input validation on user_id, file_name, and remote_path prevents path traversal.
- Max upload size enforced server‑side.

## Recommended Next Steps
1) Lock down Cloud Run with IAM auth (at least for `/upload_url`).
2) Require API key for `/quota` or remove it in prod.
3) Reduce/structure backend logs and remove client logs.
