# UI previews

The Base Station entry preview is the actual pre-dashboard Communication gate: it shows only the ESP IP and pairing-password fields, with both blank, and no AES-key prompt. The obsolete in-dashboard password prompt has been removed from the packaged default/request images. All images are 1280 × 624 pixels.

| Preview | What it shows |
|---|---|
| `key_generator_default_bb84.png` | Key Generator default BB84 mode and existing teaching warnings. |
| `key_generator_aos_teaching_warning.png` | AOS teaching mode with the classroom-profile and plain-HTTP LAN warnings. |
| `key_generator_aos_message_encoder.png` | The 32-byte Data Field preview, 31-byte UTF-8 limit, message field, and one-shot provision control. The visible text “Preview message only” was an unsubmitted UI preview string. |
| `key_generator_os_csprng_mode.png` | Separate OS-CSPRNG mode before generation; no key was created. |
| `communication_base_station_default.png` | Current empty, pre-dashboard ESP Connection Gate. This is the primary Base Station preview. |
| `communication_gate_initial.png` | Same synthetic empty gate, included as the named gate-flow preview. |
| `communication_base_station_aos_request.png` | Refreshed to the current pre-dashboard gate; no password or AES-key prompt is shown inside the dashboard. |
| `communication_gate_error_wrong_password.png` | Synthetic wrong-password error state; no password value is shown. |
| `communication_dashboard_authenticated.png` | Synthetic authenticated Base Station dashboard after a successful local verification. |
| `communication_aos_frame_gcm_verified.png` | Synthetic AOS frame with local GCM verification passing. |
| `communication_aos_decoded_message.png` | Synthetic decoded message shown after local GCM and Data Field checks. |
| `communication_base_station_aos_intro.png` | AOS receiver overview and LAN-exposure warning. |
| `communication_base_station_ordinary_message.png` | The existing ordinary `/api/message` composer, shown separately from AOS; no send action occurred. |

The gate, authenticated, error, frame-verification, and decoded-message previews use synthetic-only state. No real ESP, external request, password, or AES key was used for these previews. The ordinary `/api/message` route remains separate from AOS provisioning and pairing.
