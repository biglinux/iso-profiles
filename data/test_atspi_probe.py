from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import atspi_probe
from atspi_probe import (
    _is_transient_window,
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


class FakeAccessible:
    def __init__(self, name: str, pid: int, children=None, role: str = "frame") -> None:
        self.name = name
        self.pid = pid
        self.children = list(children or [])
        self.role = role

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


class FakeAtspi:
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

    def test_walk_does_not_yield_null_children(self) -> None:
        child = FakeAccessible("child", 42)
        root = FakeAccessible("root", 42, [None, child])
        with mock.patch.object(
            atspi_probe, "_atspi_import", return_value=(FakeAtspi, FakeGLib)
        ):
            walked = list(atspi_probe._walk(root))

        self.assertEqual(walked, [root, child])


class WidgetLabelTest(unittest.TestCase):
    def test_ignores_accelerators_and_padding_in_a_label(self) -> None:
        self.assertTrue(_label_matches("&Next", ["Next"]))
        self.assertTrue(_label_matches(" Install Now ", ["Install now"]))

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


class FakeWidget:
    def __init__(self, actions):
        self._actions = actions

    def get_action_iface(self):
        return self._actions


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


class WidgetActivationTest(unittest.TestCase):
    """Navigation activates a control through its own accessibility action,
    never through the reported rectangle, which is window-relative."""

    def _pair(self, name, actions):
        record = {
            "role": "button",
            "name": name,
            "showing": True,
            "sensitive": True,
            "center_x": 873,
            "center_y": 675,
        }
        return FakeWidget(actions), record

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

    def test_reports_a_control_that_exposes_no_usable_action(self) -> None:
        actions = FakeActions(["show-menu"])
        with mock.patch.object(
            atspi_probe, "_visible_widgets", return_value=[self._pair("Next", actions)]
        ):
            result = atspi_probe.activate_widget(0, "button", ["Next"])

        self.assertEqual(result["status"], "failed")
        self.assertIn("no usable accessibility action", result["error"])
        self.assertIn("show-menu", result["error"])


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
