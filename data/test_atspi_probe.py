from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import atspi_probe
from atspi_probe import (
    _is_transient_window,
    _launch_process_scope,
    _owned_process_scope,
    _process_scope_exited,
    _label_matches,
    _name_matches,
    _normalize_label,
    _parse_x11_window,
    launch_process_exited,
    mem_available_mib,
    process_memory,
    process_tree_pss_mib,
    wait_for_x11_window,
)


class AtspiProbeTest(unittest.TestCase):
    def test_reads_available_system_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            meminfo = Path(directory, "meminfo")
            meminfo.write_text(
                "MemTotal: 4096000 kB\nMemAvailable: 2048000 kB\n", encoding="utf-8"
            )
            self.assertEqual(mem_available_mib(meminfo), 2000.0)

    def test_sums_pss_for_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, parent, pss in (
                (100, 1, 1024),
                (101, 100, 512),
                (102, 101, 256),
                (200, 1, 4096),
            ):
                process = proc / str(pid)
                process.mkdir()
                (process / "status").write_text(
                    f"Name:\ttest\nPPid:\t{parent}\n", encoding="utf-8"
                )
                (process / "smaps_rollup").write_text(
                    f"Pss: {pss} kB\n", encoding="utf-8"
                )

            result = process_tree_pss_mib(100, proc)

        self.assertEqual(result, 1.8)

    @staticmethod
    def _write_process(
        proc: Path, pid: int, parent: int, group: int, *, with_namespace_group: bool = True
    ) -> None:
        process = proc / str(pid)
        process.mkdir()
        nspgid = f"NSpgid:\t{group}\n" if with_namespace_group else ""
        (process / "status").write_text(
            f"Name:\ttest\nPPid:\t{parent}\n{nspgid}", encoding="utf-8"
        )
        # state, ppid, pgrp, session: comm deliberately contains ')' to prove
        # that the fallback parser splits after the final closing parenthesis.
        (process / "stat").write_text(
            f"{pid} (test) helper) S {parent} {group} {group} 0 0 0 0\n",
            encoding="utf-8",
        )

    def test_launch_scope_keeps_reparented_process_group_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            # The original group leader 100 has exited. Its GUI child was
            # re-parented to PID 1 but remains in process group 100.
            self._write_process(proc, 200, 1, 100)
            self._write_process(proc, 201, 200, 201)
            self._write_process(proc, 300, 1, 300)

            scope = _launch_process_scope(100, proc_root=proc)

        self.assertEqual(scope, {100, 200})
        self.assertNotIn(300, scope)

    def test_known_window_pid_does_not_import_its_unrelated_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 220, 1, 150)
            self._write_process(proc, 221, 1, 150)

            scope = _launch_process_scope(100, (220,), proc)

        self.assertEqual(scope, {100, 220})
        self.assertNotIn(221, scope)

    def test_live_nonleader_root_does_not_import_a_shared_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 100, 1, 50)
            self._write_process(proc, 101, 1, 50)
            self._write_process(proc, 102, 100, 50)

            scope = _launch_process_scope(100, proc_root=proc)

        self.assertEqual(scope, {100, 102})
        self.assertNotIn(101, scope)

    def test_ordinary_pid_scope_does_not_import_session_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 100, 1, 50)
            self._write_process(proc, 101, 1, 50)
            self._write_process(proc, 102, 100, 50)

            scope = _owned_process_scope(100, proc_root=proc)

        self.assertEqual(scope, {100, 102})
        self.assertNotIn(101, scope)

    def test_explicit_supervisor_root_enables_group_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 200, 1, 100)
            self._write_process(proc, 201, 1, 201)

            scope = _owned_process_scope(200, 100, proc_root=proc)

        self.assertEqual(scope, {100, 200})
        self.assertNotIn(201, scope)

    def test_process_group_falls_back_to_proc_stat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 240, 1, 140, with_namespace_group=False)

            scope = _launch_process_scope(140, proc_root=proc)

        self.assertEqual(scope, {140, 240})

    def test_scope_is_live_after_group_leader_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._write_process(proc, 260, 1, 160)
            scope = _launch_process_scope(160, proc_root=proc)

            self.assertFalse(_process_scope_exited(scope, proc))
            for child in (proc / "260").iterdir():
                child.unlink()
            (proc / "260").rmdir()
            self.assertTrue(_process_scope_exited(scope, proc))

    def test_empty_scope_is_not_proof_of_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(_process_scope_exited(set(), Path(directory)))

    def test_keeps_rss_when_pss_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "100"
            process.mkdir()
            (process / "status").write_text(
                "Name:\ttest\nPPid:\t1\nVmRSS:\t2048 kB\n", encoding="utf-8"
            )

            result = process_tree_pss_mib(100, proc)
            memory = process_memory(100, proc)

        self.assertIsNone(result)
        self.assertEqual(memory["rss_mib"], 2.0)
        self.assertIsNone(memory["pss_mib"])
        self.assertEqual(memory["process_count"], 1)

    def test_detects_exited_launch_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "123").mkdir()
            self.assertFalse(launch_process_exited(123, proc))
            self.assertTrue(launch_process_exited(456, proc))

    def test_treats_zombie_launch_process_as_exited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = Path(directory, "123")
            process.mkdir()
            (process / "status").write_text("State:\tZ (zombie)\n", encoding="utf-8")

            self.assertTrue(launch_process_exited(123, Path(directory)))

    def test_matches_desktop_name_against_executable_alias(self) -> None:
        self.assertTrue(_name_matches("gimp / GIMP Startup", "GNU Image gimp-3.2"))
        self.assertTrue(
            _name_matches(
                "Big-Driver-Manager / Big-Driver-Manager", "Drivers big-driver-manager"
            )
        )

    def test_ignores_startup_splash_as_final_window(self) -> None:
        self.assertTrue(_is_transient_window({"name": "GIMP Startup"}))
        self.assertFalse(
            _is_transient_window({"name": "GNU Image Manipulation Program"})
        )

    def test_matches_expected_name_in_application_or_window(self) -> None:
        self.assertTrue(
            _name_matches(
                "soffice.bin Untitled 1 — LibreOffice Calc", "LibreOffice Calc"
            )
        )

    def test_x11_wait_open_is_available_without_atspi_window(self) -> None:
        self.assertTrue(callable(wait_for_x11_window))

    def test_parses_x11_window_pid_and_name(self) -> None:
        window = _parse_x11_window(
            "0x1400002",
            "_NET_WM_PID(CARDINAL) = 5822\n"
            '_NET_WM_NAME(UTF8_STRING) = "No file - mpv"\n',
        )
        self.assertEqual(window["pid"], 5822)
        self.assertEqual(window["name"], "No file - mpv")


