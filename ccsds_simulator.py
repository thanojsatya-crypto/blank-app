"""Offline CCSDS teaching helpers; deliberately not a flight or compliance stack.

Implemented profiles are documented in CCSDS_PROFILE.md. This module is pure:
it performs no I/O, network access, hardware access, key generation, or ESP calls.
"""

from __future__ import annotations

from typing import Any


_SPACE_PACKET_PRIMARY_HEADER_LENGTH = 6
_MAX_SPACE_PACKET_DATA_LENGTH = 65_536
_MAX_APID = 0x7FF
_TC_PRIMARY_HEADER_LENGTH = 5
_TC_FECF_LENGTH = 2
_TM_PRIMARY_HEADER_LENGTH = 6
_TM_FECF_LENGTH = 2
_TM_DATA_FIELD_STATUS = 0x1800  # no TF secondary header, octet packets, SLID=11, FHP=0
_FECF_CRC_POLYNOMIAL = 0x1021
_FECF_CRC_INITIAL = 0xFFFF
_FECF_CRC_FINAL_XOR = 0x0000
_COP_FRAME_SEQUENCE_MODULUS = 256


def _require_uint(name: str, value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in the range 0..{maximum}")
    return value


def _require_bytes(name: str, value: Any) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(f"{name} must be bytes-like")
    return bytes(value)


def encode_space_packet(
    data_field: bytes,
    *,
    apid: int,
    packet_type: int = 0,
    secondary_header_flag: bool = False,
    sequence_flags: int = 0b11,
    sequence_value: int = 0,
) -> bytes:
    """Encode one Space Packet Version 1 (PVN bits ``000``) teaching example.

    ``sequence_value`` is the 14-bit Packet Sequence Count for telemetry and
    may represent a mission-defined sequence count or packet name for
    telecommand. The packet data field is opaque and must contain 1..65536
    octets; mission-specific secondary-header contents are not interpreted.
    APID 2047 is reserved as the Idle Packet APID and is rejected as this
    simulator's teaching-profile choice, not as a general CCSDS prohibition.
    """
    payload = _require_bytes("data_field", data_field)
    apid = _require_uint("apid", apid, _MAX_APID)
    if apid == _MAX_APID:
        raise ValueError(
            "APID 2047 is reserved as the Idle Packet APID; rejection is this simulator's profile choice"
        )
    packet_type = _require_uint("packet_type", packet_type, 1)
    sequence_flags = _require_uint("sequence_flags", sequence_flags, 3)
    sequence_value = _require_uint("sequence_value", sequence_value, 0x3FFF)
    if not isinstance(secondary_header_flag, bool):
        raise ValueError("secondary_header_flag must be bool")
    if not 1 <= len(payload) <= _MAX_SPACE_PACKET_DATA_LENGTH:
        raise ValueError("data_field length must be in the range 1..65536 octets")

    packet_identification = (packet_type << 12) | (int(secondary_header_flag) << 11) | apid
    packet_sequence_control = (sequence_flags << 14) | sequence_value
    packet_data_length = len(payload) - 1
    return (
        packet_identification.to_bytes(2, "big")
        + packet_sequence_control.to_bytes(2, "big")
        + packet_data_length.to_bytes(2, "big")
        + payload
    )


def decode_space_packet(packet: bytes) -> dict[str, Any]:
    """Decode exactly one complete Space Packet Version 1 (PVN bits ``000``).

    Raises ``ValueError`` for unsupported versions/APIDs, truncated packets,
    or trailing bytes inconsistent with the primary-header length field.
    """
    raw = _require_bytes("packet", packet)
    if len(raw) < _SPACE_PACKET_PRIMARY_HEADER_LENGTH + 1:
        raise ValueError("Space Packet must contain a 6-octet header and at least 1 data octet")
    if len(raw) > _SPACE_PACKET_PRIMARY_HEADER_LENGTH + _MAX_SPACE_PACKET_DATA_LENGTH:
        raise ValueError("Space Packet exceeds the CCSDS maximum length")

    packet_identification = int.from_bytes(raw[0:2], "big")
    packet_sequence_control = int.from_bytes(raw[2:4], "big")
    packet_data_length = int.from_bytes(raw[4:6], "big")

    packet_version_number = (packet_identification >> 13) & 0b111
    if packet_version_number != 0:
        raise ValueError("only Space Packet Version 1 encoded with PVN bits 000 is supported")

    packet_type = (packet_identification >> 12) & 1
    secondary_header_flag = bool((packet_identification >> 11) & 1)
    apid = packet_identification & 0x7FF
    if apid == 0x7FF:
        raise ValueError(
            "APID 2047 is reserved as the Idle Packet APID; rejection is this simulator's profile choice"
        )

    data_field_length = packet_data_length + 1
    expected_length = _SPACE_PACKET_PRIMARY_HEADER_LENGTH + data_field_length
    if len(raw) != expected_length:
        raise ValueError(
            f"Space Packet length mismatch: header declares {expected_length} octets, received {len(raw)}"
        )

    return {
        "packet_version_number": packet_version_number,
        "packet_type": packet_type,
        "secondary_header_flag": secondary_header_flag,
        "apid": apid,
        "sequence_flags": (packet_sequence_control >> 14) & 0b11,
        "sequence_value": packet_sequence_control & 0x3FFF,
        "packet_data_length_field": packet_data_length,
        "data_field": raw[_SPACE_PACKET_PRIMARY_HEADER_LENGTH:],
        "total_length": len(raw),
    }


def crc16_ccsds_fecf(data: bytes) -> int:
    """Return the CCSDS TC/TM FECF CRC-16 value for ``data``.

    Parameters: width 16, polynomial x^16+x^12+x^5+1 (0x1021), initial
    register 0xFFFF, MSB-first, no reflection, final XOR 0. These parameters are defined by CCSDS 132.0-B-3 section 4.1.6.2
    and CCSDS 232.0-B-4 section 4.1.4.2.
    """
    raw = _require_bytes("data", data)
    crc = _FECF_CRC_INITIAL
    for octet in raw:
        crc ^= octet << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _FECF_CRC_POLYNOMIAL) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc ^ _FECF_CRC_FINAL_XOR


