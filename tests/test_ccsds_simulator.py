import binascii
import unittest

import ccsds_simulator as sim


PACKET_VECTOR = bytes.fromhex("0123c02a0002010203")
TC_TYPE_AD_VECTOR = bytes.fromhex("01550c0fff0123c02a00020102033f92")
TM_PACKET_VECTOR = bytes.fromhex("1556123418000123c02a0002010203fdb5")


class SpacePacketTests(unittest.TestCase):
    def test_primary_header_known_vector(self):
        encoded = sim.encode_space_packet(
            bytes.fromhex("010203"),
            apid=0x123,
            packet_type=0,
            sequence_flags=0b11,
            sequence_value=0x2A,
        )
        self.assertEqual(encoded, PACKET_VECTOR)
        decoded = sim.decode_space_packet(PACKET_VECTOR)
        self.assertEqual(decoded["packet_version_number"], 0)
        self.assertEqual((encoded[0] >> 5) & 0b111, 0b000)
        self.assertEqual(decoded["packet_type"], 0)
        self.assertFalse(decoded["secondary_header_flag"])
        self.assertEqual(decoded["apid"], 0x123)
        self.assertEqual(decoded["sequence_flags"], 0b11)
        self.assertEqual(decoded["sequence_value"], 0x2A)
        self.assertEqual(decoded["packet_data_length_field"], 2)
        self.assertEqual(decoded["data_field"], bytes.fromhex("010203"))

    def test_round_trip_telecommand_and_all_sequence_flag_values(self):
        for flags in range(4):
            with self.subTest(flags=flags):
                encoded = sim.encode_space_packet(
                    b"payload",
                    apid=17,
                    packet_type=1,
                    secondary_header_flag=True,
                    sequence_flags=flags,
                    sequence_value=0x3FFF,
                )
                decoded = sim.decode_space_packet(encoded)
                self.assertEqual(decoded["packet_type"], 1)
                self.assertTrue(decoded["secondary_header_flag"])
                self.assertEqual(decoded["sequence_flags"], flags)
                self.assertEqual(decoded["sequence_value"], 0x3FFF)
                self.assertEqual(decoded["data_field"], b"payload")

    def test_min_and_maximum_data_field_lengths(self):
        one_octet = sim.encode_space_packet(b"x", apid=1)
        self.assertEqual(len(one_octet), 7)
        maximum = sim.encode_space_packet(b"x" * 65_536, apid=1)
        self.assertEqual(len(maximum), 65_542)
        self.assertEqual(sim.decode_space_packet(maximum)["packet_data_length_field"], 0xFFFF)

    def test_invalid_fields_and_exact_length(self):
        for args in (
            {"data_field": b"", "apid": 1},
            {"data_field": b"x", "apid": 0x7FF},
            {"data_field": b"x", "apid": -1},
            {"data_field": b"x", "apid": 1, "packet_type": 2},
            {"data_field": b"x", "apid": 1, "sequence_flags": 4},
            {"data_field": b"x", "apid": 1, "sequence_value": 0x4000},
            {"data_field": b"x", "apid": 1, "secondary_header_flag": 1},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                sim.encode_space_packet(**args)

        with self.assertRaises(ValueError):
            sim.decode_space_packet(PACKET_VECTOR[:-1])
        with self.assertRaises(ValueError):
            sim.decode_space_packet(PACKET_VECTOR + b"\x00")
        unsupported_version = bytearray(PACKET_VECTOR)
        unsupported_version[0] |= 0x20
        with self.assertRaisesRegex(ValueError, "Space Packet Version 1.*PVN bits 000"):
            sim.decode_space_packet(unsupported_version)
        with self.assertRaisesRegex(ValueError, "APID 2047.*simulator's profile choice"):
            sim.encode_space_packet(b"x", apid=0x7FF)
        idle_apid = bytearray(PACKET_VECTOR)
        idle_apid[0] = (idle_apid[0] & 0xF8) | 0x07
        idle_apid[1] = 0xFF
        with self.assertRaisesRegex(ValueError, "APID 2047.*simulator's profile choice"):
            sim.decode_space_packet(idle_apid)


class TransferFrameTests(unittest.TestCase):
    def setUp(self):
        self.packet = PACKET_VECTOR

    def test_fecf_crc_parameters_against_independent_reference(self):
        reference = binascii.crc_hqx(b"123456789", 0xFFFF)
        self.assertEqual(reference, 0x29B1)
        self.assertEqual(sim.crc16_ccsds_fecf(b"123456789"), reference)

    def test_tc_type_ad_known_vector_and_round_trip(self):
        frame = sim.encode_tc_transfer_frame(
            self.packet,
            spacecraft_id=0x155,
            virtual_channel_id=3,
            frame_sequence_number=0xFF,
        )
        self.assertEqual(frame, TC_TYPE_AD_VECTOR)
        decoded = sim.decode_tc_transfer_frame(TC_TYPE_AD_VECTOR)
        self.assertEqual(decoded["frame_type"], "Type-AD")
        self.assertFalse(decoded["bypass_flag"])
        self.assertFalse(decoded["control_command_flag"])
        self.assertEqual(decoded["spacecraft_id"], 0x155)
        self.assertEqual(decoded["virtual_channel_id"], 3)
        self.assertEqual(decoded["frame_sequence_number"], 0xFF)
        self.assertEqual(decoded["frame_length_field"], len(TC_TYPE_AD_VECTOR) - 1)
        self.assertEqual(decoded["space_packet"]["data_field"], bytes.fromhex("010203"))

    def test_tm_known_vector_and_round_trip(self):
        frame = sim.encode_tm_transfer_frame(
            self.packet,
            spacecraft_id=0x155,
            virtual_channel_id=3,
            master_channel_frame_count=0x12,
            virtual_channel_frame_count=0x34,
        )
        self.assertEqual(frame, TM_PACKET_VECTOR)
        decoded = sim.decode_tm_transfer_frame(TM_PACKET_VECTOR)
        self.assertEqual(decoded["spacecraft_id"], 0x155)
        self.assertEqual(decoded["virtual_channel_id"], 3)
        self.assertEqual(decoded["master_channel_frame_count"], 0x12)
        self.assertEqual(decoded["virtual_channel_frame_count"], 0x34)
        self.assertEqual(decoded["segment_length_identifier"], 0b11)
        self.assertEqual(decoded["first_header_pointer"], 0)
        self.assertEqual(decoded["data_field"], PACKET_VECTOR)

    def test_tm_outputs_are_variable_length_layout_exercises(self):
        short_packet = sim.encode_space_packet(b"x", apid=1)
        long_packet = sim.encode_space_packet(b"longer sample", apid=1)
        short_layout = sim.encode_tm_transfer_frame(short_packet, spacecraft_id=1)
        long_layout = sim.encode_tm_transfer_frame(long_packet, spacecraft_id=1)
        self.assertEqual(len(short_layout), 6 + len(short_packet) + 2)
        self.assertEqual(len(long_layout), 6 + len(long_packet) + 2)
        self.assertNotEqual(len(short_layout), len(long_layout))
        tm_doc = " ".join(sim.encode_tm_transfer_frame.__doc__.split())
        self.assertIn("not a standard-valid TM channel frame", tm_doc)
        self.assertIn("§4.1.1.2", tm_doc)

    def test_tc_invalid_type_length_and_frame_integrity(self):
        bad_type = bytearray(TC_TYPE_AD_VECTOR)
        bad_type[0] |= 0x20  # Bypass Flag = 1 (Type-B, unsupported here).
        with self.assertRaisesRegex(ValueError, "Type-AD"):
            sim.decode_tc_transfer_frame(bad_type)

        bad_length = bytearray(TC_TYPE_AD_VECTOR)
        bad_length[3] ^= 1
        with self.assertRaisesRegex(ValueError, "Frame Length"):
            sim.decode_tc_transfer_frame(bad_length)

        bad_crc = bytearray(TC_TYPE_AD_VECTOR)
        bad_crc[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "FECF mismatch"):
            sim.decode_tc_transfer_frame(bad_crc)

        too_large_packet = sim.encode_space_packet(b"x" * 1012, apid=1)
        with self.assertRaisesRegex(ValueError, "1024-octet"):
            sim.encode_tc_transfer_frame(too_large_packet, spacecraft_id=1)

    def test_tm_rejects_unsupported_header_and_bad_fecf(self):
        bad_pointer = bytearray(TM_PACKET_VECTOR)
        bad_pointer[5] |= 1
        with self.assertRaisesRegex(ValueError, "First Header Pointer"):
            sim.decode_tm_transfer_frame(bad_pointer)

        bad_ocf = bytearray(TM_PACKET_VECTOR)
        bad_ocf[1] |= 1
        with self.assertRaisesRegex(ValueError, "Operational Control Field"):
            sim.decode_tm_transfer_frame(bad_ocf)

        bad_crc = bytearray(TM_PACKET_VECTOR)
        bad_crc[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "FECF mismatch"):
            sim.decode_tm_transfer_frame(bad_crc)

        with self.assertRaises(ValueError):
            sim.encode_tm_transfer_frame(self.packet, spacecraft_id=0x400)


class Cop1TeachingTraceTests(unittest.TestCase):
    def test_lost_clcw_timeout_retry_duplicate_and_ack_with_wrap(self):
        trace = sim.simulate_cop1_scenario()
        event_names = [item["event"] for item in trace["events"]]
        self.assertEqual(
            event_names,
            [
                "type_ad_frame_sent",
                "farm_accept_in_sequence",
                "clcw_generated_but_lost",
                "t1_timeout",
                "ad_retransmission_started",
                "type_ad_frame_retransmitted",
                "farm_discard_duplicate",
                "clcw_reported",
                "clcw_acknowledged_frame",
            ],
        )
        self.assertTrue(trace["completed"])
        self.assertEqual(trace["delivered_frame_count"], 1)
        self.assertEqual(trace["profile"]["fop_sliding_window_width_k"], 1)
        self.assertEqual(trace["profile"]["farm_sliding_window_width_w"], 2)
        self.assertEqual(trace["profile"]["farm_positive_window_width_pw"], 1)
        self.assertEqual(trace["profile"]["farm_negative_window_width_nw"], 1)
        self.assertIn("configured teaching-simulator default 3", trace["profile"]["transmission_limit"])
        self.assertIn("not a CCSDS default", trace["profile"]["transmission_limit"])
        self.assertIn("abstract teaching labels", trace["profile"]["state_labels"])
        self.assertEqual(trace["initial_state"]["fop"]["state"], "TEACHING_ACTIVE")
        self.assertEqual(trace["initial_state"]["farm"]["state"], "TEACHING_OPEN")
        self.assertFalse(any(item["state"]["fop"]["state"].startswith("S") for item in trace["events"]))

        sent = trace["events"][0]["details"]
        retried = trace["events"][5]["details"]
        duplicate = trace["events"][6]["details"]
        ack = trace["events"][8]["details"]
        self.assertEqual(sent["n_s"], 255)
        self.assertEqual(retried["n_s"], 255)
        self.assertEqual(retried["transmission_count"], 2)
        self.assertFalse(duplicate["delivered_to_higher_procedure"])
        self.assertEqual(ack["n_r"], 0)
        self.assertEqual(ack["acknowledged_n_s"], [255])
        self.assertEqual(trace["final_state"]["fop"]["v_s"], 0)
        self.assertEqual(trace["final_state"]["fop"]["nn_r"], 0)
        self.assertEqual(trace["final_state"]["fop"]["sent_queue"], [])
        self.assertFalse(trace["final_state"]["fop"]["timer_running"])
        self.assertEqual(trace["final_state"]["farm"]["v_r"], 0)
        self.assertEqual(trace["final_state"]["farm"]["delivered_frame_sequence_numbers"], [255])

    def test_transmission_limit_one_takes_timeout_alert_path(self):
        trace = sim.simulate_cop1_scenario(initial_sequence_number=4, transmission_limit=1)
        self.assertFalse(trace["completed"])
        self.assertEqual(trace["events"][-1]["event"], "ad_service_alert_t1")
        self.assertEqual(trace["final_state"]["fop"]["state"], "TEACHING_TIMEOUT_ALERT")
        self.assertNotIn("type_ad_frame_retransmitted", [e["event"] for e in trace["events"]])

    def test_invalid_cop_profile_arguments(self):
        for kwargs in (
            {"initial_sequence_number": -1},
            {"initial_sequence_number": 256},
            {"transmission_limit": 0},
            {"transmission_limit": 256},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                sim.simulate_cop1_scenario(**kwargs)


if __name__ == "__main__":
    unittest.main()
