#!/usr/bin/env python3
"""Mini przypomnienia w stylu powiadomień systemowych macOS. Bez zależności (tylko stdlib + PyObjC z systemu)."""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

STORE = Path.home() / ".reminders.json"
HISTORY = Path.home() / ".reminders-history.md"
LOG = Path("/tmp/przypomnienia.log")
# dwa krótkie 'yip' — szczeknięcie yorka (generowane, /tmp/make_bark.py)
SOUND = str(Path(__file__).with_name("bark.wav"))
SNOOZE_MIN = 5


def log(msg):
    with LOG.open("a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def load():
    if STORE.exists():
        items = json.loads(STORE.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError("Plik przypomnień musi zawierać listę")
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                    or not item["text"].strip() or not isinstance(item.get("due"), str)):
                raise ValueError("Nieprawidłowe przypomnienie w pliku")
            if datetime.fromisoformat(item["due"]).tzinfo is not None:
                raise ValueError("Termin musi być zapisany w czasie lokalnym")
        return items
    return []


def save(items):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=STORE.parent,
                                         prefix=STORE.name + ".", delete=False) as f:
            temporary = Path(f.name)
            json.dump(items, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, STORE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def edit_items():
    with STORE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        items = load()
        yield items
        save(items)


_REL = re.compile(r"^(?P<n>[0-9]+)\s*(?P<unit>[a-ząćęłńóśźż]*)$", re.IGNORECASE)
_HOURS = {"h", "godz", "godziny", "godzin"}
_MINUTES = {"m", "min", "minut", "minuty", "minu"}
MAX_AHEAD = timedelta(days=366)


def parse_when(s):
    """'13' | '+30m' | '2h' | '14:30' | '2026-09-24 14:30'.

    Sama liczba to minuty od teraz — '13' znaczy 'za 13 minut'. Kolon zawsze
    oznacza zegar, więc '13:00' to godzina 13:00, a nie 13 minut.
    """
    s = s.strip()
    now = datetime.now()
    rel = _REL.match(s.lstrip("+").strip())
    if rel:
        n = int(rel["n"])
        unit = rel["unit"].lower()
        if unit in _HOURS:
            delta = timedelta(hours=n)
        elif unit in _MINUTES or not unit:
            delta = timedelta(minutes=n)
        else:
            raise ValueError("Nieznana jednostka czasu — użyj min albo h, np. 13 albo 2h")
        if delta <= timedelta(0):
            raise ValueError("Podaj dodatni czas, np. 13 (13 minut) albo 2h")
        if delta > MAX_AHEAD:
            raise ValueError("Nie planuję tak daleko w przyszłości (max 366 dni)")
        return now + delta
    if " " in s:
        due = datetime.strptime(s, "%Y-%m-%d %H:%M")
        if due <= now:
            raise ValueError("Podana data już minęła")
        return due
    due = datetime.strptime(s, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day)
    if due <= now:
        due += timedelta(days=1)  # godzina już minęła → jutro
    return due


def play_sound(times=2):
    try:
        for _ in range(times):
            subprocess.run(["afplay", SOUND], timeout=5, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"Sound error: {e}")





def log_done(text):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", encoding="utf-8") as f:
        if new:
            f.write("# Zrobione\n\n")
        f.write(f"- [x] {datetime.now():%Y-%m-%d %H:%M} — {text}\n")


_UI = {}


def ui():
    """Klasy ObjC definiujemy RAZ — PyObjC nie pozwala redefiniować klasy o tej samej nazwie."""
    if _UI:
        return _UI
    from AppKit import NSApplication, NSButton, NSWindow
    from Foundation import NSObject
    import objc

    def stop_app():
        NSApplication.sharedApplication().stopModal()

    class Btn(NSButton):
        def acceptsFirstMouse_(self, event):
            return True  # pierwszy klik działa nawet gdy okno nie jest jeszcze aktywne

    class KeyWindow(NSWindow):
        # borderless okno domyślnie nie może zostać klawiszowe (brak belki tytułowej),
        # więc skróty 1/2/Return/Esc nigdy by nie dotarły
        def canBecomeKeyWindow(self):
            return True

    class Handler(NSObject):
        def initWithSnooze_done_close_(self, snooze_fn, done_fn, close_fn):
            self = objc.super(Handler, self).init()
            self.snooze_fn, self.done_fn, self.close_fn = snooze_fn, done_fn, close_fn
            return self

        def doOk_(self, sender):
            self.done_fn()
            self.close_fn()
            stop_app()

        def doSnooze_(self, sender):
            self.snooze_fn()
            self.close_fn()
            stop_app()

    class WinDelegate(NSObject):
        # żółty = odłóż (minimalizacja bez sensu — ukryte okno zablokowałoby daemona na zawsze)
        def initWithDone_snooze_(self, done_fn, snooze_fn):
            self = objc.super(WinDelegate, self).init()
            self.done_fn, self.snooze_fn = done_fn, snooze_fn
            return self

        def windowWillClose_(self, note):
            self.done_fn()
            stop_app()

        def windowWillMiniaturize_(self, note):
            self.snooze_fn()
            stop_app()

    _UI.update(Btn=Btn, Handler=Handler, WinDelegate=WinDelegate, KeyWindow=KeyWindow)
    return _UI


def show_banner(text, due=None):
    """Banner w stylu powiadomień macOS (prawy górny róg). Zwraca 'done' albo 'snooze'."""
    from AppKit import (NSApplication, NSScreen, NSColor, NSTextField,
                        NSFont, NSBackingStoreBuffered, NSVisualEffectView, NSImage,
                        NSImageView, NSWorkspace)
    from Foundation import NSMakeRect
    from Quartz import CGColorCreateGenericGray

    app = NSApplication.sharedApplication()
    ACCENT = NSColor.controlAccentColor()
    ICON = Path(__file__).with_name("icon.png")
    BW, PAD = 382, 16
    lines = max(1, len(text) // 38 + 1)
    BH = 104 + min(66, max(22, lines * 21))
    Btn, Handler, WinDelegate = (ui()[k] for k in ("Btn", "Handler", "WinDelegate"))
    result = {"value": "snooze"}

    vf = NSScreen.mainScreen().visibleFrame()  # omija menu bar i Docka
    win = ui()["KeyWindow"].alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(vf.origin.x + vf.size.width - BW - PAD,
                   vf.origin.y + vf.size.height - BH - 12, BW, BH),
        0, NSBackingStoreBuffered, False)  # borderless — jak systemowy baner
    win.setTitle_("Przypomnienie")
    win.setReleasedWhenClosed_(False)
    win.setLevel_(101)  # NSPopUpMenuWindowLevel — nad oknami i fullscreenem
    win.setMovable_(False)
    # CanJoinAllSpaces | Stationary | FullScreenAuxiliary — widać w każdym Space i na pełnym ekranie
    win.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8) | 262144)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(True)
    cv = win.contentView()
    W, H = cv.bounds().size.width, cv.bounds().size.height

    # Liquid Glass tylko na pływającej warstwie funkcyjnej (HIG: materials / liquid-glass)
    if not NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency():
        bg = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        bg.setMaterial_(6)       # Popover — najbliżej systemowych banerów
        bg.setBlendingMode_(0)   # behindWindow — rozmywa pulpit pod spodem
        bg.setState_(1)
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(20)
        bg.layer().setMasksToBounds_(True)
        bg.layer().setBorderWidth_(0.5)
        bg.layer().setBorderColor_(CGColorCreateGenericGray(0.5, 0.25))
        cv.addSubview_(bg)
    else:
        win.setOpaque_(True)
        win.setBackgroundColor_(NSColor.windowBackgroundColor())

    def text_field(rect, string, size, weight, color, align=0):
        f = NSTextField.alloc().initWithFrame_(rect)
        f.setStringValue_(string)
        f.setEditable_(False)
        f.setSelectable_(False)
        f.setBordered_(False)
        f.setDrawsBackground_(False)
        f.setAlignment_(align)
        f.setTextColor_(color)
        f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
        f.cell().setWraps_(True)
        f.cell().setLineBreakMode_(0)  # byWordWrapping
        return f

    tx = PAD + 50 if ICON.exists() else PAD
    tw = BW - tx - PAD
    if ICON.exists():
        iv = NSImageView.alloc().initWithFrame_(NSMakeRect(PAD, H - PAD - 38, 38, 38))
        iv.setImage_(NSImage.alloc().initWithContentsOfFile_(str(ICON)))
        iv.setImageScaling_(3)
        cv.addSubview_(iv)
    cv.addSubview_(text_field(NSMakeRect(tx, H - PAD - 14, tw - (52 if due else 0), 14),
                              "PRZYPOMNIENIE", 11, 0.3, NSColor.secondaryLabelColor()))
    if due:
        cv.addSubview_(text_field(NSMakeRect(BW - PAD - 52, H - PAD - 14, 52, 14),
                                  due[11:16], 11, 0, NSColor.tertiaryLabelColor(), align=2))
    body_bottom = 14 + 30 + 12
    cv.addSubview_(text_field(NSMakeRect(tx, body_bottom, tw, H - PAD - 14 - 6 - body_bottom),
                              text, 14, 0, NSColor.labelColor()))

    def snooze():
        result["value"] = "snooze"

    def done():
        result["value"] = "done"

    delegate = {"value": None}

    def close_window():
        win.setDelegate_(None)
        win.orderOut_(None)
        win.close()

    h = Handler.alloc().initWithSnooze_done_close_(snooze, done, close_window)

    def button(rect, label, key, action, prominent=False):
        # klawisz działa, ale nie pokazujemy go na przycisku
        b = Btn.alloc().initWithFrame_(rect)
        b.setTitle_(label)
        b.setBezelStyle_(1)  # rounded (standard macOS)
        b.setFont_(NSFont.systemFontOfSize_(13))
        b.setTarget_(h)
        b.setAction_(action)
        if prominent:
            b.setBezelColor_(ACCENT)
            b.setContentTintColor_(NSColor.whiteColor())
        b.setKeyEquivalent_(key)
        cv.addSubview_(b)

    bw = (BW - PAD * 2 - 8) / 2
    button(NSMakeRect(PAD, 14, bw, 30), "Odłóż 5 min", "1", "doSnooze:")
    button(NSMakeRect(PAD + bw + 8, 14, bw, 30), "OK", "2", "doOk:", prominent=True)
    button(NSMakeRect(0, 0, 0, 0), "", "\r", "doOk:")   # HIG 5.4 — Return = default
    button(NSMakeRect(0, 0, 0, 0), "", "\x1b", "doOk:")  # HIG 5.3 — Esc = zamknij

    # Regular (nie Accessory) — inaczej klawisze 1/2/Return/Esc nigdzie nie docierają.
    app.setActivationPolicy_(0)
    app.finishLaunching()  # bez tego ręcznie sterowana NSApplication nie aktywuje się
    delegate["value"] = WinDelegate.alloc().initWithDone_snooze_(done, snooze)
    win.setDelegate_(delegate["value"])

    # orderFrontRegardless działa nawet gdy macOS odmówi aktywacji LaunchAgentowi —
    # makeKeyAndOrderFront sam w sobie potrafi zostawić okno niewidoczne.
    win.orderFrontRegardless()
    try:
        app.activateIgnoringOtherApps_(True)  # dopiero potem próbujemy zabrać focus (do klawiszy)
    except Exception:
        pass
    win.makeKeyAndOrderFront_(None)
    try:
        app.runModalForWindow_(win)
    finally:
        close_window()
    return result["value"]