def encode_tc_transfer_frame(
    space_packet: bytes,
    *,
    spacecraft_id: int,
    virtual_channel_id: int = 0,
    frame_sequence_number: int = 0,
) -> bytes:
    """Encode one TC Type-AD offline teaching-profile frame.

    Profile: TC Version 1, Bypass Flag 0, Control Command Flag 0 (Type-AD),
    Reserved Spare 00, no Segment Header, and FECF present. The data field is
    exactly one complete supported Space Packet; no SDLS or channel coding is
    added. Type-AD, FECF presence, and one complete packet are selected
    teaching-profile constraints, not a claim of broad TC compliance. The
    10-bit Frame Length is the entire frame length minus one.
    """
    packet = _require_bytes("space_packet", space_packet)
    decode_space_packet(packet)
    spacecraft_id = _require_uint("spacecraft_id", spacecraft_id, 0x3FF)
    virtual_channel_id = _require_uint("virtual_channel_id", virtual_channel_id, 0x3F)
    frame_sequence_number = _require_uint("frame_sequence_number", frame_sequence_number, 0xFF)

    frame_without_fecf_length = _TC_PRIMARY_HEADER_LENGTH + len(packet)
    total_length = frame_without_fecf_length + _TC_FECF_LENGTH
    if total_length > 1024:
        raise ValueError("TC Transfer Frame exceeds the 1024-octet maximum")
    frame_length_field = total_length - 1

    # Primary Header: TFVN(2), Bypass(1), Control(1), Spare(2), SCID(10).
    first_header_word = spacecraft_id
    # VCID(6) followed by Frame Length(10).
    second_header_word = (virtual_channel_id << 10) | frame_length_field
    primary_header = (
        first_header_word.to_bytes(2, "big")
        + second_header_word.to_bytes(2, "big")
        + bytes((frame_sequence_number,))
    )
    frame_without_fecf = primary_header + packet
    fecf = crc16_ccsds_fecf(frame_without_fecf)
    return frame_without_fecf + fecf.to_bytes(2, "big")


