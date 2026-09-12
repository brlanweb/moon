# Moon Implementation Verification

Date: 2026-09-08

## Delivered

- Moon login: desktop/mobile layout, local NASA lunar image, original crescent/orbit mark, SVG/192 PNG/512 PNG/32 ICO.
- Real Ant Design form: labels/autofill, required fields, standard/LDAP, MFA/resend, keyboard submit, pending state, original session storage/redirect and real-IP warning.
- Current active frontend and backend generated notifications rebranded. User input, shell protocols, technical identifiers, external URLs and source license/copyright retained.
- The unused experimental `spug_web2` frontend was removed after `spug_web` was confirmed as the only build and deployment target. Existing monitor work was not changed.

## Evidence

- Frontend: `CI=true npm test -- --watchAll=false --runInBand`: 3 suites, 11 tests pass. Existing monitor tests emit act callback warnings; Node emits punycode deprecation warning.
- Backend: `SPUG_DEBUG=1 venv/bin/python manage.py test apps.setting.tests apps.setting.test_branding --keepdb`: 6 pass, Django checks clean. Paramiko emits existing TripleDES deprecation warnings. No real emails sent; external transports mocked.
- Production: `npm run build`: compiled successfully.
- `git diff --check`: no whitespace errors.
- Browser: 1440x900, 390x844, 320x568, 1024x600: no horizontal overflow; visible images decoded; no page errors. English locale renders translated login/title. Empty submit blocked. LDAP Enter submit carries type=ldap. MFA code/resend countdown works. Editing credentials resets challenge. Pending field backgrounds remain dark; settled MFA has no stale errors.
- API responses intercepted for browser auth testing: no real credentials sent, no production authentication claim.
- Independent review: copyright attribution and About translation mismatch found and fixed; targeted re-review confirms both addressed, no new issues.

## Availability

Local dev server: http://127.0.0.1:3000 . Existing API proxy points to 127.0.0.1:8000. Production bundle built but no server deployment/restart, git commit or push performed.

## Assets

See moon-assets.md. Image generation provider was unavailable; logo was drawn as original SVG and exported locally instead.
