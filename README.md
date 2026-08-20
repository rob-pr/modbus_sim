# Modbus Simulator

A Python/Tkinter desktop app for hand-crafting byte packets and sending them over a serial
port. Each packet is a row of bytes you type in a grid; the app appends a Modbus RTU CRC16
automatically and shows the slave's reply next to the packet that produced it.

Despite the name it is a **generic serial packet sender** — the only Modbus-specific behaviour
is the CRC16 and the way replies are captured.

![Modbus Simulator](screenshot.png)

## Features

- Pick a serial port from a dropdown, refresh the list, open/close it
- Configure baud (9600–115200), parity, stop bits
- **Packet matrix**: columns = bytes per packet, rows = packets, both resizable
- **CRC16 is automatic** — the last two byte columns of every row are read-only and recomputed
  as you type, low byte first
- **Per-packet "On" tick** — `Send All Checked` sends only the ticked packets; the header tick
  checks/unchecks all of them at once
- **Per-row Send button** — always sends that one packet, ticked or not
- **Response column** — the slave's reply as hex, per packet (blue on success, red when nothing
  came back)
- **Reg Name column** — a free-text note per row for your own reference; never transmitted
- Send once, or **Continuous** to loop with a configurable delay between passes
- Save/Load the whole setup (serial settings, matrix, notes, ticks) as JSON

## Requirements

- Python 3.8+
- [pyserial](https://pypi.org/project/pyserial/)
- A desktop session — this is a Tkinter GUI. It starts fine with no serial port attached
  (the port list is simply empty), you just can't send.

```
pip install -r requirements.txt
```

## Run

```
python serial_simulator.py
```

## Usage

### Entering bytes

Cells accept decimal (`10`), prefixed hex (`0x0A`), or bare hex (`0A`). Values must be `0..255`;
anything outside that range is reported as an error instead of being sent.

The **last two columns of every row are the CRC** — read-only, recalculated over that row's data
bytes on every keystroke. This is why `Bytes` has a minimum of 2.

A packet whose data bytes are **all zero** is treated as empty and skipped, so you can size the
matrix generously and only fill in the rows you need. (The CRC columns are excluded from that
check, since a CRC over zeros isn't itself zero.)

### Choosing which packets to send

Every packet row has a checkbox in the **"On"** column on the left. The rule is simple:

> **`Send All Checked` sends the ticked packets and skips the unticked ones.**

Nothing is lost by unticking a packet — it stays in the matrix with its bytes intact, and you
can still fire it by hand any time with its own `Send` button.

| Control | What it does |
|---|---|
| Row checkbox | Include (ticked) or skip (unticked) that packet in `Send All Checked` |
| **"On"** checkbox in the header | Ticks or unticks **every** packet at once |
| Row's **`Send`** button | Sends that one packet immediately, **ignoring** its checkbox |
| **`Send All Checked`** | Sends every ticked packet, once — or repeatedly if **Continuous** is on |

New packets are ticked automatically, so with a fresh matrix `Send All Checked` sends everything.

#### Example: loop just one packet out of a full matrix

You have 20 packets set up, but you want to send only packet 7 over and over:

1. Clear every tick with the **"On"** checkbox in the header. (It mirrors the rows, so when
   they're all ticked one click empties them; otherwise click once to tick all, again to clear.)
2. Tick the checkbox on **Packet7** only.
3. Turn on **Continuous** and click **`Send All Checked`**.

Packet7 now repeats on its own. The other 19 packets aren't sending, but they're still there —
click any row's `Send` button to send that one manually whenever you need it, even while the loop
is running.

To bring a packet back into the loop, just tick it: it joins on the next pass, no restart needed.
Untick one and it drops out the same way.

Your ticks are saved with `Save Config`, so a setup comes back exactly as you left it.

### Timing

Within one pass, packets are spaced **100 ms** apart. In **Continuous** mode, the *Group delay*
(default 3000 ms) is applied after the whole group before the next pass begins.

Replies are read adaptively rather than by waiting for a fixed byte count: the app waits for the
first byte, then drains until the line has been idle ~30 ms. Sending is therefore paced by how
fast the slave actually answers.

**Continuous sends stay live.** Before each pass the matrix is re-read, so editing a byte cell
mid-run means the next pass sends the new value — no need to stop and restart. Tick changes are
picked up the same way, so you can untick a row and it drops out of the loop (untick everything
and the loop simply idles until you tick something again). While a cell is momentarily invalid —
mid-keystroke, or blank while you retype it — the loop keeps sending the last valid value rather
than erroring. `Stop` ends the run.

The *Group delay* is read once when you press `Send All Checked`; changing it mid-run needs a
restart to take effect.

### Save/Load config

`Save Config` / `Load Config` store serial settings, matrix size, byte values, notes, and the
per-row ticks as JSON. CRCs are not saved — they are recomputed on load. Dialogs default to a
`ConfigFiles` folder next to the app. Configs saved before the "On" tick existed load with every
row ticked.

## Building a standalone .exe

```
python -m PyInstaller --onefile --windowed --name app --noconfirm serial_simulator.py
```

The result is `dist\app.exe`, double-clickable with no Python install required.

**Keep `app.exe` and its `ConfigFiles` folder together** — the app resolves that folder relative
to the executable, so saved configs follow the exe rather than getting lost in PyInstaller's temp
extraction directory.

If a previous `app.exe` is still running, close it first — PyInstaller can't overwrite a locked
file.

## Layout

Everything lives in `serial_simulator.py`: one `SerialSimulator(tk.Tk)` class plus a module-level
`compute_crc16_modbus()`. `CLAUDE.md` documents the internals — the matrix rebuild, CRC
auto-update, thread/UI marshalling, and the theme palette.
