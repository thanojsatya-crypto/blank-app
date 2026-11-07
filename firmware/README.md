# ESP32 AOS AES-256-GCM teaching firmware demo

> **Isolated trusted-LAN classroom demo only.** Key Generator provisions an OS-CSPRNG pairing password, the approved simulated 256-bit AOS key, and the user message directly to ESP. Communication/Base Station has no website login and sends only the manually copied pairing password directly to ESP. Both directions use unauthenticated, unencrypted plain HTTP. LAN observers can read or modify the password, key, message, frame, and returned key. Never expose the ESP or apps publicly and never use real secrets.

This firmware keeps the existing ordinary `POST /api/message` path and PB4/GPIO22 counter-only behavior unchanged. The AOS additions are limited to one provision route and one password-only downlink route. There is no site-to-site communication, website login, fixed sample plaintext, NVS/flash/Serial/log/persistent storage path for the AOS secrets, or physical-board validation claim.

## Selected AOS teaching profile

This profile uses the AOS V2 primary-header field layout described by [CCSDS 732.0-B-4](https://ccsds.org/Pubs/732x0b4.pdf) and the AES-GCM field lengths/AAD treatment from the selected [CCSDS 355.0-B-2 Annex E3 teaching subset](https://ccsds.org/Pubs/355x0b2.pdf). It is intentionally **not** a full SDLS implementation or conformance claim.

- Primary header: exact 6-octet `69521234564a`.
- SPI: fixed `0x1234`, serialized as `12 34`.
- Security Header: 14 octets = SPI + 12-octet inline 96-bit nonce.
- Data Field: exactly 32 octets = one explicit message UTF-8 length octet + 1–31 UTF-8 message octets + zero padding. No sample is compiled into the firmware.
- Security Trailer: 16-octet GCM tag.
- Cipher: AES-256-GCM with a 32-byte AES key.
- Total frame: exactly 68 octets (`6 + 14 + 32 + 16`).
- Annex E3 masked AAD: `0012000000001234000000000000000000000000`; the IV is passed separately as GCM nonce, not copied into AAD.
- Nonce: 8-byte ESP hardware-RNG prefix initialized after Wi-Fi/RF starts plus a 4-byte incrementing, non-wrapping counter. Counter exhaustion fails closed. The prefix is regenerated on reboot; cross-boot uniqueness is probabilistic, so **generate and provision a fresh key after every reboot**. A separate 128-bit non-secret `boot_id` is generated in volatile RAM after Wi-Fi starts, and `provision_id` is replaced after each accepted provision; they detect changes, not authenticate or protect data.

The Data Field is not a CCSDS-mandated message format; its one-byte UTF-8 length prefix is this demo's explicit application encoding. Invalid/empty UTF-8 and messages over 31 UTF-8 octets are rejected before state changes; the firmware never silently truncates. The 68-octet frame length remains fixed because the Data Field is padded to exactly 32 octets.

## AOS request boundary

`Content-Type: application/json` is required for `POST /api/aos-demo/provision`, `POST /api/aos-demo/downlink`, and `POST /api/message`. `POST /api/control` parses a JSON request body but does not enforce that header. `GET /api/telemetry` and `GET /api/simulation-trigger` have no request body and do not require a Content-Type header. The AOS origin accepted by the apps is a private RFC1918 IPv4 HTTP origin; no hostname, URL path, query, credentials, HTTPS, localhost, or public IP is accepted.

| Method and route | Caller | Request | Purpose |
| --- | --- | --- | --- |
| `POST /api/aos-demo/provision` | Key Generator only | Exactly `password`, `key_hex`, `message` | Validate and replace ESP's current volatile password, 32-byte key, and encoded message. |
| `POST /api/aos-demo/downlink` | Communication/Base Station only | Exactly `password` | Match current RAM-only password; encrypt current RAM-held Data Field; return frame, matching AES key, and non-secret session IDs. |

`GET /api/telemetry` includes lowercase-hex `boot_id` and `provision_id`; they are non-secret, volatile, and never persisted or logged. The first changes on reboot and the second after a successful new Key Generator provision. Base Station compares both with the successful downlink response before rendering the authenticated dashboard on each app rerun.

Key Generator creates a fresh 32-character URL-safe password with the operating system CSPRNG, independently from its simulated AOS key. The exact provision request schema is:

```json
{"password":"<32-character URL-safe CSPRNG value>","key_hex":"<64 lowercase hex characters encoding exactly 32 bytes>","message":"<user message>"}
```

A successful provision response contains exactly `{"accepted":true,"provisioned":true}`; it echoes no password, key, or message. Key Generator makes one explicit POST and never automatically retries. A rejected or uncertain attempt is closed; generate fresh material before another attempt.

The downlink request schema is exactly:

```json
{"password":"<current 32-character value copied manually from Key Generator>"}
```

It contains no key, key ID, message, or plaintext sample. Before encryption, ESP requires an accepted in-RAM provision and constant-time compares the supplied password to the current RAM value. Missing provision returns HTTP 409; a wrong password returns HTTP 403. Successful output contains exactly the five frame fields `primary_header_hex`, `security_header_hex`, `ciphertext_hex`, `tag_hex`, `frame_hex`, the matching 32-byte `key_hex`, and the non-secret `boot_id` and `provision_id`. This key is returned only after the password check and is exposed on the plain-HTTP LAN; neither ID authenticates or protects any value.

The Base Station validates the exact response schema, both ID shapes, lowercase-hex lengths, complete 68-octet concatenation, fixed header/SPI/AAD, and AES-GCM tag. It displays message plaintext only after successful GCM verification and strict length-prefixed UTF-8/padding checks. A wrong key, tampered ciphertext/tag, or invalid authenticated Data Field releases no plaintext. On a changed boot/provision ID or telemetry/network revalidation failure, it clears its cached AOS verification, relocks behind the existing gate, and rejects the previously authenticated provision ID until Key Generator successfully provisions fresh material. The AES key itself is not displayed or retained in Base Station session state.

## RAM-only lifecycle and ordinary API

Pairing password, AES key, and encoded message exist only in volatile ESP RAM. `setup()` clears all three buffers explicitly; hardware reset/reboot also restarts the program with zero-initialized state. There is no AOS persistence, key logging, Serial output, or key storage in NVS/flash/filesystem. PB6/GPIO27 remains the existing simulated display-state reset button; it is not a substitute for hardware reboot and does not provision secrets. If ESP restarts, an old Base Station password receives HTTP 409; the user must return to Key Generator, create a **fresh password and simulated key**, and provision again.

The four pre-existing routes remain unchanged: `GET /api/telemetry`, `POST /api/control`, `GET /api/simulation-trigger`, and ordinary `POST /api/message`. The message endpoint still sends plain JSON text with its existing bounded message/CRC contract; it is separate from AOS and never reads the AOS key. PB4/GPIO22 still increments only the volatile simulation-trigger counter.

Arduino `WebServer` may keep transient copies in its internal request/body buffers. Local firmware copies are wiped where implemented, but this does not promise complete secure erasure from all transient RAM. Plain HTTP itself provides no confidentiality or integrity.

## Files and verification

- Arduino sketch: `arduino/esp32-qkd-teaching-aos-demo/esp32-qkd-teaching-aos-demo.ino`.
- Shared profile header, included by the sketch and compiled by a host test: `arduino/esp32-qkd-teaching-aos-demo/aos_demo_profile.h`; its reference copy is `aos_demo_profile.h`.
- Byte-identical reference sketch: `esp32-qkd-teaching-aos-demo.cpp`, kept outside the Arduino sketch directory.
- `check_static.py` validates exact route set, sketch/header byte parity, unchanged `/api/message` and PB4 contracts, volatile clear calls, password-before-encryption order, fixed frame profile, UTF-8 oversize rejection, AAD, and nonce checks.
- Host tests cover message length encoding, 68-octet frame construction, AES-256-GCM known-answer and tamper checks, and the shared C++ header/SPI validator. Root app tests exercise provision/downlink payload boundaries and reboot/reprovision behavior with a Python software model.

Run checks from this directory:

```sh
python3 -m pip install -r requirements-test.txt
python3 check_static.py
python3 -m unittest discover -s tests -v
```

These are static/host tests only. **No Arduino compile, flash, execution on ESP32, or physical hardware test was performed.**
