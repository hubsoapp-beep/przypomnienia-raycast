import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import reminders


class RemindersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name, filename in (("STORE", ".reminders.json"),
                               ("HISTORY", ".reminders-history.md"), ("LOG", "log")):
            mock = patch.object(reminders, name, self.home / filename)
            mock.start()
            self.addCleanup(mock.stop)

    def cli(self, *args):
        return subprocess.run([sys.executable, reminders.__file__, *args],
                              env={**os.environ, "HOME": str(self.home)},
                              capture_output=True, text=True, timeout=10)

    def test_time_validation(self):
        for value in ("+5x", "+0m", "+-5m", "+2", "25:00", "", "2000-01-01 10:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reminders.parse_when(value)
        before = datetime.now()
        due = reminders.parse_when("+30m")
        self.assertGreaterEqual(due, before + timedelta(minutes=30))
        self.assertLessEqual(due, datetime.now() + timedelta(minutes=30))
        due = reminders.parse_when("00:00")
        self.assertGreater(due, datetime.now())
        self.assertEqual((due.hour, due.minute), (0, 0))

    def test_cli_validation_and_default(self):
        for args in (("add",), ("add", " "), ("add", "test", "+5x"), ("unknown",)):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
        result = self.cli("add", "Zażółć gęślą")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(reminders.load()[0]["text"], "Zażółć gęślą")
        self.assertIn("Zażółć gęślą", self.cli().stdout)

    def test_parallel_adds_preserve_every_item(self):
        workers = [subprocess.Popen(
            [sys.executable, reminders.__file__, "add", f"test {i}", "+30m"],
            env={**os.environ, "HOME": str(self.home)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for i in range(20)]
        for worker in workers:
            _, stderr = worker.communicate(timeout=15)
            self.assertEqual(worker.returncode, 0, stderr)
        self.assertEqual({item["text"] for item in reminders.load()},
                         {f"test {i}" for i in range(20)})

    def test_duplicate_completion_removes_only_one_and_preserves_new_items(self):
        item = {"text": "powtórka", "due": "2026-01-01T12:00"}
        new = {"text": "dodane podczas okna", "due": "2099-01-01T12:00"}
        reminders.save([item, item, new])
        reminders.finish_item(item, "done")
        self.assertEqual(reminders.load(), [item, new])
        self.assertIn("powtórka", reminders.HISTORY.read_text())

    def test_snooze_keeps_full_five_minutes(self):
        item = {"text": "test", "due": "2026-01-01T12:00"}
        reminders.save([item])
        fixed = datetime(2026, 9, 23, 12, 0, 47)
        with patch.object(reminders, "datetime") as clock:
            clock.now.return_value = fixed
            clock.fromisoformat.side_effect = datetime.fromisoformat
            reminders.finish_item(item, "snooze")
        self.assertEqual(reminders.load(), [{"text": "test", "due": "2026-09-23T12:05:47"}])
        self.assertFalse(reminders.HISTORY.exists())

    def test_failed_save_preserves_original(self):
        reminders.save([])
        original = reminders.STORE.read_bytes()
        with patch.object(reminders.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError), reminders.edit_items() as items:
                items.append({"text": "test", "due": "2099-01-01T12:00"})
        self.assertEqual(reminders.STORE.read_bytes(), original)
        self.assertEqual(list(self.home.glob(".reminders.json.*")), [])

    def test_invalid_store_is_not_overwritten(self):
        for data in ('{broken', '{}', '[{"text": "test", "due": "bad"}]',
                     '[{"text": "test", "due": "2026-09-23T12:00+02:00"}]'):
            with self.subTest(data=data):
                reminders.STORE.write_text(data)
                result = self.cli("add", "test")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(reminders.STORE.read_text(), data)

    def test_history_failure_preserves_reminder(self):
        item = {"text": "test", "due": "2026-01-01T12:00"}
        reminders.save([item])
        with patch.object(reminders, "log_done", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                reminders.finish_item(item, "done")
        self.assertEqual(reminders.load(), [item])

    def test_daemon_gui_failure_preserves_concurrent_add(self):
        item = {"text": "test", "due": "2026-01-01T12:00"}
        new = {"text": "nowe", "due": "2099-01-01T12:00"}
        reminders.save([item])

        def failed_gui(*args):
            with reminders.edit_items() as items:
                items.append(new)
            raise RuntimeError("GUI failure")

        with patch.object(reminders, "show_reminder", side_effect=failed_gui), \
                patch.object(reminders, "play_sound"), \
                patch.object(reminders.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                reminders.daemon_loop()
        self.assertEqual(reminders.load(), [item, new])

    def test_window_process_result_is_validated(self):
        item = {"text": "test", "due": "2026-01-01T12:00"}
        for outcome in ("done", "snooze", "unexpected"):
            with self.subTest(outcome=outcome), patch.object(reminders.subprocess, "run") as run:
                run.return_value.stdout = outcome + "\n"
                if outcome == "unexpected":
                    with self.assertRaises(ValueError):
                        reminders.show_reminder(item)
                else:
                    self.assertEqual(reminders.show_reminder(item), outcome)
                self.assertTrue(run.call_args.kwargs["check"])

    def test_second_daemon_is_rejected(self):
        with reminders.STORE.with_suffix(".daemon.lock").open("a") as lock:
            reminders.fcntl.flock(lock, reminders.fcntl.LOCK_EX)
            result = self.cli("daemon")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("już działa", result.stderr)

    @unittest.skipUnless(os.environ.get("REMINDERS_GUI_TESTS") == "1", "Wymaga pulpitu macOS")
    def test_cli_window_mouse_clicks(self):
        from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
                            CGEventCreateMouseEvent, CGEventPost, kCGHIDEventTap,
                            kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft)
        for expected, offset in (("snooze", -90), ("done", 90)):
            item = {"text": "Automatyczny test — " + expected, "due": "2026-01-01T12:00"}
            reminders.save([item])
            process = subprocess.Popen([sys.executable, reminders.__file__, "show"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                process.stdin.write(json.dumps(item))
                process.stdin.close()
                process.stdin = None
                deadline = time.monotonic() + 10
                window = None
                last_bounds = None
                stable_since = time.monotonic()
                while time.monotonic() < deadline:
                    window = next((w for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, 0)
                                   if w.get("kCGWindowOwnerPID") == process.pid
                                   and w["kCGWindowBounds"]["Width"] > 300), None)
                    bounds = dict(window["kCGWindowBounds"]) if window else None
                    if bounds != last_bounds:
                        stable_since = time.monotonic()
                        last_bounds = bounds
                    if window and time.monotonic() - stable_since >= 0.7:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(window, "Window did not appear")
                bounds = window["kCGWindowBounds"]
                point = (float(bounds["X"]) + float(bounds["Width"]) / 2 + offset,
                         float(bounds["Y"]) + float(bounds["Height"]) - 29)  # środek przycisku banera
                start = time.monotonic()
                for kind in (kCGEventLeftMouseDown, kCGEventLeftMouseUp):
                    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kind, point, kCGMouseButtonLeft))
                    time.sleep(0.02)
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout.strip(), expected)
                self.assertLess(time.monotonic() - start, 1)
                reminders.finish_item(item, stdout.strip())
                if expected == "done":
                    self.assertEqual(reminders.load(), [])
                else:
                    self.assertGreater(datetime.fromisoformat(reminders.load()[0]["due"]),
                                       datetime.now() + timedelta(minutes=4, seconds=59))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    @unittest.skipUnless(os.environ.get("REMINDERS_GUI_TESTS") == "1", "Wymaga pulpitu macOS")
    def test_gui_repeated_dismissals(self):
        code = '''
import reminders
import time
from AppKit import NSApplication, NSButton, NSTimer, NSEvent, NSLeftMouseDown, NSLeftMouseUp, NSKeyDown
from Foundation import NSRunLoop, NSRunLoopCommonModes
app = NSApplication.sharedApplication()

def descendants(view):
    for child in view.subviews():
        yield child
        yield from descendants(child)

for action, expected, delay in [('Odłóż 5 min', 'snooze', 0.2), ('OK', 'done', 0.9),
                                ('close', 'done', 0.9), ('key-1', 'snooze', 0.9)] * 2:
    clicked = []
    def dismiss(timer):
        wins = [w for w in app.windows() if w.isVisible() and w.title() == 'Przypomnienie']
        if not wins:
            # okno jeszcze nie doszło — spróbuj za chwilę zamiast wieszać test
            retry = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.2, False, dismiss)
            NSRunLoop.mainRunLoop().addTimer_forMode_(retry, NSRunLoopCommonModes)
            return
        window = wins[0]
        if action == 'close':
            window.close()  # borderless nie ma traffic lights — zamykamy wprost
        elif action == 'key-1':
            event = NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                NSKeyDown, (0, 0), 0, 0, window.windowNumber(), None, '1', '1', False, 18)
            app.postEvent_atStart_(event, False)
        else:
            button = next(v for v in descendants(window.contentView())
                          if isinstance(v, NSButton) and v.title() == action)
            point = button.convertPoint_toView_((button.bounds().size.width / 2,
                                                  button.bounds().size.height / 2), None)
            # Mouse events exercise AppKit's button tracking, unlike performClick_.
            for kind in (NSLeftMouseDown, NSLeftMouseUp):
                event = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                    kind, point, 0, 0, window.windowNumber(), None, 0, 1, 1)
                app.postEvent_atStart_(event, False)
        clicked.append(time.monotonic())
    timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(delay, False, dismiss)
    NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    result = reminders.show_banner('Test aplikacji — ' + action)
    assert clicked and time.monotonic() - clicked[0] < 0.5, 'Dismissal too slow'
    assert result == expected, (action, result)
    assert not any(w.isVisible() for w in app.windows() if w.title() == 'Przypomnienie')
    print(action, result, 'OK', flush=True)
    time.sleep(0.1)
'''
        result = subprocess.run([sys.executable, "-c", code],
                                cwd=Path(reminders.__file__).parent,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("OK"), 10)


if __name__ == "__main__":
    unittest.main()
