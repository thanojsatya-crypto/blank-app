# ESP32 QKD Teaching Project

This is a **software-only teaching project** with two separate local Streamlit apps: a Qiskit Aer BB84-style measurement demo and an ESP32 Communication/Base Station monitor. Key Generator also offers a separate, local/session-only OS-CSPRNG mode. **No quantum channel exists.** This is not live QKD, secure pairing, or production encryption. Every output from the quantum-circuit demo is labelled **“simulated quantum measurement—not a real QRNG/QKD.”**

## Beginner setup and run

Install Python 3.10 or newer. From this project folder, create and activate a virtual environment, then install the requirements:

```sh
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the two apps as **separate local processes**, each in its own terminal after activating the environment:

```sh
streamlit run key_generator.py --server.address=127.0.0.1 --server.port=8501
```

```sh
streamlit run communication_base_station.py --server.address=127.0.0.1 --server.port=8502
```

On macOS/Linux, the equivalent launcher commands are `./run-local.sh key` and `./run-local.sh communication`. Open `http://127.0.0.1:8501` for **Key Generator** and `http://127.0.0.1:8502` for **Communication / Base Station** on this computer. Both bind to loopback. There is no public deployment configuration, tunnel, or serial/USB feature. Automatic PB4 polling is off until explicitly enabled in Key Generator.

Run all software tests from the project folder:

```sh
python -m unittest discover -s tests -v
python firmware/check_static.py
python -m unittest discover -s firmware/tests -v
```

The apps keep teaching material in transient process/session memory. The **AOS teaching path** deliberately uses plain HTTP between each app and ESP: Key Generator provisioning sends the pairing password, exact simulated 32-byte AES key, and user message; Communication/Base Station sends only the pairing password in its startup gate; after checking it, ESP returns the encrypted frame plus matching key. LAN observers can read or modify this traffic. Use only on a trusted isolated lab network; do not expose either app or ESP publicly, and do not use real secrets. The ordinary `POST /api/message` text exercise remains separate and never consumes the AOS key.

The intended AOS path is **Key Generator creates an independent OS-CSPRNG pairing password + fresh 256-bit simulated AOS key + user message → one explicit Key Generator-to-ESP provision → Communication/Base Station opens on a gate asking for “ESP IP address” and “ESP pairing password (not the AES key)” → one password-only Base Station-to-ESP downlink → ESP returns frame + matching key and non-secret boot/provision IDs → local AES-GCM verify before the dashboard and authenticated plaintext are shown**. The password is cleared after each attempt and is not put in a URL, log, or persistent storage. The apps do not call one another; there is no website login. The gate is a classroom UI check, not secure authentication. A hardware reset/reboot clears the ESP's RAM-only password, AES key, and message; the next run needs fresh Key Generator generation and provisioning.

## Key Generator: existing simulator, AOS teaching-key mode, and OS-CSPRNG mode

The existing **BB84 simulator** remains the default and retains its original 128-round default, sample-size control, disturbance control, optional PB4 read-only polling, sample presentation, and manual-copy output. It uses Qiskit Aer locally; no quantum channel or physical randomness exists.

The separate **CCSDS 355.0-B-2 AOS AES-256-GCM demo** mode runs one Qiskit Aer batch capped at 1,024 rounds. It discloses and removes exactly 64 basis-matched sifted sample bits for QBER. The `MAX_TEACHING_QBER=0.11` rule in `qkd_simulator.py` is an **11% teaching threshold only—not a QKD or security threshold**. Only after a complete sample passes does the generator uniformly select exactly 256 remaining sifted bits without replacement. It aborts without retained output if the sample is missing/incomplete, QBER exceeds 0.11, fewer than 256 candidates remain, Alice/Bob's selected bits disagree, or retained length is not exactly 256.

The approved 256 simulated bits are packed directly as `int(bits, 2).to_bytes(32, 'big')`: the leftmost bit becomes the MSB of the first byte. There is no padding, truncation, KDF, or reuse. The UI never displays the retained key bits or bytes. Independently, it creates a fresh 32-character URL-safe pairing password using Python's OS-backed `secrets.token_urlsafe(24)` (192 bits of CSPRNG input). Password generation is separate from and does not derive from the AOS key.

