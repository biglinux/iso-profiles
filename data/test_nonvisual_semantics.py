# SPDX-License-Identifier: GPL-2.0-or-later
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

    def test_shared_panel_is_not_a_cycle_or_duplicate_widget(self):
        target = FakeAccessible("keyboard", 42, role="table")
        panel = FakeAccessible("panel", 42, [target])
        pages = [FakeAccessible("page", 42, [panel]) for _ in range(4)]
        root = FakeAccessible("window", 42, pages)
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            observed = list(probe._walk(root))
        self.assertEqual(observed.count(panel), 1)
        self.assertEqual(observed.count(target), 1)
        self.assertEqual(len(observed), 7)

    def test_duplicate_child_reference_is_visited_once(self):
        child = FakeAccessible("button", 42)
        root = FakeAccessible("window", 42, [child, child])
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            self.assertEqual(list(probe._walk(root)), [root, child])

    def test_cycle_below_shared_subtree_still_fails(self):
        shared = FakeAccessible("shared", 42)
        first = FakeAccessible("first", 42, [shared])
        second = FakeAccessible("second", 42, [shared])
        shared.children = [second]
        root = FakeAccessible("window", 42, [first, second])
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            with self.assertRaisesRegex(probe.WalkTruncated, "cyclic"):
                list(probe._walk(root))

    def test_exact_node_budget_can_complete(self):
        root = FakeAccessible("window", 42, [FakeAccessible("child", 42)])
        with mock.patch.object(probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            self.assertEqual(len(list(probe._walk(root, limit=2))), 2)


class OrcaSpeechTest(unittest.TestCase):
    """What Orca sends speech-dispatcher, read from the SSIP stream."""

    def test_speak_body_is_one_record_without_ssml_or_dot_escaping(self):
        stream = orca.ClientStream()
        records = stream.feed(b"SET self PRIORITY text\r\nSPEAK\r\n<speak>Sem t\xc3\xadtulo")
        records += stream.feed(b" \xe2\x80\x94 Kate</speak>\r\n..hidden\r\n.\r\n")
        self.assertEqual(records, [{"kind": "speech", "text": "Sem título — Kate\n.hidden"}])

    def test_characters_and_keys_are_speech(self):
        records = orca.ClientStream().feed(b"CHAR a\r\nKEY enter\r\nSET self RATE 10\r\n")
        self.assertEqual([r["text"] for r in records], ["a", "enter"])

    def test_server_errors_are_recorded_and_success_is_not(self):
        records = orca.ServerStream().feed(
            b"230 OK RECEIVING DATA\r\n225-17\r\n225 OK MESSAGE QUEUED\r\n"
            b"300 ERR MODULE NOT LOADED\r\n")
        self.assertEqual(records, [{"kind": "error", "reply": "300 ERR MODULE NOT LOADED"}])

    def write_log(self, folder, *records, partial=b""):
        log = Path(folder, "speech.jsonl")
        log.write_bytes(b"".join(
            (orca.json.dumps(record) + "\n").encode() for record in records) + partial)
        return mock.patch.object(orca, "SPEECH_LOG", log)

    def test_speech_after_the_mark_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            first = (orca.json.dumps({"kind": "speech", "text": "old"}) + "\n").encode()
            with self.write_log(folder, {"kind": "speech", "text": "old"},
                                {"kind": "speech", "text": "Kate"}):
                self.assertEqual(orca.check(len(first), "", 0)["status"], "passed")
                self.assertEqual(orca.check(len(first), "kate", 0)["status"], "passed")
                self.assertEqual(orca.check(len(first), "dolphin", 0)["status"], "failed")

    def test_mark_waits_for_orca_to_fall_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.write_log(folder, {"kind": "speech", "text": "Área de trabalho"}):
                log = orca.SPEECH_LOG
                late = (orca.json.dumps({"kind": "speech", "text": "late"}) + "\n").encode()

                def speak_late():
                    orca.time.sleep(0.3)
                    with log.open("ab") as stream:
                        stream.write(late)

                orca.threading.Thread(target=speak_late).start()
                mark = orca.offset(5)["offset"]
            self.assertEqual(mark, log.stat().st_size)

    def test_silence_and_a_partial_line_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.write_log(folder, {"kind": "client"}, partial=b'{"kind": "speech", "te'):
                self.assertEqual(orca.check(0, "", 0),
                                 {"status": "failed", "error": "Orca said nothing"})

    def test_a_refused_utterance_fails_even_when_others_were_spoken(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.write_log(folder, {"kind": "speech", "text": "Kate"},
                                {"kind": "error", "reply": "300 ERR"}):
                self.assertIn("refused", orca.check(0, "", 0)["error"])

    def test_phrase_match_has_word_boundaries(self):
        self.assertFalse(orca.contains_phrase("unsuccessful", "successful"))
        self.assertFalse(orca.contains_phrase("success", ""))
        self.assertTrue(orca.contains_phrase("Operação concluída!", "operacao concluida"))

    def test_proxy_forwards_both_ways_and_logs_the_utterance(self):
        import socket
        import threading
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            upstream_path = folder / "speechd.sock"
            upstream = socket.socket(socket.AF_UNIX)
            upstream.bind(str(upstream_path))
            upstream.listen(1)

            def speechd():
                connection, _ = upstream.accept()
                received = b""
                while not received.endswith(b"\r\n.\r\n"):
                    received += connection.recv(1024)
                connection.sendall(b"230 OK RECEIVING DATA\r\n225 OK MESSAGE QUEUED\r\n")
                connection.close()

            threading.Thread(target=speechd, daemon=True).start()
            with mock.patch.multiple(orca, PROXY_SOCKET=folder / "proxy.sock",
                                     SPEECH_LOG=folder / "speech.jsonl",
                                     SPEECHD_SOCKET=upstream_path):
                threading.Thread(target=orca.proxy, daemon=True).start()
                for _ in range(50):
                    if (folder / "proxy.sock").exists():
                        break
                    orca.time.sleep(0.02)
                client = socket.socket(socket.AF_UNIX)
                client.connect(str(folder / "proxy.sock"))
                client.sendall(b"SPEAK\r\n<speak>Leitor de tela ativado.</speak>\r\n.\r\n")
                reply = b""
                while b"225 OK" not in reply:
                    reply += client.recv(1024)
                client.close()
                self.assertEqual(orca.check(0, "leitor de tela ativado", 2)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
