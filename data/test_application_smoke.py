"""Smoke checks need a content witness, not a full accessibility audit."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import atspi_probe as probe
from desktop_entry_launcher import parse_desktop_entry

STATES = {key: key for key in ("ACTIVE", "SHOWING", "SENSITIVE", "FOCUSED", "FOCUSABLE",
                              "SELECTED", "CHECKED", "DEFUNCT")}
API = NS(StateType=NS(**STATES))
GLIB = NS(Error=RuntimeError)


class Node:
    def __init__(self, name="", role="panel", children=(), *, text=False, action=False,
                 states=("SHOWING", "SENSITIVE")):
        self.name, self.role, self.children = name, role, list(children)
        self.text, self.action, self.states = text, action, set(states)

    def get_state_set(self):
        return NS(contains=lambda flag: flag in self.states)

    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_child_count(self): return len(self.children)
    def get_child_at_index(self, i): return self.children[i]
    def get_text_iface(self): return NS(get_character_count=lambda: 0) if self.text else None
    def get_action_iface(self): return NS(get_n_actions=lambda: 1) if self.action else None
    def get_value_iface(self): return None


class SmokeContentTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(probe, "_atspi_import", return_value=(API, GLIB))
        patcher.start()
        self.addCleanup(patcher.stop)

    def content(self, root, limit=256):
        return probe._smoke_content(root, time.monotonic() + 1, limit)

    def test_named_window_alone_is_not_content(self):
        self.assertIsNone(self.content(Node("Editor", "frame")))

    def test_empty_editor_text_interface_is_sufficient(self):
        evidence = self.content(Node(children=[Node(role="text", text=True)]))
        self.assertTrue(evidence["text_interface"])
        self.assertNotIn("text", evidence)

    def test_named_action_is_sufficient(self):
        self.assertTrue(self.content(Node(children=[Node("Menu", "button", action=True)]))["has_name"])

    def test_unnamed_container_is_not_content(self):
        self.assertIsNone(self.content(Node(children=[Node()])))

    def test_hidden_control_is_not_a_witness(self):
        self.assertIsNone(self.content(Node(children=[Node("Menu", "button", action=True, states=())])))

    def test_defunct_control_is_not_a_witness(self):
        self.assertIsNone(self.content(Node(children=[Node("Menu", "button", action=True,
                                                          states=("SHOWING", "DEFUNCT"))])))

    def test_witness_does_not_require_full_tree_or_all_controls_named(self):
        unreadable = Node()
        unreadable.get_state_set = mock.Mock(side_effect=RuntimeError("unread later node"))
        root = Node(children=[Node("Menu", "button", action=True), unreadable])
        self.assertIsNotNone(self.content(root))
        unreadable.get_state_set.assert_not_called()

    def test_shallow_sibling_is_not_hidden_by_a_deep_first_branch(self):
        deep = Node()
        for _ in range(30):
            deep = Node(children=[deep])
        root = Node(children=[deep, Node("Menu", "button", action=True)])
        evidence = self.content(root, limit=8)
        self.assertTrue(evidence["action_interface"])
        self.assertLessEqual(evidence["nodes_visited"], 4)

    def test_wide_views_fetch_children_lazily(self):
        root = Node()
        root.get_child_count = lambda: 1000000
        root.get_child_at_index = mock.Mock(return_value=Node("Menu", "button", action=True))
        self.assertIsNotNone(self.content(root))
        self.assertEqual(root.get_child_at_index.call_count, 1)

    def test_no_witness_at_budget_is_inconclusive_not_success(self):
        with self.assertRaises(probe.WalkTruncated):
            self.content(Node(children=[Node() for _ in range(20)]), limit=10)

    def test_cycle_is_bounded(self):
        root = Node()
        root.children.append(root)
        with self.assertRaises(probe.WalkTruncated): self.content(root)

    def test_shared_container_is_not_an_ancestor_cycle(self):
        shared = Node()
        root = Node(children=[Node(children=[shared]), Node(children=[shared]),
                              Node(role="text", text=True)])
        self.assertTrue(self.content(root)["text_interface"])

    def test_shared_subtree_is_not_revisited(self):
        shared = Node(children=[Node()])
        shared.get_child_count = mock.Mock(wraps=shared.get_child_count)
        root = Node(children=[shared, shared, Node("Menu", "button", action=True)])
        self.assertTrue(self.content(root)["action_interface"])
        shared.get_child_count.assert_called_once()

    def test_empty_tree_at_exact_unique_budget_is_complete(self):
        self.assertIsNone(self.content(Node(children=[Node()]), limit=2))

    def test_null_child_does_not_hide_a_later_content_witness(self):
        root = Node(children=[None, Node(role="text", text=True)])
        self.assertTrue(self.content(root)["text_interface"])

    def test_null_child_without_witness_is_inconclusive(self):
        with self.assertRaises(probe.ProbeError):
            self.content(Node(children=[None]))

    def test_repeated_references_have_a_bounded_edge_budget(self):
        root, shared = Node(), Node()
        root.get_child_count = lambda: 1000000
        root.get_child_at_index = mock.Mock(return_value=shared)
        with self.assertRaises(probe.WalkTruncated):
            self.content(root, limit=4)
        self.assertLessEqual(root.get_child_at_index.call_count, 16)

    def test_hidden_menu_does_not_consume_visible_content_budget(self):
        hidden = Node(states=())
        hidden.get_child_count = mock.Mock(return_value=1000000)
        root = Node(children=[hidden, Node(role="terminal", text=True)])
        evidence = self.content(root, limit=3)
        self.assertTrue(evidence["text_interface"])
        hidden.get_child_count.assert_not_called()

    def test_defunct_container_children_are_never_queried(self):
        defunct = Node(states=("SHOWING", "DEFUNCT"))
        defunct.get_child_count = mock.Mock(side_effect=RuntimeError("destroyed peer"))
        root = Node(children=[defunct, Node("Close", "button", action=True)])
        self.assertTrue(self.content(root)["action_interface"])
        defunct.get_child_count.assert_not_called()

    def test_child_of_hidden_ancestor_is_not_an_accessible_witness(self):
        hidden = Node(states=(), children=[Node(role="text", text=True)])
        self.assertIsNone(self.content(Node(children=[hidden])))

    def window_result(self, pid=42, active=False, expected=42, active_only=False):
        root = Node("Editor", "frame", [Node(role="text", text=True)],
                    states=("SHOWING", "ACTIVE") if active else ("SHOWING",))
        record = {
            "pid": pid,
            "role": "frame",
            "identity": "/window/0",
            "name": "Editor",
            "application_window_count": 1,
            "application_index": 7,
        }
        with mock.patch.object(probe, "_window_records", return_value=[(root, record)]), \
             mock.patch.object(probe, "launch_process_exited", return_value=False), \
             mock.patch.object(probe.time, "monotonic", return_value=0):
            return probe.smoke_window(0, expected, active_only)

    def test_window_of_other_process_cannot_pass(self):
        self.assertEqual(self.window_result(pid=99)["status"], "failed")

    def test_own_content_is_observed_without_forcing_focus(self):
        self.assertEqual(self.window_result()["status"], "passed")

    def test_close_requires_active_target_window(self):
        self.assertEqual(self.window_result(active_only=True)["status"], "failed")
        result = self.window_result(active=True, active_only=True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["window_identity"], "/window/0")
        self.assertEqual(result["window_role"], "frame")
        self.assertEqual(result["application_window_count"], 1)
        self.assertEqual(result["application_index"], 7)

    def test_provider_error_is_not_ignored(self):
        with mock.patch.object(probe, "_window_records", side_effect=RuntimeError("bus")):
            with self.assertRaises(probe.ProbeError): probe.smoke_window(1, 42)


class PersistentSmokeSessionTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(probe, "_atspi_import", return_value=(API, GLIB))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name, "state.json")
        self.state.write_text('{"window_keys": []}', encoding="utf-8")

    @staticmethod
    def target(active=True):
        states = ["SHOWING"] + (["ACTIVE"] if active else [])
        window = Node(
            "Editor",
            "frame",
            [Node(role="text", text=True)],
            states=tuple(states),
        )
        record = {
            "key": "42\\0/window/0",
            "pid": 42,
            "identity": "/window/0",
            "application": "Editor",
            "application_index": 7,
            "name": "Editor",
            "role": "frame",
            "children": 1,
            "application_window_count": 1,
            "showing": True,
            "defunct": False,
        }
        return window, record

    def test_one_client_reuses_the_proven_window_through_process_exit(self):
        window, record = self.target()
        ready = mock.Mock()
        with mock.patch.object(probe, "_window_records", return_value=[(window, record)]) as records, \
             mock.patch.object(probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(probe, "_process_scope_exited", side_effect=lambda _scope: ready.called), \
             mock.patch.object(probe, "_emit_ready", side_effect=ready), \
             mock.patch.object(probe, "mem_available_mib", return_value=100.0), \
             mock.patch.object(probe, "process_memory", return_value={"rss_mib": 1.0, "pss_mib": 1.0, "process_count": 1}):
            result = probe.application_smoke_session(
                self.state, 0.2, 42, 42, 0, 0.2, 0.2, "process-exit"
            )
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["process_gone"])
        self.assertEqual(result["coverage"], "accessible-content-present")
        ready.assert_called_once()
        records.assert_called_once()

    def test_shared_window_can_close_while_its_service_remains(self):
        window, record = self.target()
        ready = mock.Mock(side_effect=lambda _record: window.states.discard("SHOWING"))
        with mock.patch.object(probe, "_window_records", return_value=[(window, record)]) as records, \
             mock.patch.object(probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(probe, "_process_scope_exited", return_value=False), \
             mock.patch.object(probe, "_emit_ready", side_effect=ready), \
             mock.patch.object(probe, "mem_available_mib", return_value=100.0), \
             mock.patch.object(probe, "process_memory", return_value={"rss_mib": 1.0, "pss_mib": 1.0, "process_count": 1}):
            result = probe.application_smoke_session(
                self.state, 0.2, 42, 42, 0, 0.2, 0.2, "window-close"
            )
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["window_closed"])
        self.assertFalse(result["process_gone"])
        ready.assert_called_once()
        records.assert_called_once()

    def test_inactive_target_never_requests_a_close_key(self):
        window, record = self.target(active=False)
        ready = mock.Mock()
        with mock.patch.object(probe, "_window_records", return_value=[(window, record)]), \
             mock.patch.object(probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(probe, "_process_scope_exited", return_value=False), \
             mock.patch.object(probe, "_emit_ready", side_effect=ready), \
             mock.patch.object(probe, "mem_available_mib", return_value=100.0), \
             mock.patch.object(probe, "process_memory", return_value={}):
            result = probe.application_smoke_session(
                self.state, 0.2, 42, 42, 0, 0.2, 0.2, "process-exit"
            )
        self.assertEqual(result["phase"], "focus")
        self.assertEqual(result["status"], "failed")
        ready.assert_not_called()

    def test_preexisting_window_is_not_reused_as_the_launch_result(self):
        window, record = self.target()
        self.state.write_text(
            json.dumps({"window_keys": [record["key"]]}), encoding="utf-8"
        )
        with mock.patch.object(probe, "_window_records", return_value=[(window, record)]), \
             mock.patch.object(probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(probe, "_process_scope_exited", return_value=True), \
             mock.patch.object(probe, "_emit_ready") as ready:
            result = probe.application_smoke_session(
                self.state, 0.2, 42, 42, 0, 0.2, 0.2, "process-exit"
            )
        self.assertEqual(result["phase"], "open")
        self.assertEqual(result["status"], "failed")
        ready.assert_not_called()


class OptionalApplicationTest(unittest.TestCase):
    def entry(self, **keys):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "app.desktop")
            lines = {"Type": "Application", "Name": "App", "Exec": "test-app", **keys}
            path.write_text("[Desktop Entry]\n" + "\n".join(f"{k}={v}" for k, v in lines.items()))
            return parse_desktop_entry(path)

    def test_generic_app_is_valid_in_kde_and_gnome(self):
        for desktop in ("KDE", "GNOME", "ubuntu:GNOME"):
            with self.subTest(desktop=desktop), mock.patch.dict(os.environ, XDG_CURRENT_DESKTOP=desktop):
                self.assertIsNone(self.entry().not_applicable_reason())

    def test_only_show_in_and_not_show_in_follow_current_session(self):
        with mock.patch.dict(os.environ, XDG_CURRENT_DESKTOP="GNOME"):
            self.assertIsNotNone(self.entry(OnlyShowIn="KDE;").not_applicable_reason())
            self.assertIsNone(self.entry(OnlyShowIn="GNOME;").not_applicable_reason())
            self.assertIsNotNone(self.entry(NotShowIn="GNOME;").not_applicable_reason())

    def test_first_matching_desktop_name_wins(self):
        with mock.patch.dict(os.environ, XDG_CURRENT_DESKTOP="ubuntu:GNOME"):
            self.assertIsNone(self.entry(OnlyShowIn="ubuntu;", NotShowIn="GNOME;").not_applicable_reason())
        with mock.patch.dict(os.environ, XDG_CURRENT_DESKTOP="GNOME:ubuntu"):
            self.assertIsNotNone(self.entry(OnlyShowIn="ubuntu;", NotShowIn="GNOME;").not_applicable_reason())

    def test_missing_tryexec_is_not_applicable(self):
        with mock.patch("desktop_entry_launcher.shutil.which", return_value=None):
            self.assertIn("not installed", self.entry(TryExec="optional-app").not_applicable_reason())

    def test_hidden_and_terminal_are_not_graphical_smoke_failures(self):
        self.assertIsNotNone(self.entry(Hidden="true").not_applicable_reason())
        self.assertIsNotNone(self.entry(Terminal="true").not_applicable_reason())

    def test_broken_present_entry_is_not_relabelled_absent(self):
        entry = self.entry(Exec="")
        self.assertIsNone(entry.not_applicable_reason())
        self.assertIn("neither Exec", entry.skip_reason())

    def test_nodisplay_does_not_mean_not_installed(self):
        self.assertIsNone(self.entry(NoDisplay="true").not_applicable_reason())


if __name__ == "__main__": unittest.main()