The user enters a message in Key Generator. The fixed AOS 32-byte Data Field is encoded as **one explicit UTF-8 octet-length byte + 1–31 UTF-8 message octets + zero padding**. Empty, invalid UTF-8, or oversize input is rejected before any request; there is no silent truncation. Key Generator makes exactly one deliberate `POST /api/aos-demo/provision` containing only `password`, `key_hex` (exactly 64 lowercase hex characters/32 bytes), and `message`. It does not automatically retry; if delivery is uncertain or rejected, generate fresh material before another attempt. It is the only website that provisions those values to ESP.

Optional PB4 polling remains isolated to the original simulator mode and is off by default. It is a read-only observation feature; the first successful poll establishes a baseline, and a later changed counter triggers exactly one fresh local simulator run.

### Local OS-CSPRNG key mode (separate path)

The additive **OS CSPRNG (256-bit local key)** mode calls Python's standard-library `secrets.token_bytes(32)` once after an explicit button click and displays the resulting 32 bytes as hexadecimal. `secrets` uses the strongest randomness source provided by the operating system; describe the result as **OS CSPRNG/DRBG cryptographic pseudorandom output**, not true randomness, a QRNG, or QKD. The project adds no custom random-number generator and does not use `random` for this key.

This OS-CSPRNG key remains only in its current Streamlit session and has **no AOS provisioning path**. It is distinct from the simulated AOS key and from the OS-CSPRNG pairing password. The two apps do not share session memory.

### Volatile provisioning, reboot behavior, and password-only downlink

ESP stores the current pairing password, exact AES-256 key, and encoded message only in RAM. Setup explicitly clears their buffers. There is no NVS/flash/Serial/log/persistent-storage path for these values. A hardware reset/reboot loses all three; a stale app password is rejected until Key Generator creates and provisions fresh material. The AES key is never displayed by Key Generator or Base Station.

Communication/Base Station has **no website login, no site-to-site connection, and no provisioning control**. Before any dashboard content appears, its startup gate asks for the ESP's private IPv4 address and the current pairing password (not the AES key). Its one deliberate connection request to `POST /api/aos-demo/downlink` contains exactly `{"password":"<current 32-character password>"}`—no key, IP, message, or plaintext sample in the body; the ESP IP is the request target. ESP rejects a missing volatile provision with HTTP 409 and a wrong password with HTTP 403. Wrong password, unavailable route/network, or invalid returned frame leaves the dashboard inaccessible with a retryable error. The input password is cleared after each attempt.

After successful password validation, ESP encrypts its RAM-held Data Field and returns the 68-octet frame components, matching 32-byte `key_hex`, and non-secret `boot_id` and `provision_id`. Base Station checks the exact response schema, fixed frame length/header/SPI, and AES-256-GCM tag before decoding the length-prefixed UTF-8 message. Plaintext is withheld for a wrong key, malformed authenticated Data Field, or tampered frame/tag. The key is returned over plain HTTP and is observable to LAN traffic observers; this is intentionally a classroom demonstration, not secure provisioning.

The selected Annex E3 teaching profile fixes primary header `69521234564a`, SPI `0x1234`, a 96-bit per-frame nonce, 20-octet masked AAD `0012000000001234000000000000000000000000`, AES-256-GCM, and a 16-octet tag. The frame remains exactly 68 octets: 6-byte primary header + 14-byte Security Header (SPI + nonce) + 32-byte ciphertext Data Field + 16-byte tag. Nonces use a fresh ESP hardware-random prefix and non-wrapping counter per boot. A random, non-secret `boot_id` changes each boot, and a random `provision_id` changes after each accepted fresh provisioning; both are returned by telemetry and successful downlink responses. Base Station checks both on every dashboard rerun and clears cached verified frame/plaintext and returns to the gate if either changes or telemetry cannot be reached; it rejects the previously authenticated provision ID until Key Generator sends a fresh provision. These volatile IDs are not credentials or proof of secure authentication. This is not a full SDLS receiver/profile, replay-protection service, secure transport, or CCSDS-compliant satellite software. No physical ESP compile, flash, or hardware test is claimed.

## Communication / Base Station: ESP telemetry, gates, and messages