def decode_tc_transfer_frame(frame: bytes) -> dict[str, Any]:
    """Decode one TC Type-AD frame under this teaching profile.

    Type-AD, FECF presence, and exactly one complete Space Packet are selected
    teaching-profile constraints, not broad TC compliance.
    """
    raw = _require_bytes("frame", frame)
    minimum_length = _TC_PRIMARY_HEADER_LENGTH + 7 + _TC_FECF_LENGTH
    if len(raw) < minimum_length:
        raise ValueError(f"TC Transfer Frame is shorter than {minimum_length} octets")

    first_header_word = int.from_bytes(raw[0:2], "big")
    version_number = (first_header_word >> 14) & 0b11
    bypass_flag = (first_header_word >> 13) & 1
    control_command_flag = (first_header_word >> 12) & 1
    reserved_spare = (first_header_word >> 10) & 0b11
    spacecraft_id = first_header_word & 0x3FF
    if version_number != 0:
        raise ValueError("only TC Transfer Frame Version Number 0 is supported")
    if bypass_flag != 0 or control_command_flag != 0:
        raise ValueError("only Type-AD TC Transfer Frames are supported")
    if reserved_spare != 0:
        raise ValueError("TC Reserved Spare bits must be zero")

    second_header_word = int.from_bytes(raw[2:4], "big")
    virtual_channel_id = (second_header_word >> 10) & 0x3F
    frame_length_field = second_header_word & 0x3FF
    expected_length = frame_length_field + 1
    if expected_length != len(raw):
        raise ValueError(
            f"TC Frame Length declares {expected_length} octets, received {len(raw)}"
        )

    frame_without_fecf = raw[:-_TC_FECF_LENGTH]
    received_fecf = int.from_bytes(raw[-_TC_FECF_LENGTH:], "big")
    expected_fecf = crc16_ccsds_fecf(frame_without_fecf)
    if received_fecf != expected_fecf:
        raise ValueError(
            f"TC FECF mismatch: received 0x{received_fecf:04X}, expected 0x{expected_fecf:04X}"
        )

    data_field = raw[_TC_PRIMARY_HEADER_LENGTH:-_TC_FECF_LENGTH]
    decoded_packet = decode_space_packet(data_field)
    return {
        "transfer_frame_version_number": version_number,
        "bypass_flag": False,
        "control_command_flag": False,
        "frame_type": "Type-AD",
        "reserved_spare": reserved_spare,
        "spacecraft_id": spacecraft_id,
        "virtual_channel_id": virtual_channel_id,
        "frame_length_field": frame_length_field,
        "frame_sequence_number": raw[4],
        "data_field": data_field,
        "space_packet": decoded_packet,
        "fecf": received_fecf,
        "total_length": len(raw),
    }


def encode_tm_transfer_frame(
    space_packet: bytes,
    *,
    spacecraft_id: int,
    virtual_channel_id: int = 0,
    master_channel_frame_count: int = 0,
    virtual_channel_frame_count: int = 0,
) -> bytes:
    """Encode a variable-length offline TM layout exercise.

    Profile: TM Version 1, SCID 10 bits, VCID 3 bits, OCF absent, Transfer
    Frame Secondary Header absent, octet-synchronized packet mode, Packet
    Order Flag 0, Segment Length Identifier ``11``, First Header Pointer 0,
    FECF present. The supplied bytes must be exactly one supported Space
    Packet; no padding, idle data, or packet spanning is added. This is not a
    standard-valid TM channel frame and does not model the CCSDS TM
    constant-length-per-channel-during-a-Mission-Phase requirement (§4.1.1.2).
    Header options are fixed for this layout; output length varies with packet
    length.
    """
    packet = _require_bytes("space_packet", space_packet)
    decode_space_packet(packet)
    spacecraft_id = _require_uint("spacecraft_id", spacecraft_id, 0x3FF)
    virtual_channel_id = _require_uint("virtual_channel_id", virtual_channel_id, 0b111)
    master_channel_frame_count = _require_uint(
        "master_channel_frame_count", master_channel_frame_count, 0xFF
    )
    virtual_channel_frame_count = _require_uint(
        "virtual_channel_frame_count", virtual_channel_frame_count, 0xFF
    )

    # The 2-bit TM Transfer Frame Version Number and OCF flag are both zero.
    first_header_word = (spacecraft_id << 4) | (virtual_channel_id << 1)
    primary_header = (
        first_header_word.to_bytes(2, "big")
        + bytes((master_channel_frame_count, virtual_channel_frame_count))
        + _TM_DATA_FIELD_STATUS.to_bytes(2, "big")
    )
    frame_without_fecf = primary_header + packet
    fecf = crc16_ccsds_fecf(frame_without_fecf)
    return frame_without_fecf + fecf.to_bytes(2, "big")


