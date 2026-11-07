# UI-only revision notes

This is a separate presentation-layer revision based on the reviewed CSPRNG project. The reviewed source folder and its ZIP remain unchanged.

The two Streamlit apps now share a light, card-based workspace style with clearer title hierarchy, project-specific navigation, readable status callouts, and metric cards. Communication / Base Station exposes its five existing destinations in a left sidebar using their existing labels; the original view content and ESP controls remain in place. Key Generator keeps the BB84 simulator as its default and preserves the existing AOS and OS CSPRNG modes.

No Cue account, login, credentials, data, or Agent/Group features are used or added. The Cue desktop layout is referenced only through the supplied description. Cue has no browser version, so its live interface could not be visually inspected; the revised Streamlit pages were checked separately in a local browser.

This revision changes no ESP API routes, request contracts, protocol logic, key-generation behavior, firmware, or existing safety labels. Verification: all **121 tests passed** with `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`. Browser screenshots were captured for both default dashboards and the real ESP message-send section.

## Follow-up UI-only refinement

This follow-up is based on the reviewed UI revision and is kept in a separate folder/archive. Both app entrypoints now offer a collapsed plain-language glossary for their specialist vocabulary; important QBER/AOS metrics and the message composer also have concise hover help. The real ESP message editor saves its unsent text in a separate Streamlit session-state value and restores it when returning to that section. Draft text is still sent only after the existing explicit send action; the API contract, serialized request, retry logic, protocol behavior, and key generation are unchanged. The draft remains session-only and is not persisted beyond the app session.

Verification after this follow-up: **122 tests passed** with `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`; the message-navigation regression also passed independently. No Cue integration, Agent/Group functionality, or project updates were added.


## Isolated volatile-message AOS revision

This new isolated revision is based on the latest reviewed pairing/downlink archive; earlier folders and ZIPs remain untouched. The AOS path now uses a fresh OS-CSPRNG pairing password, the approved simulated 256-bit AES key, and a user-entered message provisioned in one explicit Key Generator-to-ESP request. ESP holds password/key/message only in RAM, encodes the message into the fixed 32-octet Data Field with an explicit UTF-8 length, and rejects oversize text without truncation. Communication/Base Station has no login or provisioning role; it manually submits only the pairing password, then validates/decrypts the ESP-returned 68-octet AES-256-GCM frame plus matching key. Hardware reset/reboot clears ESP state; stale sessions require fresh provisioning. Ordinary `/api/message` and PB4 behavior are preserved.

Verification: **139 app tests passed**, **7 firmware host tests passed**, and firmware static checks passed. Python compile checks passed. No Arduino compile, flash, live ESP execution, or physical hardware validation was performed.

## First-open ESP pairing gate revision

This separate copy is based on the reviewed volatile-message project. Communication/Base Station now opens on a gate with the exact labels **“ESP IP address”** and **“ESP pairing password (not the AES key)”**. It makes one password-only `POST /api/aos-demo/downlink` directly to ESP and reveals no dashboard content unless the ESP response matches the downlink contract and its returned AES key verifies the GCM tag and encoded message. Rejection, reset/stale provisioning, route/network errors, malformed frames, or GCM failure keep the app locked with a retryable message. The password field is cleared after each attempt; the password is not placed in a URL, application log, or persistent storage.

Key Generator remains the only app that provisions a fresh pairing password, separate AES key, and message. No website-to-website request or provisioning route was added to Communication/Base Station. Plain HTTP remains explicitly labelled a classroom-only demo gate, not secure authentication; LAN exposure and no-public-exposure warnings remain prominent. A reset clears ESP RAM state, so a later connection attempt needs fresh Key Generator provisioning. No ESP hardware or real credentials were used for verification or preview capture.

Verification results for this revision are recorded in its delivery notes. Synthetic UI previews are stored in the sibling `*-esp-pairing-gate-previews/` folder rather than the reviewed source tree or archive.
