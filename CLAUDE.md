# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Install dependencies (use the bundled venv)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the app
.\.venv\Scripts\python.exe serial_simulator.py

# Syntax check (no test suite or linter exists)
.\.venv\Scripts\python.exe -c "import ast; ast.parse(open('serial_simulator.py').read())"

# Build a standalone double-clickable exe (output: dist\app.exe). Kill any running
# app.exe first, or PyInstaller can't overwrite the locked file.
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name app --noconfirm serial_simulator.py
```

The app needs a desktop session (Tkinter) and, to actually send, a serial port; it launches
fine without one (the port list is just empty).

## Architecture

Everything lives in `serial_simulator.py` — one `SerialSimulator(tk.Tk)` class plus a
module-level `compute_crc16_modbus()`. Despite the name, this is a generic byte-packet serial
sender; its only Modbus-specific behavior is appending a CRC16 and capturing single-register
(`0x06`) replies.

Concepts that span the code:

- **The packet matrix.** `build_matrix()` rebuilds a grid of `ttk.Entry` widgets: rows =
  packets, columns = bytes. Grid column 0 is the per-row **"On"** tick, column 1 the
  `Packet{r}` label, so byte cell `c` sits at grid column `c+2`. The **last two byte columns
  of every row are reserved, read-only CRC cells** (why `Bytes` has a minimum of 2). Trailing
  columns per row: a "Reg Name" note (`text_widgets`, not sent), a read-only **Response**
  field (`response_widgets`), and a per-row **Send** button. On every rebuild it destroys
  *all* matrix-frame children (so stale headers/labels don't linger) but first snapshots the
  data cells, notes, and tick states and restores them — resizing never wipes user input.

- **Per-row "On" tick.** `enabled_vars` holds one `BooleanVar` per row, and only ticked rows
  are sent by **Send All Checked**; a row's own **Send** button ignores the tick entirely, so
  unticked packets stay available for manual one-off sends. New rows default to ticked (both at
  startup and when `Packets` grows); existing rows keep their state across a resize. These are
  classic `tk.Checkbutton`s, not `ttk` — clam draws an **X** in a ticked ttk box, which reads as
  "excluded", whereas the native indicator gives a proper checkmark. `_row_enabled(row_index)`
  is the accessor (a missing var counts as enabled).

- **Select-all.** The **"On" column header is itself a tick** (`select_all_var`,
  `select_all_chk`) and works both ways: clicking it runs `_toggle_all_rows()` to check or
  uncheck every packet at once, while `_sync_select_all()` — driven by a `write` trace on every
  row var — ticks it only when *all* rows are ticked. The trace means it stays correct however
  a row changed (clicked, loaded from a config, or set in code); `_toggle_all_rows` raises
  `_suspend_sync` so those per-row traces don't flicker the header mid-loop. Also re-synced at
  the end of `build_matrix()` and after `load_config()` restores ticks.

- **CRC auto-update.** Editing a data cell fires `_update_row_crc()` (`<KeyRelease>`/`<FocusOut>`),
  recomputing the Modbus RTU CRC16 over the row's data bytes and writing it low-byte-first into
  the two reserved cells. The repetitive `state(['!readonly'])`/`state(['readonly'])` blocks
  (with plain-`Entry` `config(state=...)` fallbacks) temporarily unlock those cells to write.

- **Reading rows.** `_read_single_packet(row_index)` is the one authoritative parser/validator:
  parses each data cell (decimal, `0x`-prefixed hex, or bare hex with a–f), enforces `0..255`
  (raises `ValueError`), returns `None` for an **empty packet** (all data bytes zero — not sent;
  CRC is excluded from that check since it's non-zero even when zeroed), else returns data+CRC
  bytes. `read_matrix_snapshot()` maps it over the **ticked** rows only and returns
  `(row_index, packet)` tuples — it is the single place the "On" tick is applied.

- **Sending.** Per-row **Send** → `send_single()` (one write, bypasses continuous mode and the
  "On" tick). Bottom **Send All Checked** → `on_send()` snapshots the ticked rows, then runs a
  daemon `_send_worker` thread; matrix edits and tick changes during an active continuous send
  don't affect it (press Send All Checked again to restart with a fresh snapshot). Its
  "Nothing to send" warning distinguishes *no rows ticked* from *ticked rows all empty*. Both
  flush input, write, then read the reply via `_read_response()`.

- **Response reads are adaptive.** The port is opened with `timeout=0.2`. `_read_response()`
  waits for the first byte then drains until ~30 ms idle — it returns as soon as the frame is
  complete rather than blocking on a fixed byte count, so sending is paced by the slave's actual
  response speed. Replies show as hex in the row's Response field.

- **Thread/UI safety.** The worker runs off the Tk main thread, so it marshals UI updates back
  with `self.after(0, ...)` (response fields) and surfaces errors via `_safe_messagebox()`.

- **Save/Load config.** `save_config()`/`load_config()` persist serial settings, matrix size,
  byte data, notes, and the per-row `enabled` ticks as JSON (CRC excluded — recomputed on
  load). Configs predating the tick have no `enabled` key, so every row loads ticked. Dialogs default to
  `CONFIG_DIR` = `<APP_DIR>/ConfigFiles`, auto-created at startup. `APP_DIR` is
  frozen-aware: the folder containing `app.exe` when running as a PyInstaller exe
  (via `sys.executable`, since `__file__`/`sys._MEIPASS` points at a temp extraction
  dir that's deleted on exit), else this script's directory. Keep `app.exe` and its
  `ConfigFiles` folder together so saved configs are always found.

- **Theming.** `_apply_theme()` (called before `_build_ui`) sets the `clam` ttk theme and a
  **mid-grey palette** via module-level `COL_*` constants and named `ttk.Style`s. Greys run
  `COL_BG` (window, darkest) < `COL_CARD` (cards/input fields) with `COL_BORDER` between them,
  and `COL_BTN`/`COL_BTN_HOVER` for neutral buttons. A muted blue (`COL_ACCENT`) is the primary
  accent (banner, Open, Apply Matrix Size, headers), with `COL_ACCENT_SOFT` for light detail on
  it (the banner version label); a desaturated green (`COL_SUCCESS`) marks "go" actions
  (`Success.TButton` for Send All, `Send.TButton` for per-row Send) and `COL_STATUS_BG`/`_FG`
  tint the status bar; red (`COL_DANGER`) is Stop. Other styles: `Header.TLabel`,
  `Packet.TLabel`, `Crc.TEntry`, `Resp.TEntry`, `Status.TLabel`, banner styles. The Response
  field swaps between `Resp.TEntry` (grey-blue, reply received) and `RespErr.TEntry`
  (grey-red + `COL_RESP_ERR_FG`, `(no response)`) in `_set_response()`. Every colour lives in
  the palette except `#ffffff` text on the coloured accent/danger/success fills. Styles are
  defined once here; `build_matrix` only references them by name. The UI is laid out as
  `ttk.LabelFrame` cards (Connection / Matrix & Config / Send) under the header banner. To
  restyle, edit the palette constants or `_apply_theme`, not the per-widget construction.

- **App name / version.** Module-level `APP_NAME` and `APP_VERSION` feed both the window
  title and the header banner, where the version renders as a small muted label
  (`BannerVer.TLabel`) right after the app name. Bump `APP_VERSION` in one place on release.

## Maintenance

Keep this file in sync with the code: whenever you change behavior, structure, defaults, the
theme, or add/rename a feature in `serial_simulator.py`, update the relevant section here in the
same change so future sessions stay accurate.