def finish_item(item, outcome):
    with edit_items() as items:
        if item not in items:
            return
        if outcome == "snooze":
            items.append({"text": item["text"],
                          "due": (datetime.now() + timedelta(minutes=SNOOZE_MIN))
                          .isoformat(timespec="seconds")})
        elif outcome == "done":
            log_done(item["text"])
        else:
            raise ValueError(f"Nieznany wynik okna: {outcome}")
        items.remove(item)


def show_reminder(item):
    # AppKit lives only as long as this window; daemon sleep never blocks its UI thread.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "show"],
                            input=json.dumps(item), capture_output=True, text=True, check=True)
    outcome = result.stdout.strip()
    if outcome not in ("done", "snooze"):
        raise ValueError(f"Nieprawidłowy wynik okna: {outcome!r}")
    return outcome


def daemon_loop():
    while True:
        try:
            now = datetime.now()
            due = sorted((i for i in load() if datetime.fromisoformat(i["due"]) <= now),
                         key=lambda i: datetime.fromisoformat(i["due"]))
            if due:
                item = due[0]
                log(f"odpalam: {item['text']}")
                outcome = show_reminder(item)
                finish_item(item, outcome)
                log(f"{outcome}: {item['text']}")
        except Exception as e:
            log(f"Reminder error: {e}")
            time.sleep(60)
            continue
        time.sleep(1)


