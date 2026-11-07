# CCSDS teaching-simulator profile

The `ccsds_simulator.py` module is an **offline learning aid**, not a CCSDS conformance claim or a flight implementation. It has no `esp_api` import, live HTTP, radio/hardware access, real timing, key generation, simulated BB84/Aer key material, or SDLS behavior. Teaching data stays on the local software path, separate from the live Wi-Fi/HTTP ESP message path. The separate Key Generator AOS workflow provisions the approved simulated 256-bit teaching key, independent pairing password, and user message directly to ESP; it does not change this offline module or the ordinary message path.

## Implemented wire layouts

- **Space Packet Version 1 (SPP), encoded with primary-header PVN bits `000`:** as profiled against [CCSDS 133.0-B-2, Space Packet Protocol, Issue 2 (June 2020)](https://ccsds.org/Pubs/133x0b2e2.pdf), §§4.1.2–4.1.3.5, pp. 4-1–4-6, Figures 4-1 and 4-2. Packet type is `0` telemetry or `1` telecommand; the secondary-header flag is carried but mission-defined contents are opaque; sequence flags are 0–3; the 14-bit sequence value is carried as a count/name; the data field is 1–65,536 octets; and the 16-bit Packet Data Length is data-field octets minus one. APID 2047 is reserved as the Idle Packet APID. Rejecting it is **this simulator's teaching-profile choice**, not a general CCSDS prohibition.
- **TC Type-AD Transfer Frame teaching layout:** The selected layout follows [CCSDS 232.0-B-4, TC Space Data Link Protocol, Issue 4 (October 2021)](https://ccsds.org/Pubs/232x0b4e1c1.pdf), §§4.1.1–4.1.4.2, pp. 4-1–4-10, Figures 4-1/4-2 and Table 4-1, with [Technical Corrigendum 1 (October 2023)](https://ccsds.org/Pubs/232x0b4e1c1_tc2325.pdf). Version Number `00`, Bypass `0`, Control Command `0` (Type-AD), Reserved Spare `00`, no Segment Header, FECF present, and **exactly one complete Space Packet Version 1 per frame** are selected teaching-profile constraints—not broad TC compliance claims. SCID is 10 bits, VCID 6 bits, N(S) 8 bits, and the 10-bit Frame Length is total frame octets minus one (including FECF); this chosen layout fits within a 1,024-octet TC frame.
- **TM variable-length offline layout exercise:** The rendered TM outputs are variable-length offline layout exercises, **not a standard-valid TM channel frame**. The exercise fixes header options (Version Number `00`, OCF absent, Transfer Frame Secondary Header absent, Synchronization Flag `0`, Packet Order Flag `0`, Segment Length Identifier `11`, First Header Pointer `0`, and FECF present) and places one complete Space Packet Version 1 in the data field. Its total length varies with the packet. It does **not** model the CCSDS TM requirement for constant Transfer Frame length per channel during a Mission Phase (CCSDS 132.0-B-3 §4.1.1.2). Its FECF layout reference is §4.1.6.2, pp. 4-13–4-14 of [CCSDS 132.0-B-3, TM Space Data Link Protocol, Issue 3 (October 2021)](https://ccsds.org/Pubs/132x0b3.pdf). A local field/CRC check must not be interpreted as channel-frame validity or compliance.

For the TC and TM layouts, CRC-16 uses the standard's MSB-first polynomial `x^16 + x^12 + x^5 + 1` (`0x1021`), an all-ones initial register (`0xFFFF`), and no final XOR; the FECF is appended most-significant octet first. The tests include fixed example byte vectors and the common `123456789` check value `0x29B1`. These checks validate local encoding/decoding behavior only; the TC selections above remain a teaching profile and the TM output remains a layout exercise.

## COP-1-inspired teaching trace

The bounded trace borrows selected behavior from [CCSDS 232.1-B-2, Communications Operation Procedure-1, Issue 2 (September 2010)](https://ccsds.org/Pubs/232x1b2e2c1.pdf), including [Technical Corrigendum 1 (April 2019)](https://ccsds.org/wp-content/uploads/gravity_forms/5-448e85c647331d9cbaf66c096458bdd5/2025/01//232x1b2e2c1_tc1911.pdf?gv-iframe=true). It starts in an already-active, single-Virtual-Channel Type-AD teaching scenario. The chosen values are retransmission-allowed operation (§6.1.8.3.1), FOP sliding-window width **K=1**, FARM window **W=2**, positive width **PW=1**, negative width **NW=1**, and 8-bit modulo-256 sequence numbers. The window choice follows §§6.1.8.2–6.1.8.3 and the corrigendum. `Transmission_Limit=3` is this teaching simulator's configured default, counts the original send plus retries, and is **not a CCSDS default**. Timeout type is configured as `0` for this selected example.

`simulate_cop1_scenario()` models one frame accepted by FARM-1, a lost status report, a symbolic T1 timeout, one retransmission, a duplicate discarded inside the example's negative window (Table 6-1, E1/E4, pp. 6-9–6-10), then a reported N(R)=V(R) and acknowledgement in the trace. The related standards material is §§5.1.9–5.1.10, 5.2.4, 5.2.7–5.2.8 and Table 5-1. There is no elapsed wall-clock time, TM OCF, TC CLCW, or modeled CLCW transport.

All displayed FOP/FARM state strings are **abstract teaching labels**, not normative protocol-state names and not evidence of standard state transitions. This is **not** a complete COP-1/FOP-1/FARM-1 implementation: initialization/unlock/set-V(R), all state-table events, negative acknowledgements, Wait/Lockout, multiple outstanding frames, general retry behavior, and actual CLCW transport are not implemented. A `Transmission_Limit=1` run shows the simulator's abstract timeout-alert branch; the default run demonstrates its selected one-retry example.

## Explicit omissions and exported API

SDLS is **not implemented** in the offline frame simulator. There is no homegrown substitute, pseudo-crypto, authentication, security header/trailer, key material, or security state in that module. The separate AOS teaching-key path described below is integrated with the ESP demo and does not change this offline simulator or the ordinary message path. Also omitted from the offline simulator: radio, modulation, synchronization, channel coding, physical-layer behavior, TC Type-B/C frames, TC Segment Headers, TM OCF/secondary headers, TM idle/padding, packet segmentation/reassembly, variable first-header-pointer cases, full channel management, and real timing. Input validation rejects unsupported options rather than interpreting them speculatively.

## Separate AOS Annex E3 teaching subset

The separate Key Generator AOS mode is a single-frame teaching subset informed by [CCSDS 355.0-B-2, Space Data Link Security, Issue 2 (July 2022)](https://ccsds.org/Pubs/355x0b2.pdf), Annex E3. This is distinct from `ccsds_simulator.py`: the offline SPP/TC/TM/COP-1 simulator remains offline and has no SDLS behavior. The AOS Data Field has a fixed 32-octet size, but its contents come from the user-entered message—not a fixed sample.

- **6-octet AOS V2 primary header:** `69521234564a`.
- **No FHEC, Insert Zone, OCF, or FECF.**
- **14-octet Security Header (SH):** 16-bit SPI followed by a 96-bit inline IV; SPI is fixed at `0x1234` and serialized big-endian as `1234`.
- **32-octet VCA-SDU/Data Field:** one length octet, up to 31 UTF-8 message octets, then zero padding. Oversize or invalid UTF-8 is rejected before provisioning; there is no truncation.
- **16-octet AES-GCM authentication tag.**

The complete frame is exactly **68 octets**: `6 + 14 + 32 + 16`. The Key Generator independently creates an OS-CSPRNG pairing password and uses its approved simulated BB84/AOS process to produce exactly 256 key bits. It makes one explicit `POST /api/aos-demo/provision` containing exactly the password, 32-byte key, and user message. The Communication/Base Station has no website login and makes no site-to-site request; after the user manually copies the password, it makes a password-only `POST /api/aos-demo/downlink`. ESP checks that password against its current RAM-only value, then encrypts the RAM-held Data Field and returns the encrypted frame plus the matching key for local verification. This route returns no plaintext sample.

The firmware's current password, AES key, and message are volatile RAM only. Hardware reset/reboot clears them; no NVS, flash, Serial, log, or persistent storage path exists for those values. A stale Base Station session receives HTTP 409 and requires fresh Key Generator material and a new explicit provision. The app does not automatically retry a provision or downlink request.

For the fixed header/SPI, the 20-octet AAD fixture is exactly `0012000000001234000000000000000000000000`. AAD starts as 20 zero octets; only the masked VCID bits from primary-header octet 1 and the big-endian SPI survive: AAD octet 1 is `primary_header[1] & 0x3f` (`0x52 & 0x3f = 0x12`), and AAD octets 6–7 are `12 34`. Other primary-header positions are zero in AAD. The actual 96-bit IV is the separate GCM nonce; the twelve IV positions in the AAD construction are zero. Not every primary-header bit is authenticated. Nonce uniqueness is enforced with a random prefix and non-wrapping counter within each boot; cross-boot separation is probabilistic, so a fresh key is required after reboot.

**Exposure and boundaries:** provisioning and downlink use plaintext, unauthenticated HTTP on a trusted LAN. Password/key/message and the returned key are visible to LAN observers. Arduino `WebServer`'s internal request-body buffer is not explicitly wiped by the sketch, so transient plaintext copies may remain in RAM. The firmware has no receive/decrypt service, replay-check path, secure provisioning, QKD system, or CCSDS conformance/interoperability claim. The generated 256-bit value remains a software simulation—not QKD.

The public functions in `ccsds_simulator.py` are:

```python
encode_space_packet(data_field: bytes, *, apid: int, packet_type: int = 0,
                    secondary_header_flag: bool = False, sequence_flags: int = 3,
                    sequence_value: int = 0) -> bytes
decode_space_packet(packet: bytes) -> dict[str, object]
crc16_ccsds_fecf(data: bytes) -> int
encode_tc_transfer_frame(space_packet: bytes, *, spacecraft_id: int,
                         virtual_channel_id: int = 0,
                         frame_sequence_number: int = 0) -> bytes
decode_tc_transfer_frame(frame: bytes) -> dict[str, object]
encode_tm_transfer_frame(space_packet: bytes, *, spacecraft_id: int,
                         virtual_channel_id: int = 0,
                         master_channel_frame_count: int = 0,
                         virtual_channel_frame_count: int = 0) -> bytes
decode_tm_transfer_frame(frame: bytes) -> dict[str, object]
simulate_cop1_scenario(*, initial_sequence_number: int = 255,
                       transmission_limit: int = 3) -> dict[str, object]
```

Run the focused tests from this directory with `python3 -m unittest discover -s tests -v`.