class FakeError(Exception):
    pass


class FakeGLib:
    Error = FakeError


class FakeStateSet:
    def __init__(self, states=()) -> None:
        self.states = set(states)

    def contains(self, state):
        return state in self.states


class FakeAccessible:
    def __init__(self, name: str, pid: int, children=None, role: str = "frame") -> None:
        self.name = name
        self.pid = pid
        self.children = list(children or [])
        self.role = role
        self.states = {"showing"}

    def get_name(self):
        return self.name

    def get_process_id(self):
        return self.pid

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index: int):
        return self.children[index]

    def get_role_name(self):
        return self.role

    def get_state_set(self):
        return FakeStateSet(self.states)


class FakeAtspi:
    class StateType:
        SHOWING = "showing"
        DEFUNCT = "defunct"

    desktop = None

    @classmethod
    def get_desktop(cls, _index: int):
        return cls.desktop


class AtspiNullChildrenTest(unittest.TestCase):
    def records(self):
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            return list(atspi_probe._window_records())

    def test_null_desktop_is_reported_cleanly(self) -> None:
        FakeAtspi.desktop = None
        with self.assertRaisesRegex(atspi_probe.ProbeError, "desktop is unavailable"):
            self.records()

    def test_null_application_and_window_are_ignored(self) -> None:
        window = FakeAccessible("Settings", 42, role="frame")
        application = FakeAccessible(
            "systemsettings", 42, [None, window], "application"
        )
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [None, application])

        records = self.records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1]["name"], "Settings")
        self.assertEqual(records[0][1]["pid"], 42)
        self.assertEqual(records[0][1]["identity"], "1")
        self.assertEqual(records[0][1]["application_index"], 1)

    def test_window_state_is_read_only_when_requested(self):
        window = FakeAccessible("Settings", 42)
        window.states = {"defunct"}
        application = FakeAccessible("systemsettings", 42, [window], "application")
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [application])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            record = list(
                atspi_probe._window_records(
                    allowed_pids={42}, include_window_state=True
                )
            )[0][1]
        self.assertFalse(record["showing"])
        self.assertTrue(record["defunct"])

    def test_scoped_enumeration_does_not_query_unrelated_windows(self):
        unrelated = FakeAccessible("shell", 99)
        unrelated.get_name = mock.Mock(side_effect=FakeError("unrelated name unavailable"))
        unrelated.get_child_count = mock.Mock(side_effect=FakeError("unrelated view unavailable"))
        target = FakeAccessible("app", 42, [FakeAccessible("Window", 42)])
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [unrelated, target])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            records = list(atspi_probe._window_records(allowed_pids={42}))
        self.assertEqual([record["pid"] for _, record in records], [42])
        unrelated.get_name.assert_not_called()
        unrelated.get_child_count.assert_not_called()

    def test_scoped_enumeration_starts_with_the_recent_target(self):
        order = []
        old = FakeAccessible("old", 99)
        target = FakeAccessible("target", 42, [FakeAccessible("Window", 42)])
        old_get_pid, target_get_pid = old.get_process_id, target.get_process_id
        old.get_process_id = lambda: (order.append("old"), old_get_pid())[1]
        target.get_process_id = lambda: (order.append("target"), target_get_pid())[1]
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [old, target])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            records = list(atspi_probe._window_records(allowed_pids={42}))
        self.assertEqual(records[0][1]["pid"], 42)
        self.assertEqual(order[0], "target")

    def test_scoped_enumeration_revisits_a_pid_verified_application_hint_first(self):
        target = FakeAccessible("target", 42, [FakeAccessible("Window", 42)])
        unrelated = FakeAccessible("shell", 99)
        unrelated.get_process_id = mock.Mock(
            side_effect=AssertionError("unrelated provider must not be queried first")
        )
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [target, unrelated])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = atspi_probe._window_records(
                allowed_pids={42}, preferred_application_index=0
            )
            first = next(records)
            records.close()
        self.assertEqual(first[1]["pid"], 42)
        self.assertEqual(first[1]["application_index"], 0)
        unrelated.get_process_id.assert_not_called()

    def test_exact_window_identity_is_read_before_other_target_windows(self):
        slow = FakeAccessible("Slow", 42)
        slow.path = "/slow"
        slow.get_name = mock.Mock(
            side_effect=AssertionError("non-target window semantics must not be read first")
        )
        target_window = FakeAccessible("Target", 42)
        target_window.path = "/target"
        target = FakeAccessible("target", 42, [slow, target_window], "application")
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [target])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = atspi_probe._window_records(
                allowed_pids={42},
                preferred_application_index=0,
                stop_after_preferred_match=True,
                preferred_window_identity="/target",
            )
            first = next(records)
            records.close()
        self.assertEqual(first[1]["identity"], "/target")
        slow.get_name.assert_not_called()

    def test_exact_window_identity_survives_a_shifted_registry_slot(self):
        target_window = FakeAccessible("Target", 42)
        target_window.path = "/target"
        target = FakeAccessible("target", 42, [target_window], "application")
        stale = FakeAccessible("stale", 99, [FakeAccessible("Other", 99)], "application")
        older = FakeAccessible("older", 98)
        older.get_process_id = mock.Mock(
            side_effect=AssertionError("exact target identity must stop before older providers")
        )
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [older, target, stale])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = list(
                atspi_probe._window_records(
                    allowed_pids={42},
                    preferred_application_index=2,
                    preferred_window_identity="/target",
                )
            )
        self.assertEqual([record["identity"] for _, record in records], ["/target"])
        self.assertEqual(records[0][1]["application_index"], 1)
        older.get_process_id.assert_not_called()

    def test_pid_verified_hint_can_stop_before_unrelated_registry_providers(self):
        target = FakeAccessible("target", 42, [FakeAccessible("Window", 42)])
        unrelated = FakeAccessible("shell", 99)
        unrelated.get_process_id = mock.Mock(
            side_effect=AssertionError("unrelated provider must not be queried")
        )
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [target, unrelated])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = list(
                atspi_probe._window_records(
                    allowed_pids={42},
                    preferred_application_index=0,
                    stop_after_preferred_match=True,
                )
            )
        self.assertEqual([record["pid"] for _, record in records], [42])
        unrelated.get_process_id.assert_not_called()

    def test_stale_application_hint_falls_back_after_pid_mismatch(self):
        stale_slot = FakeAccessible("unrelated", 99)
        target = FakeAccessible("target", 42, [FakeAccessible("Window", 42)])
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [stale_slot, target])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = list(
                atspi_probe._window_records(
                    allowed_pids={42}, preferred_application_index=0
                )
            )
        self.assertEqual([record["pid"] for _, record in records], [42])
        self.assertEqual(records[0][1]["application_index"], 1)

    def test_stale_hint_resumes_newest_first_instead_of_scanning_neighbours(self):
        order = []
        providers = []
        for index in range(20):
            pid = 42 if index == 19 else 100 + index
            children = [FakeAccessible("Target", 42)] if pid == 42 else []
            provider = FakeAccessible(f"provider-{index}", pid, children, "application")
            original = provider.get_process_id
            provider.get_process_id = (
                lambda label, getter: lambda: (order.append(label), getter())[1]
            )(f"provider-{index}", original)
            providers.append(provider)
        FakeAtspi.desktop = FakeAccessible("desktop", 1, providers)

        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            records = atspi_probe._window_records(
                allowed_pids={42}, preferred_application_index=14
            )
            first = next(records)
            records.close()

        self.assertEqual(order, ["provider-14", "provider-19"])
        self.assertEqual(first[1]["pid"], 42)
        self.assertEqual(first[1]["application_index"], 19)

    def test_scoped_enumeration_does_not_hide_target_failure(self):
        target = FakeAccessible("app", 42)
        target.get_child_count = mock.Mock(side_effect=FakeError("target unavailable"))
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [target])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             self.assertRaisesRegex(atspi_probe.ProbeError, "incomplete"):
            list(atspi_probe._window_records(allowed_pids={42}))

    def test_dead_registry_provider_is_skipped_without_hiding_live_windows(self):
        stale_window = FakeAccessible("Gone", 42)
        stale_window.get_name = mock.Mock(side_effect=FakeError("provider vanished"))
        stale = FakeAccessible("stale", 42, [stale_window], "application")
        live = FakeAccessible("live", 43, [FakeAccessible("Settings", 43)], "application")
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [stale, live])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             mock.patch.object(atspi_probe, "launch_process_exited", side_effect=lambda pid: pid == 42):
            records = list(atspi_probe._window_records())
        self.assertEqual([record["pid"] for _, record in records], [43])

    def test_live_registry_provider_failure_remains_incomplete(self):
        broken_window = FakeAccessible("Broken", 42)
        broken_window.get_name = mock.Mock(side_effect=FakeError("provider unavailable"))
        target = FakeAccessible("app", 42, [broken_window], "application")
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [target])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             mock.patch.object(atspi_probe, "launch_process_exited", return_value=False), \
             self.assertRaisesRegex(atspi_probe.ProbeError, "window enumeration was incomplete"):
            list(atspi_probe._window_records())

    def test_baseline_reads_only_window_identity_and_pid(self):
        window = FakeAccessible("Sensitive title", 42)
        window.path = "/org/a11y/window/42"
        window.get_name = mock.Mock(
            side_effect=AssertionError("baseline must not read a window name")
        )
        window.get_role_name = mock.Mock(
            side_effect=AssertionError("baseline must not read a window role")
        )
        window.get_child_count = mock.Mock(
            side_effect=AssertionError("baseline must not walk window content")
        )
        application = FakeAccessible("editor", 42, [window], "application")
        application.get_name = mock.Mock(
            side_effect=AssertionError("baseline must not read an application name")
        )
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [application])

        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ), mock.patch.object(atspi_probe.time, "monotonic", return_value=0):
            records = atspi_probe._baseline_window_records(1)

        self.assertEqual(
            records,
            [{"key": "42\0/org/a11y/window/42", "pid": 42}],
        )
        application.get_name.assert_not_called()
        window.get_name.assert_not_called()
        window.get_role_name.assert_not_called()
        window.get_child_count.assert_not_called()

    def test_baseline_keeps_live_provider_errors_strict(self):
        application = FakeAccessible("editor", 42, [], "application")
        application.get_child_count = mock.Mock(side_effect=FakeError("busy"))
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [application])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ), mock.patch.object(atspi_probe.time, "monotonic", return_value=0), \
             mock.patch.object(atspi_probe, "launch_process_exited", return_value=False), \
             self.assertRaisesRegex(atspi_probe.ProbeError, "baseline application"):
            atspi_probe._baseline_window_records(1)

    def test_empty_scope_returns_no_window(self):
        FakeAtspi.desktop = FakeAccessible("desktop", 1, [FakeAccessible("other", 99)])
        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)):
            self.assertEqual(list(atspi_probe._window_records(allowed_pids=set())), [])

    def test_walk_does_not_yield_null_children(self) -> None:
        child = FakeAccessible("child", 42)
        root = FakeAccessible("root", 42, [None, child])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            walked = list(atspi_probe._walk(root))

        self.assertEqual(walked, [root, child])

    def test_widget_records_retain_their_application_registry_hint(self) -> None:
        window = FakeAccessible("Dialog", 42)
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ), mock.patch.object(
            atspi_probe,
            "_widget_record",
            return_value={"showing": True, "defunct": False, "focused": True},
        ):
            records = list(
                atspi_probe._showing_widgets_in_window(
                    window, 42, "Dialog", None, application_index=7
                )
            )

        self.assertEqual(records[0][1]["application_index"], 7)