def daemon():
    with STORE.with_suffix(".daemon.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Daemon przypomnień już działa")
        log("daemon start")
        daemon_loop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="cmd")
    add = commands.add_parser("add", help="Dodaj przypomnienie")
    add.add_argument("text")
    add.add_argument("when", nargs="?", default="60",
                     help="Czas: '13' = za 13 minut, '2h', '14:30', '2026-12-24 18:00'")
    for command in ("list", "log", "daemon", "show"):
        commands.add_parser(command)
    args = parser.parse_args()
    try:
        if args.cmd == "add":
            text = args.text.strip()
            if not text:
                raise ValueError("Treść przypomnienia nie może być pusta")
            item = {"text": text, "due": parse_when(args.when).isoformat(timespec="seconds")}
            with edit_items() as items:
                items.append(item)
            print(f"✔ {text} → {item['due']}")
        elif args.cmd in (None, "list"):
            items = sorted(load(), key=lambda i: datetime.fromisoformat(i["due"]))
            print("\n".join(f"{i['due']}  {i['text']}" for i in items) if items else "(pusto)")
        elif args.cmd == "log":
            print(HISTORY.read_text(encoding="utf-8") if HISTORY.exists() else "(historia pusta)")
        elif args.cmd == "daemon":
            daemon()
        elif args.cmd == "show":
            item = json.load(sys.stdin)
            if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                    or not item["text"].strip() or not isinstance(item.get("due"), str)):
                raise ValueError("Nieprawidłowe przypomnienie")
            datetime.fromisoformat(item["due"])
            threading.Thread(target=play_sound, daemon=True).start()
            print(show_banner(item["text"], item["due"]), flush=True)
    except (ValueError, OverflowError, OSError) as e:
        parser.exit(1, f"Błąd: {e}\n")


if __name__ == "__main__":
    main()