The Communication/Base Station app is a **separate local app**. Its initial gate must receive an accepted password-only ESP downlink response and pass AES-GCM verification before the dashboard appears. While authenticated, every dashboard rerun performs a read-only `GET /api/telemetry` and compares both returned session IDs with those returned by the gate downlink. A changed/missing ID or telemetry/network failure clears the cached AOS verification (frame and decoded plaintext), relocks the UI, and rejects the previously authenticated provision ID until fresh Key Generator material is provisioned to ESP. After reboot the ESP's RAM provision is gone, so fresh Key Generator material and provisioning are required. After connection, its ordinary ESP client uses `GET /api/telemetry`, `POST /api/control`, and `POST /api/message` as before. The AOS receiver displays the frame fetched by the gate; it does not call Key Generator or provision. The real message tab sends ordinary text only; it does not use simulated key or gate data. The ESP—not the dashboard—generates the reply. `GET /api/health` is not part of this project's API contract.

Each one-qubit gate is an explicit object such as `{"gate":"H","target":0}`. Supported one-qubit gates are `I`, `H`, `X`, `Y`, `Z`, `S`, and `T`; target must be integer `0` or `1`. The only supported CNOT is `{"gate":"CNOT","control":0,"target":1}`. Empty chains are valid and chains are limited to 64 operations. Extra control fields are rejected before transmission. The ESP's returned chain and classical state-vector calculation are displayed separately from the live physical/display telemetry; the app does not calculate or invent an ESP result. Missing telemetry fields are labelled **“Not reported”** and are never filled with assumed values.

This revision preserves the firmware's existing physical button mapping:

| Input/output | GPIO | Behavior in this project |
| --- | ---: | --- |
| PB1 / H | 18 | Active-low; sets physical display `state` to 0. |
| PB2 / X | 19 | Active-low; sets physical display `state` to 1. |
| PB3 / message slot | 21 | Active-low; cycles `message_index` through slots 1–5; sends no message. |
| PB4 / simulation trigger | 22 | Active-low; increments the volatile simulation-trigger counter only. |
| PB5 / display toggle | 25 | Active-low; toggles `display_mode` between `qubit` and `cipher`. |
| PB6 / state reset | 27 | Active-low; sets physical display `state` to 0; does not clear the saved gate simulation. |
| Status LED | 2 | Output only; never a button input. |

Buttons remain active-low and the legacy telemetry field `reseed_count` remains `0` for compatibility; PB4 does not reseed. The telemetry schema reports current values, not a history of button press events, so the dashboard does not claim an individual button event occurred.

### Real ESP message-send contract

The separate message tab sends one JSON frame to `POST /api/message`. The serialized UTF-8 JSON body is limited to **1024 bytes** and contains exactly `message_id`, `sequence`, `message`, and `crc32`. The ID is 1–32 ASCII letters/digits/underscore/hyphen; `sequence` is a positive uint32 echoed by the ESP but not globally ordered; and `message` is at most **256 UTF-8 bytes**. CRC is eight lowercase hexadecimal digits representing CRC-32/ISO-HDLC over **exactly the UTF-8 bytes of `message` only**. The request frame is frozen before transmission and reused byte-for-byte for retries.

On first acceptance, HTTP 200 returns exactly `device`, `message_id`, `sequence`, `ack`, `status`, `esp_sequence`, `received_message`, `reply_message`, `request_crc32`, `computed_crc32`, `integrity`, and `duplicate`. It identifies device `esp32-qkd-teaching`, echoes the ID/sequence/message/CRC, and returns `ack:true`, `integrity:"valid"`, the ESP-assigned sequence and actual reply, with `status:"accepted"` and `duplicate:false`. An exact retry within the cache returns HTTP 200 with the same actual reply and ESP sequence, `status:"duplicate"`, `duplicate:true`, and `ack:true`. These response-derived values are shown as returned by the ESP; the app does not invent an ACK or reply. A CRC mismatch is HTTP 422 (`crc_mismatch`, `ack:false`, `integrity:"invalid"`) and includes the ESP's `computed_crc32`; a changed request reusing a cached ID is HTTP 409 (`id_conflict`, `ack:false`, `integrity:"not_checked"`); invalid JSON/fields are HTTP 400 and oversized bodies HTTP 413. Error responses carry `device`, any valid parsed ID/sequence, `ack:false`, `status`, `integrity`, and `error`, with no reply. Other errors also use `integrity:"not_checked"`. ACK and integrity fields—not HTTP status alone—are authoritative.