class WidgetLabelTest(unittest.TestCase):
    def test_ignores_accelerators_and_padding_in_a_label(self) -> None:
        self.assertTrue(_label_matches("&Next", ["Next"]))
        self.assertTrue(_label_matches(" Install Now ", ["Install now"]))

    def test_folds_diacritics_so_a_translated_label_still_matches(self) -> None:
        # The installer names this button "Concluído"; a caller that spells it
        # without the accent, or a translation that adds one, must still match.
        self.assertEqual(_normalize_label("Concluído"), "concluido")
        self.assertTrue(_label_matches("Próximo", ["Proximo"]))
        self.assertTrue(_label_matches("Avancar", ["Avançar"]))
        # Folding accents must not turn different words into the same one.
        self.assertFalse(_label_matches("Concluído", ["Concluir"]))

    def test_accepts_any_label_when_none_is_required(self) -> None:
        self.assertTrue(_label_matches("whatever", []))

    def test_rejects_a_different_control(self) -> None:
        self.assertFalse(_label_matches("Cancel", ["Next", "Continue"]))


class FakeActions:
    def __init__(self, names, performed=True):
        self.names = names
        self.performed = performed
        self.done = []

    def get_n_actions(self):
        return len(self.names)

    def get_action_name(self, index):
        return self.names[index]

    def do_action(self, index):
        self.done.append(self.names[index])
        return self.performed