def decode_tm_transfer_frame(frame: bytes) -> dict[str, Any]:
    """Decode one variable-length offline TM layout exercise.

    The frame must contain exactly one complete supported Space Packet in its
    data field. Unsupported header options and a bad FECF raise ``ValueError``.
    A passing local decode does not make this a standard-valid TM channel frame
    or check the CCSDS constant-length-per-channel-during-a-Mission-Phase rule.
    """
    raw = _require_bytes("frame", frame)
    minimum_length = _TM_PRIMARY_HEADER_LENGTH + 7 + _TM_FECF_LENGTH
    if len(raw) < minimum_length:
        raise ValueError(f"TM Transfer Frame is shorter than {minimum_length} octets")

    first_header_word = int.from_bytes(raw[0:2], "big")
    frame_version_number = (first_header_word >> 14) & 0b11
    if frame_version_number != 0:
        raise ValueError("only TM Transfer Frame Version Number 0 is supported")
    spacecraft_id = (first_header_word >> 4) & 0x3FF
    virtual_channel_id = (first_header_word >> 1) & 0b111
    ocf_flag = first_header_word & 1
    if ocf_flag:
        raise ValueError("Operational Control Field is unsupported by this profile")

    data_field_status = int.from_bytes(raw[4:6], "big")
    tf_secondary_header_flag = (data_field_status >> 15) & 1
    synchronization_flag = (data_field_status >> 14) & 1
    packet_order_flag = (data_field_status >> 13) & 1
    segment_length_identifier = (data_field_status >> 11) & 0b11
    first_header_pointer = data_field_status & 0x7FF
    if tf_secondary_header_flag != 0:
        raise ValueError("Transfer Frame Secondary Header is unsupported by this profile")
    if synchronization_flag != 0:
        raise ValueError("only octet-synchronized packet mode is supported")
    if packet_order_flag != 0:
        raise ValueError("nonzero Packet Order Flag is unsupported by this profile")
    if segment_length_identifier != 0b11:
        raise ValueError("octet-synchronized packet mode requires Segment Length Identifier 11")
    if first_header_pointer != 0:
        raise ValueError("profile requires exactly one packet starting at First Header Pointer 0")

    frame_without_fecf = raw[:-_TM_FECF_LENGTH]
    received_fecf = int.from_bytes(raw[-_TM_FECF_LENGTH:], "big")
    expected_fecf = crc16_ccsds_fecf(frame_without_fecf)
    if received_fecf != expected_fecf:
        raise ValueError(
            f"TM FECF mismatch: received 0x{received_fecf:04X}, expected 0x{expected_fecf:04X}"
        )

    data_field = raw[_TM_PRIMARY_HEADER_LENGTH:-_TM_FECF_LENGTH]
    decoded_packet = decode_space_packet(data_field)
    return {
        "transfer_frame_version_number": frame_version_number,
        "spacecraft_id": spacecraft_id,
        "virtual_channel_id": virtual_channel_id,
        "ocf_flag": False,
        "master_channel_frame_count": raw[2],
        "virtual_channel_frame_count": raw[3],
        "tf_secondary_header_flag": False,
        "synchronization_flag": False,
        "packet_order_flag": False,
        "segment_length_identifier": segment_length_identifier,
        "first_header_pointer": first_header_pointer,
        "data_field": data_field,
        "space_packet": decoded_packet,
        "fecf": received_fecf,
        "total_length": len(raw),
    }


