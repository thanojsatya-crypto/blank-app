# Private debugger exact-review handoff

## Candidate and scope

Review the isolated revision derived from candidate ZIP SHA-256 `c17f1eadb2db6386ae00b2bd392e6a8747ac905adc3e72cc39559440d3748ace`. The original candidate directory and ZIP were left untouched. This revision is intended only for private debugger review; do not post project updates to the owner Group.

## Review targets

- Verify the Base Station keeps the existing password-only `POST /api/aos-demo/downlink` route and request contract; do not substitute `/api/pair`.
- Check that ESP-originated non-secret `boot_id` and `provision_id` values are validated against telemetry on every authenticated Streamlit rerun.
- Check reboot/session change and telemetry/network failure clear cached AOS frame/decoded plaintext and relock behind the password-only gate.
- Check a network failure rejects the prior provision ID until a new Key Generator provisioning occurs. The downlink request remains exactly `{"password":"<current password>"}`; no site-to-site calls were added.
- Confirm ordinary `POST /api/message`, volatile password/key/message boundaries, no secret URLs/logs/persistence, plain-HTTP classroom caveats, and existing demo labels remain intact.
- Inspect `ui-previews/communication_base_station_default.png` and `ui-previews/communication_base_station_aos_request.png`; both are refreshed to the actual blank pre-dashboard gate. Gate/error/authenticated/frame/decoded screenshots use synthetic-only state, with no real ESP or external requests.

## Validation completed

- Root unit suite: 147 tests passed.
- Firmware host suite: 7 tests passed.
- `firmware/check_static.py`: passed, including route/hash guards and byte-identical `.cpp`/`.ino` checks.
- No Arduino compile, flash, ESP execution, or physical hardware validation was performed.
