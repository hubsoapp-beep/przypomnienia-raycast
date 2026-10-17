# ⏰ Przypomnienia — Raycast + banner w stylu macOS

Wpisz w Raycasta treść i czas, a przypomnienie wyskoczy jako banner w prawym górnym rogu ekranu — z dźwiękiem, przyciskiem **OK** i **Odłóż 5 min**.

Zero zależności zewnętrznych: czysty Python 3 (systemowy) + PyObjC, które macOS już ma. Żadnego Docka, żadnej bazy, żadnego konta.

```
┌──────────────────────────────────────┐
│ [ikona]  PRZYPOMNIENIE           08:00│
│         Odbierz paczkę               │
│         [ Odłóż 5 min ]     [   OK  ]│
└──────────────────────────────────────┘
```

## Jak działa

| Element | Rola |
|---|---|
| `przypomnienie.sh` | Raycast Script Command — 2 argumenty: treść + czas |
| `reminders.py add` | dopisuje do `~/.reminders.json` (lock `flock`, zapis atomowy) |
| `reminders.py daemon` | pętla 1 s, wykrywa termin i odpala banner |
| `reminders.py show` | proces pomocniczy: okno AppKit modalnie (blokuje tylko siebie, nie daemona) |

- Stan: `~/.reminders.json`
- Historia zrobionych: `~/.reminders-history.md`
- Log: `/tmp/przypomnienia.log`

## Instalacja

```bash
git clone https://github.com/hubsoapp-beep/przypomnienia-raycast.git
cd przypomnienia-raycast
./install.sh
```

`install.sh` kopiuje pliki do `~/bin/przypomnienia`, generuje LaunchAgent i restartuje daemona.

**Ostatni krok ręcznie** — w Raycast:

1. Ustawienia → Extensions → Create Quicklink / Script Commands
2. Name: `Przypomnienie`
3. Script: `~/bin/przypomnienia/przypomnienie.sh`
4. Interpreter: `/bin/bash`

Nadaj sobie skrót klawiszowy (w Quicklinku → ⌘K → „Add Keyboard Shortcut").

## Użycie

W Raycast: **Przypomnienie** → wpisz treść → podaj czas:

| Wpis | Znaczenie |
|---|---|
| `+30m` / `+2h` | za 30 minut / 2 godziny |
| `14:30` | dzisiaj o 14:30 (już minęło → jutro) |
| `2026-12-24 18:00` | konkretna data |
| *(puste)* | domyślnie `+60m` |

Z wiersza poleceń:

```bash
~/bin/przypomnienia/reminders.py list              # coś wisi
~/bin/przypomnienia/reminders.py add "Wstań" +45m
~/bin/przypomnienia/reminders.py log               # historia
tail -f /tmp/przypomnienia.log                     # log na żywo
```

W oknie: **1** = odłóż, **2** / **Return** = OK, **Esc** = zamknij (traktuje jak OK).

## Odinstalowanie

```bash
./uninstall.sh
```

Zatrzymuje daemon i usuwa pliki. Dane (`~/.reminders.json`, `~/.reminders-history.md`) zostają — usuń ręcznie, jeśli chcesz. Quicklink usuń w Raycast: Settings → Extensions → Przypomnienia.

## Testy

```bash
python3 -m unittest -v test_reminders
REMINDERS_GUI_TESTS=1 python3 -m unittest -v test_reminders.RemindersTests.test_gui_repeated_dismissals
```

Testy GUI klikają w prawdziwe okno AppKit (symulowane zdarzenia myszy) — włącz tylko na własnym pulpicie.

## Wymagania

macOS z systemowym `python3` (`/usr/bin/python3`) i PyObjC (`AppKit`, `Quartz`, `Foundation`). Sprawdź:

```bash
/usr/bin/python3 -c "import AppKit, Quartz; print('ok')"
```

## Licencja

MIT — [LICENSE](LICENSE). Dźwięk (`bark.wav`) i ikona (`icon.png`) są dorobione na potrzeby tego projektu, możesz podmienić.