class FakeComponent:
    def __init__(self, *, focusable=True):
        self._focusable = focusable
        self.focus_requests = 0

    def grab_focus(self):
        self.focus_requests += 1
        return self._focusable


class FakeWidget:
    def __init__(self, actions, component=None):
        self._actions = actions
        self._component = component

    def get_action_iface(self):
        return self._actions

    def get_component_iface(self):
        return self._component


class RichTextLabelTest(unittest.TestCase):
    """Calamares names some controls with their whole rich-text description."""

    ERASE = (
        "<strong>Erase disk</strong><br/>This will "
        '<font color="red">delete</font> all data currently present on the '
        "selected storage device."
    )
    MANUAL = (
        "<strong>Manual partitioning</strong><br/>You can create or resize "
        "partitions yourself."
    )

    def test_matches_the_heading_of_a_rich_text_label(self) -> None:
        self.assertTrue(_label_matches(self.ERASE, ["Erase disk"]))
        self.assertTrue(_label_matches(self.MANUAL, ["Manual partitioning"]))

    def test_does_not_confuse_two_rich_text_controls(self) -> None:
        self.assertFalse(_label_matches(self.MANUAL, ["Erase disk"]))
        self.assertFalse(_label_matches(self.ERASE, ["Manual partitioning"]))

    def test_anchors_at_the_start_of_the_label(self) -> None:
        self.assertFalse(_label_matches("Do not erase disk", ["Erase disk"]))

    def test_strips_markup_before_comparing(self) -> None:
        self.assertEqual(_normalize_label("<b>Next</b>"), "next")