def _cop_state_snapshot(
    *,
    v_s: int,
    nn_r: int,
    sent_queue: list[int],
    transmission_count: int,
    timer_running: bool,
    v_r: int,
    delivered_frames: list[int],
    retransmit_flag: bool = False,
    wait_flag: bool = False,
    lockout_flag: bool = False,
    fop_state: str = "TEACHING_ACTIVE",
    farm_state: str = "TEACHING_OPEN",
) -> dict[str, Any]:
    return {
        "fop": {
            "state": fop_state,
            "v_s": v_s,
            "nn_r": nn_r,
            "sent_queue": list(sent_queue),
            "transmission_count": transmission_count,
            "timer_running": timer_running,
        },
        "farm": {
            "state": farm_state,
            "v_r": v_r,
            "delivered_frame_sequence_numbers": list(delivered_frames),
            "retransmit_flag": retransmit_flag,
            "wait_flag": wait_flag,
            "lockout_flag": lockout_flag,
        },
    }


def simulate_cop1_scenario(
    *,
    initial_sequence_number: int = 255,
    transmission_limit: int = 3,
) -> dict[str, Any]:
    """Return a deterministic one-frame COP-1 teaching trace.

    The precondition is an already-active AD Service with one frame available.
    The modeled scenario accepts the first frame at FARM-1 but loses its CLCW;
    after an injected symbolic T1 timeout, FOP-1 retransmits it. FARM-1
    discards the duplicate inside the configured negative window and its next
    CLCW acknowledges the frame. No wall-clock timer or link is used.

    This is a bounded trace, not a complete FOP-1/FARM-1 implementation. State
    labels are abstract teaching labels, not normative FOP/FARM states or a
    standard transition model. ``transmission_limit`` defaults to this
    simulator's configured value of 3; it is not a CCSDS default. With
    ``transmission_limit=1`` this teaching trace shows its timeout-alert branch.
    """
    initial_sequence_number = _require_uint(
        "initial_sequence_number", initial_sequence_number, 0xFF
    )
    transmission_limit = _require_uint("transmission_limit", transmission_limit, 0xFF)
    if transmission_limit < 1:
        raise ValueError("transmission_limit must be at least 1")

    sequence_number = initial_sequence_number
    v_s = sequence_number
    v_r = sequence_number
    nn_r = sequence_number
    sent_queue: list[int] = []
    delivered_frames: list[int] = []
    transmission_count = 0
    timer_running = False
    fop_state = "TEACHING_ACTIVE"
    farm_state = "TEACHING_OPEN"
    events: list[dict[str, Any]] = []

    def snapshot() -> dict[str, Any]:
        return _cop_state_snapshot(
            v_s=v_s,
            nn_r=nn_r,
            sent_queue=sent_queue,
            transmission_count=transmission_count,
            timer_running=timer_running,
            v_r=v_r,
            delivered_frames=delivered_frames,
            fop_state=fop_state,
            farm_state=farm_state,
        )

    def record(event: str, side: str, details: dict[str, Any]) -> None:
        events.append(
            {
                "step": len(events) + 1,
                "event": event,
                "side": side,
                "details": details,
                "state": snapshot(),
            }
        )

    initial_state = snapshot()

    # COP-1 5.2.4: allocate N(S)=V(S), increment V(S), queue, count=1, start T1.
    transmission_count = 1
    sent_queue.append(sequence_number)
    v_s = (v_s + 1) % _COP_FRAME_SEQUENCE_MODULUS
    timer_running = True
    record(
        "type_ad_frame_sent",
        "fop",
        {"n_s": sequence_number, "transmission_count": transmission_count, "retransmission": False},
    )

    # FARM-1 E1: the in-sequence AD frame is delivered exactly once; V(R) advances.
    v_r = (v_r + 1) % _COP_FRAME_SEQUENCE_MODULUS
    delivered_frames.append(sequence_number)
    record(
        "farm_accept_in_sequence",
        "farm",
        {
            "n_s": sequence_number,
            "v_r_after": v_r,
            "delivered_to_higher_procedure": True,
        },
    )

    first_nr = v_r
    record(
        "clcw_generated_but_lost",
        "link_simulation",
        {
            "n_r": first_nr,
            "retransmit_flag": False,
            "wait_flag": False,
            "lockout_flag": False,
        },
    )

    # COP-1 FOP-1 Table 5-1 E16 / 5.1.10.5: timeout, then retry if limit remains.
    timer_running = False
    record(
        "t1_timeout",
        "fop",
        {
            "transmission_count": transmission_count,
            "transmission_limit": transmission_limit,
            "timeout_type": 0,
            "timeout_is_symbolic_not_elapsed_wall_time": True,
        },
    )

    if transmission_count >= transmission_limit:
        fop_state = "TEACHING_TIMEOUT_ALERT"
        record(
            "ad_service_alert_t1",
            "fop",
            {"reason": "Transmission_Count reached Transmission_Limit", "retry_started": False},
        )
        return {
            "profile": _cop_profile(),
            "initial_state": initial_state,
            "final_state": snapshot(),
            "events": events,
            "state_trace": [event["state"] for event in events],
            "completed": False,
            "delivered_frame_count": len(delivered_frames),
        }

    # COP-1 5.2.7: increment transmission count, restart T1, mark frame for retry.
    transmission_count += 1
    timer_running = True
    record(
        "ad_retransmission_started",
        "fop",
        {"n_s": sequence_number, "transmission_count": transmission_count},
    )
    record(
        "type_ad_frame_retransmitted",
        "fop",
        {"n_s": sequence_number, "transmission_count": transmission_count, "retransmission": True},
    )

    # FARM-1 E4: one-behind duplicate in the negative receive window is discarded.
    backwards_distance = (v_r - sequence_number) % _COP_FRAME_SEQUENCE_MODULUS
    if not (1 <= backwards_distance <= 1):  # Profile NW=1; guard against trace drift.
        raise RuntimeError("scenario sequence is outside the configured FARM negative window")
    record(
        "farm_discard_duplicate",
        "farm",
        {
            "n_s": sequence_number,
            "v_r": v_r,
            "backwards_distance": backwards_distance,
            "delivered_to_higher_procedure": False,
        },
    )

    # FARM's current CLCW reports the already advanced V(R); abstract report path.
    acknowledgement_nr = v_r
    record(
        "clcw_reported",
        "farm",
        {
            "n_r": acknowledgement_nr,
            "retransmit_flag": False,
            "wait_flag": False,
            "lockout_flag": False,
            "transport": "abstracted; no TM OCF or radio modeled",
        },
    )

    # FOP-1 receives N(R)=V(S) and N(R)!=NN(R), removing the acknowledged frame.
    acknowledged = list(sent_queue)
    if acknowledgement_nr != v_s or acknowledgement_nr == nn_r:
        raise RuntimeError("scenario CLCW does not acknowledge the outstanding frame as profiled")
    sent_queue.clear()
    nn_r = acknowledgement_nr
    transmission_count = 1
    timer_running = False
    record(
        "clcw_acknowledged_frame",
        "fop",
        {
            "n_r": acknowledgement_nr,
            "acknowledged_n_s": acknowledged,
            "sent_queue_empty": not sent_queue,
            "timer_cancelled": True,
        },
    )

    return {
        "profile": _cop_profile(),
        "initial_state": initial_state,
        "final_state": snapshot(),
        "events": events,
        "state_trace": [event["state"] for event in events],
        "completed": True,
        "delivered_frame_count": len(delivered_frames),
    }


