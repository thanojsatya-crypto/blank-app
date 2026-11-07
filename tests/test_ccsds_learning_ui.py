from __future__ import annotations

from pathlib import Path
import json
import unittest
from unittest.mock import patch

from ccsds_learning import (
    SPP_MODE,
    TC_MODE,
    TM_MODE,
    build_ccsds_learning_frame,
    build_cop1_learning_trace,
)
from esp_api import EspApiClient
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "communication_base_station.py"
PROJECT_ROOT = APP_PATH.parent
BOOT_ID = "0123456789abcdef0123456789abcdef"
PROVISION_ID = "11111111111111111111111111111111"


class CcsdsLearningFrameTests(unittest.TestCase):
    def test_spp_build_decode_and_length_round_trip(self):
        result = build_ccsds_learning_frame(
            "café",
            SPP_MODE,
            apid=0x123,
            packet_type=1,
            secondary_header_flag=True,
            sequence_flags=2,
            sequence_value=0x2A,
        )
        self.assertEqual(result["decoded_space_packet"]["data_field"], "café".encode("utf-8"))
        self.assertEqual(result["selected_header_fields"]["apid"], 0x123)
        self.assertEqual(result["selected_header_fields"]["packet_type"], 1)
        self.assertTrue(result["selected_header_fields"]["secondary_header_flag"])
        self.assertEqual(result["selected_header_fields"]["sequence_flags"], 2)
        self.assertEqual(result["selected_header_fields"]["sequence_value"], 0x2A)
        self.assertTrue(result["length_valid"])
        self.assertIsNone(result["fecf_valid"])
        self.assertTrue(result["round_trip_valid"])
        self.assertTrue(result["overall_valid"])
        self.assertIn("PVN bits 000", result["profile_notice"])

    def test_tc_type_ad_frame_fecf_and_selected_header_fields(self):
        result = build_ccsds_learning_frame(
            "telecommand sample",
            TC_MODE,
            apid=77,
            spacecraft_id=0x155,
            tc_virtual_channel_id=3,
            tc_frame_sequence_number=255,
        )
        self.assertEqual(result["decoded_frame"]["frame_type"], "Type-AD")
        self.assertEqual(result["selected_header_fields"]["spacecraft_id"], 0x155)
        self.assertEqual(result["selected_header_fields"]["virtual_channel_id"], 3)
        self.assertEqual(result["selected_header_fields"]["frame_sequence_number"], 255)
        self.assertEqual(result["decoded_frame"]["frame_length_field"] + 1, len(result["frame"]))
        self.assertTrue(result["length_valid"])
        self.assertTrue(result["fecf_valid"])
        self.assertTrue(result["round_trip_valid"])
        self.assertIn("selected teaching-profile constraints", result["profile_notice"])
        self.assertIn("not broad TC compliance", result["profile_notice"])

    def test_tm_variable_length_offline_layout_fields_fecf_and_round_trip(self):
        result = build_ccsds_learning_frame(
            "telemetry sample",
            TM_MODE,
            apid=19,
            spacecraft_id=0x2A5,
            tm_virtual_channel_id=7,
            tm_master_channel_frame_count=254,
            tm_virtual_channel_frame_count=12,
        )
        fields = result["selected_header_fields"]
        self.assertEqual(fields["spacecraft_id"], 0x2A5)
        self.assertEqual(fields["virtual_channel_id"], 7)
        self.assertEqual(fields["master_channel_frame_count"], 254)
        self.assertEqual(fields["virtual_channel_frame_count"], 12)
        self.assertFalse(fields["ocf_flag"])
        self.assertFalse(fields["tf_secondary_header_flag"])
        self.assertTrue(result["length_valid"])
        self.assertTrue(result["fecf_valid"])
        self.assertTrue(result["round_trip_valid"])
        self.assertTrue(result["overall_valid"])
        self.assertIn("Variable-length offline TM layout exercise", result["profile_notice"])
        self.assertIn("not a standard-valid TM channel frame", result["profile_notice"])
        self.assertIn("constant length per channel during a Mission Phase", result["profile_notice"])
        self.assertIn("§4.1.1.2", result["profile_notice"])
        self.assertIn("§4.1.6.2", result["profile_notice"])

    def test_invalid_text_and_frame_selection_are_reported(self):
        for sample, mode in (("", SPP_MODE), ("sample", "unsupported frame")):
            with self.subTest(sample=sample, mode=mode), self.assertRaises(ValueError):
                build_ccsds_learning_frame(sample, mode, apid=1)

    def test_cop_trace_preserves_deterministic_event_order(self):
        trace = build_cop1_learning_trace(initial_sequence_number=255, transmission_limit=3)
        self.assertEqual(
            [event["event"] for event in trace["events"]],
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
        self.assertIn("configured teaching-simulator default 3", trace["profile"]["transmission_limit"])
        self.assertIn("not a CCSDS default", trace["profile"]["transmission_limit"])
        self.assertIn("abstract teaching labels", trace["profile"]["state_labels"])


class CcsdsLearningTabTests(unittest.TestCase):
    def setUp(self):
        self.telemetry_patcher = patch.object(
            EspApiClient, "get_telemetry", return_value={"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
        )
        self.telemetry_patcher.start()
        self.addCleanup(self.telemetry_patcher.stop)

    def make_app(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        # These offline tab tests bypass the live handshake with synthetic session state;
        # the dedicated communication-gate suite tests the actual password exchange.
        app.session_state["esp_connection_authenticated"] = True
        app.session_state["esp_base_origin"] = "http://192.168.1.42"
        app.session_state["esp_boot_id"] = BOOT_ID
        app.session_state["esp_provision_id"] = PROVISION_ID
        app.run()
        app.radio[0].set_value("CCSDS learning simulation").run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        return app

    def test_tab_shows_offline_path_sources_and_cop_ack_caveat(self):
        app = self.make_app()
        markdown_text = "\n".join(item.value for item in app.markdown)
        subheader_text = "\n".join(item.value for item in app.subheader)
        warning_text = "\n".join(item.value for item in app.warning)
        info_text = "\n".join(item.value for item in app.info)
        code_text = "\n".join(item.value for item in app.code)
        caption_text = "\n".join(item.value for item in app.caption)
        self.assertIn("CCSDS learning simulation", subheader_text)
        self.assertIn("CCSDS appears only in the separate offline learning tab", caption_text)
        self.assertIn("Building frames and traces here makes no network calls", caption_text)
        self.assertIn("opaque sample bytes", caption_text)
        self.assertIn("Simulation / offline", "\n".join(item.value for item in app.success))
        self.assertIn("Local typed UTF-8", code_text)
        self.assertIn("not a CCSDS-compliant implementation", warning_text)
        self.assertIn("does not prove", warning_text)
        self.assertIn("232.1-B-2 Technical Corrigendum 1", markdown_text)
        self.assertIn("132.0-B-3", markdown_text)
        self.assertIn("232x0b4e1c1_tc2325.pdf", markdown_text)
        self.assertIn("Space Packet Version 1 encoded with PVN bits 000", caption_text)
        self.assertIn("not a standard-valid TM channel frame", warning_text)
        self.assertIn("selected teaching-profile constraints", warning_text)
        self.assertIn("not normative FOP/FARM states", info_text)

    def test_readme_and_profile_note_record_conditional_ccsds_scope(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        profile = (PROJECT_ROOT / "CCSDS_PROFILE.md").read_text(encoding="utf-8")
        for name, document in (("README", readme), ("CCSDS_PROFILE", profile)):
            with self.subTest(document=name):
                self.assertIn("Space Packet Version 1", document)
                self.assertTrue("PVN bits `000`" in document or "PVN bits are `000`" in document)
                self.assertIn("not a general CCSDS prohibition", document)
                self.assertIn("not broad TC compliance", document)
                self.assertIn("not a standard-valid TM channel frame", document)
                self.assertIn("§4.1.1.2", document)
                self.assertIn("§4.1.6.2", document)
                self.assertIn("232x0b4e1c1_tc2325.pdf", document)
                self.assertIn("not a CCSDS default", document)
                self.assertIn("abstract teaching labels", document)
        self.assertNotIn("fixed TM profile", readme + profile)
        self.assertNotIn("TM fixed-profile", readme + profile)

    def test_tc_submit_displays_exact_hex_space_packet_and_tc_header_fields(self):
        app = self.make_app()
        next(item for item in app.text_area if item.label == "Sample data (UTF-8)").set_value("hello")
        next(item for item in app.selectbox if item.label == "Output frame").set_value(TC_MODE)
        next(item for item in app.number_input if item.label == "Space Packet Version 1 APID (0–2046)").set_value(42)
        next(item for item in app.number_input if item.label == "Spacecraft ID / SCID (0–1023)").set_value(341)
        next(item for item in app.number_input if item.label == "TC Virtual Channel ID (0–63)").set_value(3)
        next(item for item in app.number_input if item.label == "TC frame sequence number (0–255)").set_value(255)
        next(item for item in app.button if item.label == "Build and decode offline frame").click()
        app.run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        result = app.session_state["ccsds_frame_result"]
        self.assertTrue(result["overall_valid"])
        self.assertTrue(any(item.value == result["frame"].hex().upper() for item in app.code))
        json_fields = [json.loads(item.value) for item in app.json]
        self.assertTrue(any(isinstance(item, dict) and item.get("apid") == 42 for item in json_fields))
        self.assertTrue(any(isinstance(item, dict) and item.get("spacecraft_id") == 341 for item in json_fields))
        self.assertTrue(any("Local decode and round trip: PASS" in item.value for item in app.success))
        warning_text = "\n".join(item.value for item in app.warning)
        self.assertIn("selected teaching-profile constraints", warning_text)
        self.assertIn("not broad TC compliance", warning_text)
        rendered_text = "\n".join(item.value for item in app.markdown)
        self.assertIn("Length validation: **PASS**", rendered_text)
        self.assertIn("FECF validation: **PASS**", rendered_text)

    def test_tm_submit_displays_offline_layout_fields_and_validation(self):
        app = self.make_app()
        next(item for item in app.text_area if item.label == "Sample data (UTF-8)").set_value("TM sample")
        next(item for item in app.selectbox if item.label == "Output frame").set_value(TM_MODE)
        next(item for item in app.number_input if item.label == "Spacecraft ID / SCID (0–1023)").set_value(677)
        next(item for item in app.number_input if item.label == "TM Virtual Channel ID (0–7)").set_value(7)
        next(item for item in app.number_input if item.label == "TM master-channel frame count (0–255)").set_value(254)
        next(item for item in app.number_input if item.label == "TM virtual-channel frame count (0–255)").set_value(12)
        next(item for item in app.button if item.label == "Build and decode offline frame").click()
        app.run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        result = app.session_state["ccsds_frame_result"]
        self.assertTrue(result["overall_valid"])
        self.assertTrue(any(item.value == result["frame"].hex().upper() for item in app.code))
        transfer_fields = json.loads(app.json[-1].value)
        self.assertEqual(transfer_fields["spacecraft_id"], 677)
        self.assertEqual(transfer_fields["virtual_channel_id"], 7)
        self.assertEqual(transfer_fields["master_channel_frame_count"], 254)
        self.assertEqual(transfer_fields["virtual_channel_frame_count"], 12)
        self.assertFalse(transfer_fields["ocf_flag"])
        self.assertFalse(transfer_fields["tf_secondary_header_flag"])
        rendered_text = "\n".join(item.value for item in app.markdown)
        self.assertIn("Length validation: **PASS**", rendered_text)
        self.assertIn("FECF validation: **PASS**", rendered_text)
        warnings = "\n".join(item.value for item in app.warning)
        self.assertIn("not a standard-valid TM channel frame", warnings)
        self.assertIn("Variable-length offline TM layout exercise", warnings)
        self.assertIn("constant-length-per-channel-during-a-Mission-Phase", warnings)

    def test_ccsds_action_never_invokes_live_esp_client(self):
        with (
            patch.object(
                EspApiClient, "get_telemetry", return_value={"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
            ) as get_telemetry,
            patch.object(EspApiClient, "set_chain") as set_chain,
            patch.object(EspApiClient, "send_message") as send_message,
        ):
            app = self.make_app()
            next(item for item in app.text_area if item.label == "Sample data (UTF-8)").set_value("LOCAL_CCSDS_ONLY")
            next(item for item in app.button if item.label == "Build and decode offline frame").click()
            app.run()
        get_telemetry.assert_called()
        set_chain.assert_not_called()
        send_message.assert_not_called()
        self.assertTrue(app.session_state["ccsds_frame_result"]["overall_valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
