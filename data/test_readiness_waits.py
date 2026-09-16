# SPDX-License-Identifier: GPL-2.0-or-later
"""Provider failures must not end a wait before its deadline or prove absence."""
import unittest
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

import atspi_probe as probe
import test_nonvisual_semantics as fixtures
import test_application_smoke as smoke_fixtures


class ReadinessWaitsTest(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.sleeps = []
        patches = [mock.patch.object(probe.time, "monotonic", side_effect=lambda: self.clock),
                   mock.patch.object(probe.time, "sleep", side_effect=self.sleep)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, duration):
        self.assertGreater(duration, 0)
        self.assertLessEqual(duration, 0.1)
        self.sleeps.append(duration)
        self.clock += duration

    def test_read_can_succeed_after_transient_failure(self):
        target = fixtures.SelectorTest().pair()
        with mock.patch.object(probe, "_visible_widgets", side_effect=[probe.ProbeError("starting"), [target]]) as read:
            result = probe.wait_for_widget(1, "button", ["Install"], 42)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["complete"])
        self.assertEqual(read.call_count, 2)
        self.assertTrue(all(call.args[0] == 42 for call in read.call_args_list))
        self.assertFalse(target[0].get_action_iface().done)
        self.assertEqual(len(self.sleeps), 1)

    def test_persistent_error_is_not_absence_or_failure_of_selector(self):
        with mock.patch.object(probe, "_visible_widgets", side_effect=probe.ProbeError("provider unavailable")), \
             self.assertRaisesRegex(probe.ProbeError, "provider unavailable"):
            probe.wait_for_widget(0.25, "button", ["Install"], 42, absent=True)
        self.assertAlmostEqual(self.clock, 0.25)
        self.assertEqual(len(self.sleeps), 3)

    def test_zero_budget_never_retries_an_error(self):
        read = mock.Mock(side_effect=probe.ProbeError("provider"))
        with self.assertRaises(probe.ProbeError):
            probe._read_until_ready(read, 0)
        read.assert_called_once()
        self.assertEqual(self.sleeps, [])

    def test_structural_truncation_is_not_retried(self):
        read = mock.Mock(side_effect=probe.WalkTruncated("node limit"))
        with self.assertRaises(probe.WalkTruncated):
            probe._read_until_ready(read, 30)
        read.assert_called_once()
        self.assertEqual(self.sleeps, [])

    def test_unexpected_programming_error_is_not_retried(self):
        read = mock.Mock(side_effect=ValueError("invalid local argument"))
        with self.assertRaises(ValueError):
            probe._read_until_ready(read, 30)
        read.assert_called_once()

    def test_complete_fresh_absence_can_follow_a_failed_read(self):
        with mock.patch.object(probe, "_visible_widgets", side_effect=[probe.ProbeError("starting"), []]):
            result = probe.wait_for_widget(1, "button", ["Install"], 42, absent=True)
        self.assertEqual(result["reason"], "absent")
        self.assertTrue(result["complete"])

    def test_ambiguous_fresh_read_does_not_become_success(self):
        pairs = [fixtures.SelectorTest().pair(), fixtures.SelectorTest().pair()]
        with mock.patch.object(probe, "_visible_widgets", side_effect=[probe.ProbeError("starting"), pairs]):
            result = probe.wait_for_widget(1, "button", ["Install"], 42)
        self.assertEqual(result["reason"], "ambiguous")
        self.assertTrue(all(not node.get_action_iface().done for node, _ in pairs))

    def test_focus_query_is_retried_without_moving_focus(self):
        target = fixtures.SelectorTest().pair(focused=True)
        with mock.patch.object(probe, "_visible_widgets", side_effect=[probe.ProbeError("starting"), [target]]):
            result = probe.focused_widget(1, 42)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(target[0].get_action_iface().done)

    def test_target_focus_reuses_application_hint_without_scanning_other_apps(self):
        window = object()
        target = {
            "pid": 42,
            "identity": "/target",
            "role": "button",
            "showing": True,
            "focused": True,
            "defunct": False,
            "application_index": 7,
        }

        def windows(*_args, **_kwargs):
            yield window, {
                "pid": 42,
                "name": "Installer",
                "application_index": 7,
            }
            raise AssertionError("an unrelated application was enumerated")

        with mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "_window_records", side_effect=windows) as read, \
             mock.patch.object(probe, "_widget_by_identity", return_value=target) as locate, \
             mock.patch.object(probe, "_showing_widgets_in_window") as walk:
            result = probe.focused_widget(1, 42, "/target", 7)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            read.call_args.kwargs["preferred_application_index"], 7
        )
        self.assertTrue(read.call_args.kwargs["stop_after_preferred_match"])
        self.assertEqual(locate.call_args.kwargs["application_index"], 7)
        walk.assert_not_called()

    def test_known_target_not_focused_is_a_complete_keyboard_observation(self):
        window = object()
        target = {
            "pid": 42,
            "identity": "/target",
            "role": "button",
            "showing": True,
            "focused": False,
            "defunct": False,
            "application_index": 7,
        }
        with mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(
                 probe, "_window_records",
                 return_value=[(window, {"pid": 42, "name": "Installer", "application_index": 7})],
             ), \
             mock.patch.object(probe, "_widget_by_identity", return_value=target), \
             mock.patch.object(
                 probe, "_showing_widgets_in_window",
                 side_effect=probe.WalkTruncated("slow unrelated subtree"),
             ):
            result = probe.focused_widget(1, 42, "/target", 7)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "target-not-focused")
        self.assertTrue(result["complete"])

    def test_read_attempts_receive_decreasing_budget(self):
        target = fixtures.SelectorTest().pair()
        with mock.patch.object(probe, "_widget_matches", side_effect=[probe.ProbeError("starting"), ([target], [target])]) as read:
            probe.wait_for_widget(1, "button", ["Install"], 42)
        self.assertEqual(read.call_args_list[0].args[3], 1)
        self.assertAlmostEqual(read.call_args_list[1].args[3], 0.9)


    def test_baseline_retries_transient_registry_failure_before_persisting(self):
        windows = [{"key": "42\0/window", "pid": 42}]
        with mock.patch.object(probe, "_baseline_window_records", side_effect=[
                 probe.ProbeError("registry transition"), windows]) as read, \
             mock.patch.object(probe, "mem_available_mib", return_value=100.0), \
             mock.patch.object(probe, "_x11_window_records", return_value=[]), \
             mock.patch.dict(probe.os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}), \
             mock.patch.object(Path, "write_text") as write:
            result = probe.save_baseline(Path("baseline.json"), 1)
        self.assertEqual(result, {
            "status": "passed",
            "window_count": 1,
            "mem_available_mib": 100.0,
            "desktop": "KDE",
        })
        self.assertNotIn("windows", result)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(self.sleeps, [0.1])
        payload = write.call_args.args[0]
        self.assertIn("42\\u0000/window", payload)

    def test_baseline_persistent_registry_failure_expires_without_writing(self):
        with mock.patch.object(probe, "_baseline_window_records",
                               side_effect=probe.ProbeError("registry unavailable")), \
             mock.patch.object(Path, "write_text") as write, \
             self.assertRaisesRegex(probe.ProbeError, "registry unavailable"):
            probe.save_baseline(Path("baseline.json"), 0.25)
        self.assertAlmostEqual(self.clock, 0.25)
        write.assert_not_called()

    def test_window_open_retries_read_failure_with_same_launch_scope(self):
        record = {"key": "new-window", "pid": 42, "application": "Editor",
                  "application_index": 7, "name": "Document",
                  "role": "frame", "children": 1}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "process_memory", return_value={}), \
             mock.patch.object(probe, "accessible_snapshot", side_effect=[
                 probe.ProbeError("starting"), {"windows": [record]}]) as read:
            result = probe.wait_for_window_change(Path("unused"), 1, True, 42, sample_memory=False)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["pid"], 42)
        self.assertEqual(result["application_index"], 7)
        self.assertTrue(all(call.args[1] == {42} for call in read.call_args_list))
        self.assertEqual(read.call_count, 2)

    def test_window_open_survives_a_reparented_live_group_member(self):
        record = {"key": "new-window", "pid": 99, "application": "Editor",
                  "application_index": 7, "name": "Document",
                  "role": "frame", "children": 1}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_launch_process_scope", return_value={42, 99}), \
             mock.patch.object(
                 probe, "launch_process_exited", side_effect=lambda pid, *_args: pid == 42
             ), \
             mock.patch.object(probe, "process_memory", return_value={}), \
             mock.patch.object(probe, "accessible_snapshot", side_effect=[
                 {"windows": []}, {"windows": [record]}]) as read:
            result = probe.wait_for_window_change(
                Path("unused"), 1, True, 42, sample_memory=False
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["pid"], 99)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(self.sleeps, [0.1])

    def test_window_close_read_failure_cannot_prove_disappearance(self):
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", side_effect=probe.ProbeError("bus")), \
             self.assertRaises(probe.ProbeError):
            probe.wait_for_window_change(Path("unused"), 0.25, False, 42)
        self.assertAlmostEqual(self.clock, 0.25)

    def test_shared_process_closes_the_exact_opened_window(self):
        replacement = {"key": "42\\0/replacement", "identity": "/replacement",
                       "pid": 42, "application": "App", "name": "Tray",
                       "role": "frame", "children": 1}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", return_value={"windows": [replacement]}), \
             mock.patch.object(probe, "launch_process_exited", return_value=False):
            result = probe.wait_for_window_change(
                Path("unused"), 0, False, 42,
                expected_window_identity="/tested-window")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["accessible_window"])
        self.assertFalse(result["process_gone"])

    def test_shared_process_does_not_invent_exact_window_disappearance(self):
        target = {"key": "42\\0/tested", "identity": "/tested-window",
                  "pid": 42, "application": "App", "name": "Window",
                  "role": "frame", "children": 1}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", return_value={"windows": [target]}), \
             mock.patch.object(probe, "launch_process_exited", return_value=False):
            result = probe.wait_for_window_change(
                Path("unused"), 0, False, 42,
                expected_window_identity="/tested-window")
        self.assertEqual(result["status"], "failed")

    def test_hidden_exact_window_counts_as_closed_for_resident_service(self):
        target = {"key": "42\\0/tested", "identity": "/tested-window",
                  "pid": 42, "application": "App", "name": "Window",
                  "role": "frame", "children": 1, "showing": False,
                  "defunct": False}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", return_value={"windows": [target]}), \
             mock.patch.object(probe, "launch_process_exited", return_value=False):
            result = probe.wait_for_window_change(
                Path("unused"), 0, False, 42,
                expected_window_identity="/tested-window")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["accessible_window"])
        self.assertFalse(result["process_gone"])

    def test_defunct_exact_window_counts_as_closed(self):
        target = {"key": "42\\0/tested", "identity": "/tested-window",
                  "pid": 42, "application": "App", "name": "Window",
                  "role": "frame", "children": 1, "showing": True,
                  "defunct": True}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", return_value={"windows": [target]}), \
             mock.patch.object(probe, "launch_process_exited", return_value=False):
            result = probe.wait_for_window_change(
                Path("unused"), 0, False, 42,
                expected_window_identity="/tested-window")
        self.assertEqual(result["status"], "passed")

    def test_hidden_window_is_not_accepted_as_open(self):
        target = {"key": "42\\0/tested", "identity": "/tested-window",
                  "pid": 42, "application": "App", "name": "Window",
                  "role": "frame", "children": 1, "showing": False,
                  "defunct": False}
        with mock.patch.object(probe, "baseline_keys", return_value=set()), \
             mock.patch.object(probe, "_process_tree", return_value={42}), \
             mock.patch.object(probe, "accessible_snapshot", return_value={"windows": [target]}), \
             mock.patch.object(probe, "launch_process_exited", return_value=False):
            result = probe.wait_for_window_change(
                Path("unused"), 0, True, 42, sample_memory=False)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["accessible_window"])

    def test_smoke_retries_observation_but_never_an_action(self):
        root = smoke_fixtures.Node("Editor", "frame", [smoke_fixtures.Node(role="text", text=True)])
        with mock.patch.object(probe, "_atspi_import", return_value=(smoke_fixtures.API, smoke_fixtures.GLIB)), \
             mock.patch.object(probe, "_window_records", side_effect=[
                 probe.ProbeError("starting"), [(root, {"pid": 42, "role": "frame"})]]) as read:
            result = probe.smoke_window(1, 42)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["evidence"]["text_interface"])
        self.assertEqual(read.call_count, 2)
        self.assertTrue(all(call.args[1] == {42} for call in read.call_args_list))

    def test_smoke_reuses_pid_verified_application_hint(self):
        root = smoke_fixtures.Node(
            "Editor", "frame", [smoke_fixtures.Node(role="text", text=True)]
        )
        with mock.patch.object(
            probe, "_atspi_import",
            return_value=(smoke_fixtures.API, smoke_fixtures.GLIB),
        ), mock.patch.object(
            probe, "_window_records",
            return_value=[(root, {"pid": 42, "role": "frame", "application_index": 7})],
        ) as read:
            result = probe.smoke_window(1, 42, application_index=7)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["application_index"], 7)
        self.assertEqual(read.call_args.kwargs["preferred_application_index"], 7)
        self.assertTrue(read.call_args.kwargs["stop_after_preferred_match"])

    def test_smoke_uses_launch_tree_and_prefers_the_opened_window(self):
        root = smoke_fixtures.Node(
            "Editor", "frame", [smoke_fixtures.Node(role="text", text=True)]
        )
        record = {
            "pid": 43,
            "role": "frame",
            "identity": "/opened",
            "application_index": 6,
        }
        with mock.patch.object(
            probe, "_atspi_import",
            return_value=(smoke_fixtures.API, smoke_fixtures.GLIB),
        ), mock.patch.object(
            probe, "_launch_process_scope", return_value={42, 43}
        ) as scope, mock.patch.object(
            probe, "_window_records", return_value=[(root, record)]
        ) as read:
            result = probe.smoke_window(
                1, 42, application_index=7,
                window_identity="/opened", root_pid=41,
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["pid"], 43)
        self.assertEqual(result["window_identity"], "/opened")
        scope.assert_called_once_with(41, (42,))
        self.assertEqual(read.call_args.args[1], {42, 43})
        self.assertEqual(read.call_args.kwargs["preferred_application_index"], 7)
        self.assertEqual(read.call_args.kwargs["preferred_window_identity"], "/opened")

    def test_smoke_permanent_failure_uses_one_shared_deadline(self):
        with mock.patch.object(probe, "_atspi_import", return_value=(smoke_fixtures.API, smoke_fixtures.GLIB)), \
             mock.patch.object(probe, "_window_records", side_effect=probe.ProbeError("bus")), \
             self.assertRaises(probe.ProbeError):
            probe.smoke_window(0.25, 42)
        self.assertAlmostEqual(self.clock, 0.25)

    def test_smoke_does_not_retry_a_structural_node_limit(self):
        root = smoke_fixtures.Node("Editor", "frame")
        with mock.patch.object(probe, "_atspi_import", return_value=(smoke_fixtures.API, smoke_fixtures.GLIB)), \
             mock.patch.object(probe, "_window_records", return_value=[(root, {"pid": 42, "role": "frame"})]) as read, \
             mock.patch.object(probe, "_smoke_content", side_effect=probe.WalkTruncated("node limit")), \
             self.assertRaises(probe.WalkTruncated):
            probe.smoke_window(1, 42)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_focus_transition_from_two_candidates_waits_for_unique_state(self):
        first = fixtures.SelectorTest().pair(focused=True)
        final = fixtures.SelectorTest().pair(focused=True)
        with mock.patch.object(probe, "_visible_widgets", side_effect=[[first, final], [final]]) as read:
            result = probe.focused_widget(1, 42)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(read.call_count, 2)
        self.assertEqual(self.sleeps, [0.1])

    def test_focus_absence_can_be_a_pending_state(self):
        item = fixtures.SelectorTest().pair(focused=True)
        with mock.patch.object(probe, "_visible_widgets", side_effect=[[], [item]]):
            self.assertEqual(probe.focused_widget(1, 42)["status"], "passed")
        self.assertEqual(self.sleeps, [0.1])

    def test_persistent_focus_ambiguity_is_not_resolved_arbitrarily(self):
        first = fixtures.SelectorTest().pair(focused=True)
        second = fixtures.SelectorTest().pair(focused=True)
        first[1].update(identity="/first", name="secret-field-value", role="frame")
        second[1].update(identity="/second", role="button")
        with mock.patch.object(probe, "_visible_widgets", return_value=[first, second]):
            result = probe.focused_widget(0.25, 42)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "ambiguous")
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["candidates"][0]["identity"], "/first")
        self.assertNotIn("secret-field-value", str(result))
        self.assertAlmostEqual(self.clock, 0.25)

    def test_focus_diagnostics_are_bounded(self):
        pairs = [fixtures.SelectorTest().pair(focused=True) for _ in range(20)]
        for _, record in pairs:
            record.update(identity="x" * 1000, role="y" * 1000)
        with mock.patch.object(probe, "_visible_widgets", return_value=pairs):
            result = probe.focused_widget(0, 42)
        self.assertEqual(len(result["candidates"]), 8)
        self.assertEqual(len(result["candidates"][0]["identity"]), 256)
        self.assertEqual(len(result["candidates"][0]["role"]), 64)
        self.assertEqual(result["matches"], 20)

    def test_defunct_focus_candidate_is_not_accepted(self):
        item = fixtures.SelectorTest().pair(focused=True, defunct=True)
        with mock.patch.object(probe, "_visible_widgets", return_value=[item]):
            result = probe.focused_widget(0.25, 42)
        self.assertEqual(result["reason"], "not-found")
        self.assertAlmostEqual(self.clock, 0.25)


class AtspiCallBudgetTest(unittest.TestCase):
    def test_new_probe_has_no_fresh_fifteen_second_startup_grace(self):
        gi = ModuleType("gi")
        gi.require_version = mock.Mock()
        repository = ModuleType("gi.repository")
        repository.Atspi = mock.Mock()
        repository.GLib = smoke_fixtures.GLIB
        gi.repository = repository
        with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}), \
             mock.patch.object(probe, "_atspi_timeout_set", False):
            probe._atspi_import()
            probe._atspi_import()
        repository.Atspi.set_timeout.assert_called_once_with(800, -1)


if __name__ == "__main__":
    unittest.main()