class WidgetSearchTest(unittest.TestCase):
    def _pair(self, role, name, sensitive=True, actions=None):
        record = {
            "role": role,
            "name": name,
            "showing": True,
            "sensitive": sensitive,
            "center_x": 5,
            "center_y": 6,
        }
        return FakeWidget(actions or FakeActions(["click"])), record

    def test_accepts_any_of_the_listed_roles(self) -> None:
        with mock.patch.object(
            atspi_probe, "_visible_widgets", return_value=[self._pair("button", "Next")]
        ):
            result = atspi_probe.wait_for_widget(0, "push button|button", ["Next"])

        self.assertEqual(result["status"], "passed")

    def test_reports_every_role_it_saw_when_nothing_matches(self) -> None:
        with mock.patch.object(
            atspi_probe,
            "_visible_widgets",
            return_value=[self._pair("document web", "")],
        ):
            result = atspi_probe.wait_for_widget(0, "push button", ["Next"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("all roles observed: document web=1", result["error"])

    def test_skips_an_insensitive_control(self) -> None:
        with mock.patch.object(
            atspi_probe,
            "_visible_widgets",
            return_value=[self._pair("push button", "Next", sensitive=False)],
        ):
            result = atspi_probe.wait_for_widget(0, "push button", ["Next"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("(insensitive)", result["error"])

    @staticmethod
    def _semantic_record(node):
        return {
            "role": node.role,
            "name": node.name,
            "showing": True,
            "sensitive": True,
            "checked": False,
            "selected": False,
            "focused": False,
            "focusable": True,
            "defunct": False,
            "accessible_id": "",
            "identity": f"/{node.name or 'node'}",
        }

    def test_positive_witness_stops_before_unrelated_slow_subtree(self) -> None:
        target = FakeAccessible("Welcome to the Calamares installer", 42, role="label")
        slow = FakeAccessible("slow", 42)
        root = FakeAccessible("Calamares", 42, [target, slow])
        record = {
            "pid": 42,
            "name": "Calamares",
            "application_index": 7,
        }

        def semantics(node):
            if node is slow:
                raise AssertionError("a positive witness must stop before unrelated siblings")
            return self._semantic_record(node)

        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             mock.patch.object(atspi_probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(atspi_probe, "_window_records", return_value=iter([(root, record)])), \
             mock.patch.object(atspi_probe, "_widget_record", side_effect=semantics):
            result = atspi_probe.wait_for_widget(
                1,
                "label",
                ["Welcome to the Calamares installer"],
                42,
                application_index=7,
                positive_witness=True,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["proof"], "positive-witness")
        self.assertFalse(result["tree_complete"])

    def test_positive_witness_survives_one_broken_sibling(self) -> None:
        broken = FakeAccessible("broken", 42)
        target = FakeAccessible("Welcome to the Calamares installer", 42, role="label")
        root = FakeAccessible("Calamares", 42, [broken, target])
        record = {"pid": 42, "name": "Calamares", "application_index": 7}

        def semantics(node):
            if node is broken:
                raise atspi_probe.ProbeError("provider disappeared")
            return self._semantic_record(node)

        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             mock.patch.object(atspi_probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(atspi_probe, "_window_records", return_value=iter([(root, record)])), \
             mock.patch.object(atspi_probe, "_widget_record", side_effect=semantics):
            result = atspi_probe.wait_for_widget(
                1, "label", ["Welcome to the Calamares installer"], 42,
                positive_witness=True,
            )

        self.assertEqual(result["status"], "passed")

    def test_positive_witness_without_target_keeps_broken_tree_inconclusive(self) -> None:
        broken = FakeAccessible("broken", 42)
        root = FakeAccessible("Calamares", 42, [broken])
        record = {"pid": 42, "name": "Calamares", "application_index": 7}

        def semantics(node):
            if node is broken:
                raise atspi_probe.ProbeError("provider disappeared")
            return self._semantic_record(node)

        with mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)), \
             mock.patch.object(atspi_probe, "_owned_process_scope", return_value={42}), \
             mock.patch.object(atspi_probe, "_window_records", return_value=iter([(root, record)])), \
             mock.patch.object(atspi_probe, "_widget_record", side_effect=semantics), \
             self.assertRaisesRegex(atspi_probe.ProbeError, "positive witness was not found"):
            atspi_probe.wait_for_widget(
                0, "label", ["Welcome to the Calamares installer"], 42,
                positive_witness=True,
            )

    def test_positive_witness_cannot_prove_absence_or_checked_state(self) -> None:
        with self.assertRaisesRegex(atspi_probe.ProbeError, "cannot be used"):
            atspi_probe.wait_for_widget(
                0, "button", ["Install"], 42,
                absent=True, positive_witness=True,
            )
        with self.assertRaisesRegex(atspi_probe.ProbeError, "cannot be used"):
            atspi_probe.wait_for_widget(
                0, "radio button", ["Erase disk"], 42,
                checked=True, positive_witness=True,
            )

    def test_process_transition_uses_nearby_application_hint_and_stops_on_match(self) -> None:
        old_window = object()
        target_window = object()
        unrelated_window = object()
        windows = [
            (old_window, {
                "pid": 4924, "name": "BigLinux Installation",
                "application_index": 14, "application_window_ordinal": 0,
                "application_candidate_window_count": 1,
            }),
            (target_window, {
                "pid": 5170, "name": "Calamares",
                "application_index": 15, "application_window_ordinal": 0,
                "application_candidate_window_count": 1,
            }),
            (unrelated_window, {
                "pid": 5180, "name": "Unrelated child",
                "application_index": 16, "application_window_ordinal": 0,
                "application_candidate_window_count": 1,
            }),
        ]
        visits = []

        def widgets(window, pid, name, deadline, *, application_index=None, **_kwargs):
            visits.append(application_index)
            if window is unrelated_window:
                raise AssertionError("search must stop after the matching launch application")
            label = "Welcome to the Calamares installer" if window is target_window else "Continue"
            return [self._pair("label", label)]

        with mock.patch.object(atspi_probe, "_process_tree", return_value={4400, 4924, 5170, 5180}), \
             mock.patch.object(atspi_probe, "_window_records", return_value=iter(windows)) as read, \
             mock.patch.object(atspi_probe, "_showing_widgets_in_window", side_effect=widgets):
            result = atspi_probe.wait_for_widget(
                1, "label", ["Welcome to the Calamares installer"], 4400,
                application_index=14,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["widget"]["name"], "Welcome to the Calamares installer")
        self.assertEqual(visits, [14, 15])
        self.assertEqual(read.call_args.kwargs["preferred_application_index"], 14)


class WidgetActivationTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib))
        patcher.start()
        self.addCleanup(patcher.stop)

    """The explicit AT-action API does not claim keyboard reachability."""

    def _pair(self, name, actions, component=None):
        record = {
            "role": "button",
            "name": name,
            "showing": True,
            "sensitive": True,
            "center_x": 873,
            "center_y": 675,
        }
        return FakeWidget(actions, component), record

    def test_performs_the_click_action(self) -> None:
        actions = FakeActions(["click"])
        with mock.patch.object(
            atspi_probe, "_visible_widgets", return_value=[self._pair("Next", actions)]
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["action"], "click")
        self.assertEqual(actions.done, ["click"])

    def test_ignores_an_action_it_must_not_trigger(self) -> None:
        actions = FakeActions(["show-menu", "press"])
        with mock.patch.object(
            atspi_probe, "_visible_widgets", return_value=[self._pair("Next", actions)]
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["action"], "press")
        self.assertEqual(actions.done, ["press"])

    def test_never_teleports_focus_to_rescue_a_control(self) -> None:
        # Calamares' finished page reports its "Done" button with an empty
        # action list, which failed a release job after a complete and correct
        # installation. Focus is the other thing AT-SPI can do to a control,
        # and it leaves the press to the caller instead of to a coordinate.
        actions = FakeActions(["show-menu"])
        component = FakeComponent()
        with mock.patch.object(
            atspi_probe,
            "_visible_widgets",
            return_value=[self._pair("Next", actions, component)],
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("no usable accessibility action", result["error"])
        self.assertEqual(component.focus_requests, 0)
        self.assertEqual(actions.done, [])

    def test_reports_a_control_that_neither_acts_nor_focuses(self) -> None:
        actions = FakeActions(["show-menu"])
        component = FakeComponent(focusable=False)
        with mock.patch.object(
            atspi_probe,
            "_visible_widgets",
            return_value=[self._pair("Next", actions, component)],
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("no usable accessibility action", result["error"])
        self.assertEqual(component.focus_requests, 0)

    def test_prefers_an_action_over_focus(self) -> None:
        # Focus plus a key press is the fallback, never the first choice: a
        # focused control that swallows Return would look activated.
        actions = FakeActions(["click"])
        component = FakeComponent()
        with mock.patch.object(
            atspi_probe,
            "_visible_widgets",
            return_value=[self._pair("Next", actions, component)],
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["action"], "click")
        self.assertEqual(component.focus_requests, 0)


class WindowAcceptanceTest(unittest.TestCase):
    """The approval rule: a window belonging to the launched process tree is
    enough, whatever its title or accessibility subtree looks like."""

    def _wait(self, windows, expected_pid, tree):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory, "baseline.json")
            state.write_text('{"windows": []}', encoding="utf-8")
            with (
                mock.patch.object(atspi_probe, "baseline_keys", return_value=set()),
                mock.patch.object(
                    atspi_probe,
                    "accessible_snapshot",
                    return_value={"windows": windows, "mem_available_mib": 100.0},
                ),
                mock.patch.object(atspi_probe, "_process_tree", return_value=tree),
                mock.patch.object(
                    atspi_probe, "sample_process_memory", return_value={}
                ),
            ):
                return atspi_probe.wait_for_window_change(
                    state, 0.5, opening=True, expected_pid=expected_pid
                )

    def _window(self, pid, name="", children=0):
        return {
            "key": f"w{pid}",
            "pid": pid,
            "name": name,
            "application": "",
            "role": "frame",
            "children": children,
        }

    def test_accepts_untitled_window_without_accessible_children(self) -> None:
        result = self._wait([self._window(42)], expected_pid=42, tree={42})

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["accessible_window"])

    def test_accepts_window_owned_by_a_forked_child(self) -> None:
        result = self._wait([self._window(99)], expected_pid=42, tree={42, 99})

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["pid"], 99)

    def test_rejects_window_outside_the_launched_process_tree(self) -> None:
        result = self._wait(
            [self._window(1234, "Notification")], expected_pid=42, tree={42}
        )

        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()


class WalkBoundsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib))
        patcher.start()
        self.addCleanup(patcher.stop)

    """A walk is bounded by time, not only by node count.

    Every node costs several synchronous D-Bus round trips, so an application
    that is on the bus but not answering makes the node limit meaningless: the
    desktop-wide walk in dump-widgets outlived a five-minute budget and read as
    a hang.
    """

    class SlowAccessible:
        """One node per call, each taking a tenth of a second to answer."""

        def __init__(self, clock):
            self._clock = clock

        def get_child_count(self):
            self._clock[0] += 0.1
            return 1

        def get_child_at_index(self, _index):
            return type(self)(self._clock)

    def test_the_walk_stops_at_its_deadline(self) -> None:
        clock = [0.0]
        node = self.SlowAccessible(clock)
        with mock.patch.object(atspi_probe.time, "monotonic", lambda: clock[0]):
            with self.assertRaises(atspi_probe.WalkTruncated):
                for _ in atspi_probe._walk(node, limit=10_000, deadline=1.0):
                    pass

    def test_the_walk_without_a_deadline_still_stops_at_the_node_limit(self) -> None:
        clock = [0.0]
        node = self.SlowAccessible(clock)
        visited = []
        with self.assertRaises(atspi_probe.WalkTruncated):
            for item in atspi_probe._walk(node, limit=5):
                visited.append(item)
        self.assertEqual(len(visited), 5)


class DumpWidgetsBudgetTest(unittest.TestCase):
    def test_dump_widgets_reports_truncation(self) -> None:
        # The operation accepted --timeout and ignored it, so raising the
        # budget from 120 to 300 seconds changed nothing at all.
        with mock.patch.object(atspi_probe, "_visible_widgets", return_value=[]):
            result = atspi_probe.dump_widget_tree(None, timeout=30)
        self.assertEqual(result["status"], "passed")
        self.assertIn("truncated", result)
        self.assertFalse(result["truncated"])
