# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Install dependencies (use the bundled venv)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the app
.\.venv\Scripts\python.exe serial_simulator.py

# Syntax check (no test suite, linter, or build step exists)
.\.venv\Scripts\python.exe -c "import ast; ast.parse(open('serial_simulator.py').read())"
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
  packets, columns = bytes. The **last two columns of every row are reserved, read-only CRC
  cells** (why `Bytes` has a minimum of 2). Trailing columns per row: a "Reg Name" note
  (`text_widgets`, not sent), a read-only **Response** field (`response_widgets`), and a
  per-row **Send** button. On every rebuild it destroys *all* matrix-frame children (so stale
  headers/labels don't linger) but first snapshots the data cells and notes and restores them —
  resizing never wipes user input.

- **CRC auto-update.** Editing a data cell fires `_update_row_crc()` (`<KeyRelease>`/`<FocusOut>`),
  recomputing the Modbus RTU CRC16 over the row's data bytes and writing it low-byte-first into
  the two reserved cells. The repetitive `state(['!readonly'])`/`state(['readonly'])` blocks
  (with plain-`Entry` `config(state=...)` fallbacks) temporarily unlock those cells to write.

- **Reading rows.** `_read_single_packet(row_index)` is the one authoritative parser/validator:
  parses each data cell (decimal, `0x`-prefixed hex, or bare hex with a–f), enforces `0..255`
  (raises `ValueError`), returns `None` for an **empty packet** (all data bytes zero — not sent;
  CRC is excluded from that check since it's non-zero even when zeroed), else returns data+CRC
  bytes. `read_matrix_snapshot()` maps it over all rows and returns `(row_index, packet)` tuples.

- **Sending.** Per-row **Send** → `send_single()` (one write, bypasses continuous mode).
  Bottom **Send All** → `on_send()` snapshots, then runs a daemon `_send_worker` thread; matrix
  edits during an active continuous send don't affect it (press Send All again to restart with a
  fresh snapshot). Both flush input, write, then read the reply via `_read_response()`.

- **Response reads are adaptive.** The port is opened with `timeout=0.2`. `_read_response()`
  waits for the first byte then drains until ~30 ms idle — it returns as soon as the frame is
  complete rather than blocking on a fixed byte count, so sending is paced by the slave's actual
  response speed. Replies show as hex in the row's Response field.

- **Thread/UI safety.** The worker runs off the Tk main thread, so it marshals UI updates back
  with `self.after(0, ...)` (response fields) and surfaces errors via `_safe_messagebox()`.

- **Save/Load config.** `save_config()`/`load_config()` persist serial settings, matrix size,
  byte data, and notes as JSON (CRC excluded — recomputed on load). Dialogs default to
  `CONFIG_DIR` = `<script dir>/ConfigFiles`, which is auto-created at startup.