Each network attempt has a **2-second timeout**. The app makes the initial request plus at most **two automatic retries**, and only after timeout, connection error, or HTTP 5xx. Retries do not follow redirects and do not occur for any 4xx, `ack:false`, malformed ACK, or failed integrity check. If the retry limit is exhausted, delivery is shown as **“delivery unknown”** because the ESP may have accepted a request whose response was lost. A manual retry is available and reuses the same serialized frame, ID, sequence, text, and CRC; it does not claim that a previous unknown delivery failed.

The ESP deduplicates only the **latest eight IDs in volatile RAM since boot**. An exact retry within that window returns `duplicate:true`, `ack:true`, and the original reply and ESP sequence without incrementing `esp_sequence`. A changed sequence/message/CRC with a cached ID conflicts before CRC mismatch handling. After eight newer unique accepted IDs evict the old ID—or after ESP reboot—the ID may be accepted again; there is no durable exactly-once guarantee. The app's separate session-only history is capped at ten messages and is not persisted or logged.

CRC-32 detects accidental transmission errors only; it is **not cryptographic integrity, authentication, encryption, or key protection**. The endpoint uses plain HTTP over Wi-Fi/LAN demo transport. Keep the ESP and both apps on a trusted LAN; never expose the ESP or either app publicly. This is not satellite communication, a QKD link, or a secure quantum communication system.

### Plain-language data path

`ESP32 → Wi-Fi 802.11 → local IP → HTTP API/JSON → local dashboard`

“Satellite” and “base station” are role analogies only. The live ESP path includes **no satellite radio or 3GPP NTN**. The SPP/TC/TM learning simulator is offline; the separate AOS teaching profile is not a full CCSDS/SDLS implementation. This is not a QKD link. Plain HTTP on a trusted LAN is demo transport only; it is not encrypted or authenticated. The message endpoint's CRC detects accidental corruption only, not tampering. Only ordinary text explicitly entered in the real message-send tab is sent to `/api/message`; the AOS provision/downlink exchange is separate and exposes secrets to LAN observers. Never expose the ESP or either app publicly.

### Separate in-process message demonstration

The **Local send/receive demo** tab is a different feature from ESP telemetry. It echoes a typed teaching message inside the same Streamlit process, keeps the log only in the current session's memory, and caps it at **10 messages**. Each entry visibly shows **“Sent (local simulation)”** and **“Received (local simulation)”**. The log is labelled **non-secure** and **not actual telemetry**; it does not encrypt, contact another app/device, or issue any ESP request. Clear the session log to start over. Do not enter real secrets.

## Firmware integration boundary

This isolated revision adds exactly two AOS routes: Key Generator-only `POST /api/aos-demo/provision` and password-only Base Station `POST /api/aos-demo/downlink`. It preserves the ordinary `GET /api/telemetry`, `POST /api/control`, `POST /api/message`, existing button/PB4 behavior, and the separate offline CCSDS learning tab. Base Station never generates or provisions an AOS key. No physical-board test is claimed.

Tests cover the simulated 256-bit key criteria, OS-CSPRNG pairing-password shape, one-shot exact provisioning schema, UTF-8 length encoding and oversize rejection, RAM reset/reboot clearing, fresh reprovisioning, stale-session and wrong-password rejection, frame round-trip, wrong-key/tamper fail-closed behavior, the exact 68-octet/AAD/GCM profile, existing app navigation/message contracts, and unchanged firmware `/api/message`/PB4 hashes. These are host/static tests, not an Arduino compile, flash, or physical ESP/board test.

## CCSDS learning simulation (offline only)

