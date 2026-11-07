"""Presentation-layer helpers for the separate offline CCSDS learning tab.

This module only composes pure functions from :mod:`ccsds_simulator`. It has
no live ESP client, networking, hardware, key-generation, or crypto behavior.
"""

from __future__ import annotations

from typing import Any

from ccsds_simulator import (
    crc16_ccsds_fecf,
    decode_space_packet,
    decode_tc_transfer_frame,
    decode_tm_transfer_frame,
    encode_space_packet,
    encode_tc_transfer_frame,
    encode_tm_transfer_frame,
    simulate_cop1_scenario,
)


SPP_MODE = "Space Packet Version 1 (SPP; PVN bits 000)"
TC_MODE = "TC Type-AD Transfer Frame"
TM_MODE = "TM variable-length offline layout exercise"
FRAME_MODES = (SPP_MODE, TC_MODE, TM_MODE)


def build_ccsds_learning_frame(
    sample_text: str,
    frame_mode: str,
    *,
    apid: int,
    packet_type: int = 0,
    secondary_header_flag: bool = False,
    sequence_flags: int = 3,
    sequence_value: int = 0,
    spacecraft_id: int = 1,
    tc_virtual_channel_id: int = 0,
    tc_frame_sequence_number: int = 0,
    tm_virtual_channel_id: int = 0,
    tm_master_channel_frame_count: int = 0,
    tm_virtual_channel_frame_count: int = 0,
) -> dict[str, Any]:
    """Build one selected offline teaching layout, then decode it locally."""
    if not isinstance(sample_text, str):
        raise ValueError("sample_text must be text")
    if frame_mode not in FRAME_MODES:
        raise ValueError(f"frame_mode must be one of: {', '.join(FRAME_MODES)}")
    try:
        data_field = sample_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("sample_text must contain valid UTF-8 text") from exc

    space_packet = encode_space_packet(
        data_field,
        apid=apid,
        packet_type=packet_type,
        secondary_header_flag=secondary_header_flag,
        sequence_flags=sequence_flags,
        sequence_value=sequence_value,
    )
    decoded_packet = decode_space_packet(space_packet)

    fecf_computed: int | None = None
    fecf_received: int | None = None
    fecf_valid: bool | None = None
    profile_notice: str

    if frame_mode == SPP_MODE:
        profile_notice = "Space Packet Version 1 is encoded with PVN bits 000."
        frame = space_packet
        decoded_frame = decoded_packet
        length_valid = (
            decoded_packet["packet_data_length_field"] + 1 == len(data_field)
            and decoded_packet["total_length"] == len(frame)
        )
        length_check = "Space Packet Version 1 Packet Data Length + 1 equals data-field octets; total packet length agrees."
        selected_header_fields = {
            key: decoded_packet[key]
            for key in (
                "packet_version_number",
                "packet_type",
                "secondary_header_flag",
                "apid",
                "sequence_flags",
                "sequence_value",
                "packet_data_length_field",
            )
        }
        fecf_check = "Not applicable: Space Packet Version 1 has no FECF field in this profile."
        decoded_data = decoded_packet["data_field"]
        decoded_packet_bytes = frame
    elif frame_mode == TC_MODE:
        profile_notice = (
            "TC Type-AD, FECF presence, and exactly one complete Space Packet Version 1 per frame are "
            "selected teaching-profile constraints, not broad TC compliance."
        )
        frame = encode_tc_transfer_frame(
            space_packet,
            spacecraft_id=spacecraft_id,
            virtual_channel_id=tc_virtual_channel_id,
            frame_sequence_number=tc_frame_sequence_number,
        )
        decoded_frame = decode_tc_transfer_frame(frame)
        length_valid = (
            decoded_frame["frame_length_field"] + 1 == len(frame)
            and decoded_frame["total_length"] == len(frame)
        )
        length_check = "TC Frame Length + 1 equals the total transfer-frame octet count."
        selected_header_fields = {
            key: decoded_frame[key]
            for key in (
                "transfer_frame_version_number",
                "bypass_flag",
                "control_command_flag",
                "frame_type",
                "reserved_spare",
                "spacecraft_id",
                "virtual_channel_id",
                "frame_length_field",
                "frame_sequence_number",
            )
        }
        fecf_computed = crc16_ccsds_fecf(frame[:-2])
        fecf_received = int.from_bytes(frame[-2:], "big")
        fecf_valid = fecf_computed == fecf_received == decoded_frame["fecf"]
        fecf_check = "TC FECF matches CRC-16/CCSDS over the frame excluding its final two FECF octets."
        decoded_data = decoded_frame["space_packet"]["data_field"]
        decoded_packet_bytes = decoded_frame["data_field"]
    else:
        profile_notice = (
            "Variable-length offline TM layout exercise; not a standard-valid TM channel frame. "
            "Header options are fixed, but output length varies with the packet. This does not model CCSDS TM "
            "constant length per channel during a Mission Phase (§4.1.1.2); FECF layout reference: §4.1.6.2, "
            "pp. 4-13–4-14."
        )
        frame = encode_tm_transfer_frame(
            space_packet,
            spacecraft_id=spacecraft_id,
            virtual_channel_id=tm_virtual_channel_id,
            master_channel_frame_count=tm_master_channel_frame_count,
            virtual_channel_frame_count=tm_virtual_channel_frame_count,
        )
        decoded_frame = decode_tm_transfer_frame(frame)
        length_valid = (
            decoded_frame["total_length"] == len(frame)
            and len(frame) == 6 + len(space_packet) + 2
            and decoded_frame["data_field"] == space_packet
        )
        length_check = (
            "Variable-length offline TM layout check: 6-octet header + one complete Space Packet Version 1 "
            "+ 2-octet FECF equals this example's total length; not a standard-valid channel-frame check."
        )
        selected_header_fields = {
            key: decoded_frame[key]
            for key in (
                "transfer_frame_version_number",
                "spacecraft_id",
                "virtual_channel_id",
                "ocf_flag",
                "master_channel_frame_count",
                "virtual_channel_frame_count",
                "tf_secondary_header_flag",
                "synchronization_flag",
                "packet_order_flag",
                "segment_length_identifier",
                "first_header_pointer",
            )
        }
        fecf_computed = crc16_ccsds_fecf(frame[:-2])
        fecf_received = int.from_bytes(frame[-2:], "big")
        fecf_valid = fecf_computed == fecf_received == decoded_frame["fecf"]
        fecf_check = "TM FECF matches CRC-16/CCSDS over the frame excluding its final two FECF octets."
        decoded_data = decoded_frame["space_packet"]["data_field"]
        decoded_packet_bytes = decoded_frame["data_field"]

    round_trip_valid = (
        decoded_data == data_field
        and decoded_packet_bytes == space_packet
        and decoded_packet["data_field"] == data_field
    )
    if fecf_valid is None:
        overall_valid = length_valid and round_trip_valid
    else:
        overall_valid = length_valid and fecf_valid and round_trip_valid

    return {
        "frame_mode": frame_mode,
        "data_field": data_field,
        "space_packet": space_packet,
        "decoded_space_packet": decoded_packet,
        "frame": frame,
        "decoded_frame": decoded_frame,
        "selected_header_fields": selected_header_fields,
        "profile_notice": profile_notice,
        "length_valid": length_valid,
        "length_check": length_check,
        "fecf_computed": fecf_computed,
        "fecf_received": fecf_received,
        "fecf_valid": fecf_valid,
        "fecf_check": fecf_check,
        "round_trip_valid": round_trip_valid,
        "overall_valid": overall_valid,
    }


def build_cop1_learning_trace(
    *, initial_sequence_number: int = 255, transmission_limit: int = 3
) -> dict[str, Any]:
    """Return the simulator's explicitly bounded deterministic COP-1 trace."""
    return simulate_cop1_scenario(
        initial_sequence_number=initial_sequence_number,
        transmission_limit=transmission_limit,
    )


__all__ = [
    "FRAME_MODES",
    "SPP_MODE",
    "TC_MODE",
    "TM_MODE",
    "build_ccsds_learning_frame",
    "build_cop1_learning_trace",
]