def _cop_profile() -> dict[str, Any]:
    return {
        "procedure": "COP-1 Issue 2 / FOP-1B and FARM-1 teaching subset",
        "service": "Type-AD, retransmission allowed",
        "transmission_limit": "configured teaching-simulator default 3; caller may override; counts original plus retries; not a CCSDS default",
        "timeout_type": 0,
        "t1_initial": "symbolic event only; no elapsed time is calculated",
        "fop_sliding_window_width_k": 1,
        "farm_sliding_window_width_w": 2,
        "farm_positive_window_width_pw": 1,
        "farm_negative_window_width_nw": 1,
        "sequence_number_modulus": 256,
        "acknowledgement_rule": "CLCW N(R) reports FARM-1 V(R), the next expected Type-AD N(S)",
        "state_labels": "abstract teaching labels; not normative FOP/FARM states or standard transitions",
        "scope": "already-active single-VC session; one in-sequence frame; one lost CLCW; at most one retry in this trace",
    }


__all__ = [
    "crc16_ccsds_fecf",
    "decode_space_packet",
    "decode_tc_transfer_frame",
    "decode_tm_transfer_frame",
    "encode_space_packet",
    "encode_tc_transfer_frame",
    "encode_tm_transfer_frame",
    "simulate_cop1_scenario",
]