In **Communication / Base Station**, select the **CCSDS learning simulation** tab. Here, SPP means **Space Packet Version 1**, encoded with PVN bits `000`. Enter sample UTF-8 text, select a Space Packet Version 1, TC, or TM output, and set the displayed identifiers and counters; **Build and decode offline frame** shows the selected header fields, exact uppercase wire-order hex, local decode, round-trip result, frame-length validation, and FECF validation where the teaching layout includes an FECF. Space Packet Version 1 itself has no FECF in this profile. Every TM output is a variable-length offline layout exercise, not a standard-valid TM channel frame; it does not model the CCSDS TM constant-length-per-channel-during-a-Mission-Phase requirement (§4.1.1.2). Its FECF layout reference is §4.1.6.2, pp. 4-13–4-14. The deterministic COP-1-inspired event trace is displayed in event order, and its initial sequence number and transmission limit can be changed.

The local path is `typed UTF-8 → Space Packet Version 1 primary header → optional TC/TM transfer frame → local decoder`. The tab uses only the pure helpers in `ccsds_simulator.py`; it does not invoke the live ESP client or make network calls. The existing ESP telemetry/gate, real ESP message, local echo, and demo-only tabs remain separate. **A link-layer ACK/CLCW does not prove that an application command executed or that its requested effect occurred.**

This is a **narrow teaching subset**, not full COP-1 and not a CCSDS-compliant implementation. The Space Packet Version 1 layout fixes PVN bits `000`; APID 2047 is reserved as the Idle Packet APID, and rejecting it is this simulator's profile choice—not a general CCSDS prohibition. TC Type-AD, FECF presence, and exactly one complete Space Packet Version 1 per frame are selected teaching-profile constraints, not broad TC compliance claims. TM header options are fixed for a variable-length offline layout exercise; output length varies with packet length, and the result is not a standard-valid TM channel frame. The COP-1-inspired trace models one already-active single-VC session, one in-sequence frame, one lost status report, a symbolic T1 timeout, at most one retry, and an abstracted CLCW return path. Its state names are abstract teaching labels, not normative FOP/FARM states or standard transitions. `Transmission_Limit=3` is this simulator's configured default, not a CCSDS default. It is deterministic and has no elapsed wall-clock time.

Not implemented: satellite RF, synchronization, channel coding, physical hardware, SDLS crypto, real QKD/QRNG, key generation, complete COP-1/FOP-1/FARM-1 behavior, packet segmentation/reassembly, or the other omitted profiles and channel procedures. The simulation creates or uses no keys or crypto and changes nothing in the live API. It has **not been tested against an ESP32 board** and makes no hardware/board support claim.

### Official CCSDS references

- [CCSDS 133.0-B-2, Space Packet Protocol, Issue 2 (June 2020)](https://ccsds.org/Pubs/133x0b2e2.pdf), §§4.1.2–4.1.3.5: SPP primary-header profile.
- [CCSDS 232.0-B-4, TC Space Data Link Protocol, Issue 4 (October 2021)](https://ccsds.org/Pubs/232x0b4e1c1.pdf), §§4.1.1–4.1.4.2: TC Type-AD header and FECF profile.
- [CCSDS 232.0-B-4 Technical Corrigendum 1 (October 2023)](https://ccsds.org/Pubs/232x0b4e1c1_tc2325.pdf): cited for the selected TC teaching profile; this does not expand the simulator into broad TC compliance.
- [CCSDS 132.0-B-3, TM Space Data Link Protocol, Issue 3 (October 2021)](https://ccsds.org/Pubs/132x0b3.pdf), §§4.1.1.2 and 4.1.6.2, pp. 4-13–4-14: constant-length-per-channel-during-a-Mission-Phase limitation and FECF reference for TM layout exercises.
- [CCSDS 232.1-B-2, Communications Operation Procedure-1, Issue 2 (September 2010)](https://ccsds.org/Pubs/232x1b2e2c1.pdf).
- [CCSDS 232.1-B-2 Technical Corrigendum 1 (April 2019)](https://ccsds.org/wp-content/uploads/gravity_forms/5-448e85c647331d9cbaf66c096458bdd5/2025/01//232x1b2e2c1_tc1911.pdf?gv-iframe=true).

The profile details, wire-field constraints, modeled COP-1 events, and omissions are also summarized in [`CCSDS_PROFILE.md`](CCSDS_PROFILE.md). The UI is an educational local software simulation only; it does not claim standards conformance or flight/board readiness.
