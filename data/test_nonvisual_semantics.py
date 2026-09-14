# SPDX-License-Identifier: GPL-2.0-or-later
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import atspi_probe as probe
import orca_probe as orca
from test_atspi_probe import FakeAccessible, FakeAtspi, FakeGLib, FakeActions, FakeWidget


class SelectorTest(unittest.TestCase):
    def pair(self, name="Install", identifier="target", **fields):
        record = dict(name=name, role="button", sensitive=True, showing=True,
                      accessible_id=identifier, pid=42, window="Dialog", **fields)
        return FakeWidget(FakeActions(["click"])), record

    def test_plain_prefix_is_not_identity(self):
        self.assertFalse(probe._label_matches("Install unwanted software", ["Install"]))

    def test_ambiguous_selector_never_acts(self):
        first, second = self.pair(), self.pair()
        with mock.patch.object(probe, "_visible_widgets", return_value=[first, second]):
            result = probe.activate_widget(0, "button", ["Install"])
        self.assertEqual(result["reason"], "ambiguous")
        self.assertFalse(first[0].get_action_iface().done)
        self.assertFalse(second[0].get_action_iface().done)

    def test_stable_id_disambiguates(self):
        pairs = [self.pair(identifier="other"), self.pair()]
        with mock.patch.object(probe, "_visible_widgets", return_value=pairs) as walk:
            result = probe.wait_for_widget(0, "button", [], 42, accessible_id="target", window_name="Dialog")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(walk.call_args.args[0], 42)
        self.assertEqual(result["widget"]["accessible_id"], "target")

    def test_disabled_is_not_disappeared(self):
        item = self.pair()
        item[1]["sensitive"] = False
        with mock.patch.object(probe, "_visible_widgets", return_value=[item]):
            result = probe.wait_for_widget(0, "button", ["Install"], absent=True)
        self.assertEqual(result["status"], "failed")

    def test_incomplete_is_never_absent(self):
        with mock.patch.object(probe, "_visible_widgets", side_effect=probe.WalkTruncated("budget")):
            with self.assertRaises(probe.WalkTruncated):
                probe.wait_for_widget(0, "button", ["Install"], absent=True)

    def test_complete_empty_query_proves_absence(self):
        with mock.patch.object(probe, "_visible_widgets", return_value=[]):
            result = probe.wait_for_widget(0, "button", ["Install"], absent=True)
        self.assertEqual(result["reason"], "absent")
        self.assertTrue(result["complete"])

    def test_checked_is_required_when_requested(self):
        item = self.pair(checked=False)
        with mock.patch.object(probe, "_visible_widgets", return_value=[item]):
            result = probe.wait_for_widget(0, "button", ["Install"], checked=True)
        self.assertEqual(result["status"], "failed")

    def test_focus_is_observed_without_calling_component(self):
        item = self.pair(focused=True)
        with mock.patch.object(probe, "_visible_widgets", return_value=[item]):
            result = probe.focused_widget(1, 42)
        self.assertEqual(result["status"], "passed")

    def test_geometry_is_not_required(self):
        states = SimpleNamespace(**{name: name for name in
            ("SHOWING", "SENSITIVE", "CHECKED", "SELECTED", "FOCUSED", "FOCUSABLE", "DEFUNCT")})
        api = SimpleNamespace(StateType=states)
        node = FakeAccessible("Confirm", 42, role="button")
        node.get_state_set = lambda: SimpleNamespace(contains=lambda flag: flag in {"SHOWING", "SENSITIVE"})
        with mock.patch.object(probe, "_atspi_import", return_value=(api, FakeGLib)):
            self.assertEqual(probe._widget_record(node)["name"], "Confirm")

    def test_wide_tree_is_bounded_before_fetching_children(self):
        root = FakeAccessible("root", 42)
        root.get_child_count = lambda: 1000000
        root.get_child_at_index = mock.Mock()
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            with self.assertRaises(probe.WalkTruncated):
                list(probe._walk(root, limit=10))
        root.get_child_at_index.assert_not_called()

    def test_cycle_is_incomplete_not_a_valid_tree(self):
        root = FakeAccessible("root", 42)
        root.children = [root]
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            with self.assertRaisesRegex(probe.WalkTruncated, "cyclic"):
                list(probe._walk(root))


class OrcaEvidenceTest(unittest.TestCase):
    def test_reader_output_not_debug_or_key_text(self):
        raw = b'{"kind":"key","text":"success"}\n{"kind":"speech","text":"Ready"}\n'
        self.assertEqual(orca.presented_text(raw), "Ready")

    def test_interrupted_output_is_not_evidence(self):
        raw = b'{"kind":"speech","text":"success"}\n{"kind":"interrupt"}\n'
        self.assertEqual(orca.presented_text(raw), "")

    def test_partial_record_is_not_evidence(self):
        self.assertEqual(orca.presented_text(b'{"kind":"speech","text":"success"}'), "")

    def test_phrase_match_has_word_boundaries(self):
        self.assertFalse(orca.contains_phrase("unsuccessful", "successful"))
        self.assertFalse(orca.contains_phrase("success", ""))
        self.assertTrue(orca.contains_phrase("Operação concluída!", "operacao concluida"))

    def test_malformed_record_is_rejected(self):
        with self.assertRaises(orca.ObservationError):
            orca.presented_text(b'{"kind":"speech","text":5}\n')

    def test_introspects_signature_instead_of_guessing(self):
        xml = '<node><interface name="org.gnome.Orca1.SpeechPresenter"><method name="SetLogFileForTesting"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method></interface></node>'
        self.assertEqual(orca.find_recorder(lambda _: xml), (orca.ROOT, "org.gnome.Orca1.SpeechPresenter"))
        with self.assertRaises(orca.ObservationError):
            orca.find_recorder(lambda _: xml.replace('type="b"', 'type="s"'))

    def test_missing_upstream_capability_blocks(self):
        with self.assertRaisesRegex(orca.ObservationError, "lacks"):
            orca.find_recorder(lambda _: "<node/>")

    def test_state_is_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "state.json")
            orca.save_state(path, {"a": 1})
            self.assertEqual(orca.read_state(path), {"a": 1})
            path.chmod(0o644)
            with self.assertRaises(orca.ObservationError):
                orca.read_state(path)


if __name__ == "__main__":
    unittest.main()
