#!/usr/bin/env python3
"""
serial_simulator.py

A simple Tkinter GUI to send byte-packets over a serial port.

Features:
- Dropdown listing available serial ports and refresh button
- Open/Close selected port
- Configure baudrate, parity, stopbits, bytesize
- Configurable matrix: columns = bytes per packet, rows = number of packets
- Per-packet "On" checkbox (checked by default): Send All Checked sends only ticked packets,
  while a row's own Send button always sends that row regardless
- Send button: snapshots matrix and sends packets once or continuously
- Continuous send with configurable interval between packets (ms)
- Continuous sending re-reads the matrix before every pass, so edits to the byte cells (and to
  the "On" ticks) take effect on the next pass without restarting the send

Depends on: pyserial

Run: python serial_simulator.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont
import threading
import time
import json
import os
import sys


APP_NAME = "Modbus Simulator"
APP_VERSION = "v1.0.2"


# Base directory for the app: the folder containing app.exe when frozen by
# PyInstaller (sys._MEIPASS is a temp extraction dir, so we use sys.executable),
# otherwise the directory of this script.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# default directory for save/load dialogs: <app dir>/ConfigFiles
CONFIG_DIR = os.path.join(APP_DIR, "ConfigFiles")

# ---- mid-grey theme palette (muted blue accent) ----
COL_BG = "#c9ccd1"        # window background
COL_CARD = "#dfe2e6"      # card / panel background
COL_TEXT = "#17202b"      # primary text
COL_MUTED = "#5b6169"     # secondary text
COL_BORDER = "#a9aeb5"    # borders
COL_ACCENT = "#2b5299"    # primary accent (muted blue)
COL_ACCENT_HOVER = "#1f3f78"
COL_ACCENT_SOFT = "#c3cfe0"  # light text/detail on an accent background
COL_DANGER = "#b52222"
COL_DANGER_HOVER = "#8f1b1b"
COL_SUCCESS = "#2f7d4f"   # green (send actions)
COL_SUCCESS_HOVER = "#256640"
COL_BTN = "#cbcfd4"       # neutral button fill
COL_BTN_HOVER = "#b6bbc2"
COL_DISABLED = "#b9bec5"  # text on a disabled coloured button
COL_CRC = "#c4c8cd"       # CRC cell field (greyed)
COL_RESP = "#ccd6e6"      # response cell field (grey-blue)
COL_RESP_ERR = "#e2c4c4"  # response cell field when no reply (grey-red)
COL_RESP_ERR_FG = "#7f1d1d"
COL_STATUS_BG = "#c6d3c6"  # status bar (grey-green)
COL_STATUS_FG = "#2c4a33"

try:
    import serial
    import serial.tools.list_ports
except Exception as e:
    print("Missing required package 'pyserial'. Install with: pip install pyserial")
    raise


def compute_crc16_modbus(data: bytes) -> int:
    """Compute Modbus RTU CRC16 for given data. Returns 16-bit int (CRC).

    CRC is returned as a 16-bit integer where low byte is sent first.
    """
    crc = 0xFFFF
    for a in data:
        crc ^= a
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class SerialSimulator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("820x600")
        self.minsize(720, 520)

        self._apply_theme()

        # ensure the config folder exists for save/load dialogs
        os.makedirs(CONFIG_DIR, exist_ok=True)

        self.serial_port = None
        self.sender_thread = None
        self.stop_event = threading.Event()
        self.entry_widgets = []     # list of lists for matrix
        self.text_widgets = []      # list for custom text entries (Reg Name notes)
        self.response_widgets = []  # list of read-only entries showing each packet's response
        self.enabled_vars = []      # list of BooleanVar: is this packet included in Send All Checked
        self.select_all_var = tk.BooleanVar(value=True)  # header tick: toggles every row at once
        self._suspend_sync = False  # guard while _toggle_all_rows rewrites every row var

        self._build_ui()

    def _apply_theme(self):
        """Apply a mid-grey theme (muted blue accent) on the clam base theme."""
        self.configure(bg=COL_BG)

        # base + heading fonts (Segoe UI is the Windows 11 system font)
        self.base_font = tkfont.Font(family="Segoe UI", size=10)
        self.bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.title_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        self.version_font = tkfont.Font(family="Segoe UI", size=9)
        self.option_add("*Font", self.base_font)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # generic widgets
        style.configure(".", background=COL_BG, foreground=COL_TEXT, font=self.base_font)
        style.configure("TFrame", background=COL_BG)
        style.configure("Card.TFrame", background=COL_CARD)
        style.configure("TLabel", background=COL_BG, foreground=COL_TEXT)
        style.configure("Card.TLabel", background=COL_CARD, foreground=COL_TEXT)
        style.configure("TCheckbutton", background=COL_CARD, foreground=COL_TEXT)
        style.map("TCheckbutton",
                  background=[("active", COL_CARD)],
                  indicatorcolor=[("selected", COL_ACCENT)])

        # cards (LabelFrame)
        style.configure("Card.TLabelframe", background=COL_CARD,
                        bordercolor=COL_BORDER, relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=COL_CARD,
                        foreground=COL_ACCENT, font=self.bold_font)

        # inputs
        for ent in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(ent, fieldbackground=COL_CARD, background=COL_CARD,
                            foreground=COL_TEXT, bordercolor=COL_BORDER,
                            arrowcolor=COL_TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", COL_CARD)],
                  foreground=[("readonly", COL_TEXT)])
        # combobox dropdown list colors
        self.option_add("*TCombobox*Listbox.background", COL_CARD)
        self.option_add("*TCombobox*Listbox.foreground", COL_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", COL_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        # read-only matrix cell variants
        style.configure("Crc.TEntry", fieldbackground=COL_CRC, foreground=COL_MUTED)
        style.map("Crc.TEntry", fieldbackground=[("readonly", COL_CRC)],
                  foreground=[("readonly", COL_MUTED)])
        style.configure("Resp.TEntry", fieldbackground=COL_RESP, foreground=COL_TEXT)
        style.map("Resp.TEntry", fieldbackground=[("readonly", COL_RESP)],
                  foreground=[("readonly", COL_TEXT)])
        style.configure("RespErr.TEntry", fieldbackground=COL_RESP_ERR, foreground=COL_RESP_ERR_FG)
        style.map("RespErr.TEntry", fieldbackground=[("readonly", COL_RESP_ERR)],
                  foreground=[("readonly", COL_RESP_ERR_FG)])

        # buttons
        style.configure("TButton", background=COL_BTN, foreground=COL_TEXT,
                        bordercolor=COL_BORDER, focuscolor=COL_BG,
                        padding=(10, 5), relief="flat")
        style.map("TButton", background=[("active", COL_BTN_HOVER)])

        style.configure("Accent.TButton", background=COL_ACCENT, foreground="#ffffff",
                        bordercolor=COL_ACCENT, padding=(12, 5), relief="flat")
        style.map("Accent.TButton",
                  background=[("pressed", COL_ACCENT_HOVER), ("active", COL_ACCENT_HOVER)],
                  foreground=[("disabled", COL_DISABLED)])

        style.configure("Danger.TButton", background=COL_DANGER, foreground="#ffffff",
                        bordercolor=COL_DANGER, padding=(12, 5), relief="flat")
        style.map("Danger.TButton",
                  background=[("pressed", COL_DANGER_HOVER), ("active", COL_DANGER_HOVER)])

        # green "go" buttons: Send All Checked and per-row Send
        style.configure("Success.TButton", background=COL_SUCCESS, foreground="#ffffff",
                        bordercolor=COL_SUCCESS, padding=(12, 5), relief="flat")
        style.map("Success.TButton",
                  background=[("pressed", COL_SUCCESS_HOVER), ("active", COL_SUCCESS_HOVER)],
                  foreground=[("disabled", COL_DISABLED)])

        style.configure("Send.TButton", background=COL_SUCCESS, foreground="#ffffff",
                        bordercolor=COL_SUCCESS, padding=(6, 2), relief="flat")
        style.map("Send.TButton",
                  background=[("pressed", COL_SUCCESS_HOVER), ("active", COL_SUCCESS_HOVER)])

        # matrix labels
        style.configure("Header.TLabel", background=COL_CARD, foreground=COL_ACCENT,
                        font=self.bold_font)
        style.configure("Packet.TLabel", background=COL_CARD, foreground=COL_MUTED,
                        font=self.bold_font)

        # banner + status bar
        style.configure("Banner.TFrame", background=COL_ACCENT)
        style.configure("Banner.TLabel", background=COL_ACCENT, foreground="#ffffff",
                        font=self.title_font)
        style.configure("BannerVer.TLabel", background=COL_ACCENT, foreground=COL_ACCENT_SOFT,
                        font=self.version_font)
        style.configure("Status.TLabel", background=COL_STATUS_BG, foreground=COL_STATUS_FG,
                        padding=(8, 4))

        # scrollbar
        style.configure("TScrollbar", background=COL_BG, troughcolor=COL_BG,
                        bordercolor=COL_BG, arrowcolor=COL_TEXT)

    def _build_ui(self):
        # header banner
        banner = ttk.Frame(self, style="Banner.TFrame")
        banner.pack(fill=tk.X)
        ttk.Label(banner, text=APP_NAME,
                  style="Banner.TLabel").pack(side=tk.LEFT, padx=(12, 6), pady=8)
        ttk.Label(banner, text=APP_VERSION,
                  style="BannerVer.TLabel").pack(side=tk.LEFT, padx=(0, 12), pady=(14, 8))

        # Connection card: port selection and serial config
        top = ttk.LabelFrame(self, text="Connection", style="Card.TLabelframe", padding=10)
        top.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(top, text="Port:", style="Card.TLabel").grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=25, state='readonly')
        self.port_combo.grid(row=0, column=1, sticky=tk.W, padx=4, pady=3)

        self.refresh_btn = ttk.Button(top, text="Refresh", command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=2, padx=6, pady=3)

        self.open_btn = ttk.Button(top, text="Open", style="Accent.TButton", command=self.toggle_open)
        self.open_btn.grid(row=0, column=3, padx=6, pady=3)

        ttk.Label(top, text="Baud:", style="Card.TLabel").grid(row=1, column=0, sticky=tk.W, padx=4, pady=3)
        self.baud_var = tk.StringVar(value="9600")
        self.baud_combo = ttk.Combobox(top, textvariable=self.baud_var, values=["9600","19200","38400","57600","115200"], width=10, state='readonly')
        self.baud_combo.grid(row=1, column=1, sticky=tk.W, padx=4, pady=3)

        ttk.Label(top, text="Parity:", style="Card.TLabel").grid(row=1, column=2, sticky=tk.W, padx=4, pady=3)
        self.parity_var = tk.StringVar(value='N')
        self.parity_combo = ttk.Combobox(top, textvariable=self.parity_var, values=['N','E','O','M','S'], width=6, state='readonly')
        self.parity_combo.grid(row=1, column=3, sticky=tk.W, padx=4, pady=3)

        ttk.Label(top, text="Stop bits:", style="Card.TLabel").grid(row=2, column=2, sticky=tk.W, padx=4, pady=3)
        self.stop_var = tk.StringVar(value='1')
        self.stop_combo = ttk.Combobox(top, textvariable=self.stop_var, values=['1','1.5','2'], width=6, state='readonly')
        self.stop_combo.grid(row=2, column=3, sticky=tk.W, padx=4, pady=3)

        # Matrix & Config card: matrix size + save/load
        cfg = ttk.LabelFrame(self, text="Matrix & Config", style="Card.TLabelframe", padding=10)
        cfg.pack(fill=tk.X, padx=10, pady=4)

        ttk.Label(cfg, text="Bytes:", style="Card.TLabel").grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        self.cols_var = tk.IntVar(value=8)
        # enforce at least 2 bytes so last two can be CRC
        self.cols_spin = ttk.Spinbox(cfg, from_=2, to=64, textvariable=self.cols_var, width=6)
        self.cols_spin.grid(row=0, column=1, sticky=tk.W, padx=4, pady=3)

        ttk.Label(cfg, text="Packets:", style="Card.TLabel").grid(row=1, column=0, sticky=tk.W, padx=4, pady=3)
        self.rows_var = tk.IntVar(value=1)
        self.rows_spin = ttk.Spinbox(cfg, from_=1, to=256, textvariable=self.rows_var, width=6)
        self.rows_spin.grid(row=1, column=1, sticky=tk.W, padx=4, pady=3)

        self.apply_matrix_btn = ttk.Button(cfg, text="Apply Matrix Size", style="Accent.TButton", command=self.build_matrix)
        self.apply_matrix_btn.grid(row=0, column=2, rowspan=2, sticky=tk.W, padx=12, pady=3)

        self.save_btn = ttk.Button(cfg, text="Save Config", command=self.save_config)
        self.save_btn.grid(row=0, column=3, sticky=tk.W, padx=6, pady=3)

        self.load_btn = ttk.Button(cfg, text="Load Config", command=self.load_config)
        self.load_btn.grid(row=1, column=3, sticky=tk.W, padx=6, pady=3)

        # Middle frame: matrix canvas
        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self.canvas = tk.Canvas(mid, bg=COL_CARD, highlightthickness=1,
                                highlightbackground=COL_BORDER)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=vsb.set)

        self.matrix_frame = ttk.Frame(self.canvas, style="Card.TFrame")
        self.canvas.create_window((0,0), window=self.matrix_frame, anchor='nw')
        self.matrix_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))

        # Send card: send controls
        bot = ttk.LabelFrame(self, text="Send", style="Card.TLabelframe", padding=10)
        bot.pack(fill=tk.X, padx=10, pady=4)

        # interval_var now represents group delay (ms) after whole group of packets is sent
        # inter-packet delay within a group is fixed at 100 ms (see _send_worker)
        self.interval_var = tk.IntVar(value=3000)  # ms (group delay)
        ttk.Label(bot, text="Group delay (ms) after all packets sent:", style="Card.TLabel").grid(row=0, column=0, sticky=tk.W, padx=4, pady=3)
        self.interval_entry = ttk.Entry(bot, textvariable=self.interval_var, width=8)
        self.interval_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=3)

        self.continuous_var = tk.BooleanVar(value=False)
        self.continuous_check = ttk.Checkbutton(bot, text="Continuous", variable=self.continuous_var)
        self.continuous_check.grid(row=0, column=2, padx=12, pady=3)

        self.send_btn = ttk.Button(bot, text="Send All Checked", style="Success.TButton",
                                   command=self.on_send)
        self.send_btn.grid(row=0, column=3, padx=8, pady=3)

        self.stop_btn = ttk.Button(bot, text="Stop", style="Danger.TButton", command=self.stop_sending)
        self.stop_btn.grid(row=0, column=4, padx=8, pady=3)

        self.status_label = ttk.Label(self, text="Status: idle", style="Status.TLabel", anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        # matrix storage
        self.entry_widgets = []  # list of lists
        self.build_matrix()
        self.refresh_ports()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports
        if ports:
            self.port_combo.current(0)

    def toggle_open(self):
        if self.serial_port and self.serial_port.is_open:
            self._close_port()
        else:
            self._open_port()

    def _open_port(self):
        port = self.port_var.get()
        if not port:
            messagebox.showerror("Port error", "Please select a serial port first")
            return
        try:
            baud = int(self.baud_var.get())
            parity = self.parity_var.get()
            stopbits = float(self.stop_var.get())

            parity_map = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD, 'M': serial.PARITY_MARK, 'S': serial.PARITY_SPACE}
            stop_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}

            self.serial_port = serial.Serial(port=port, baudrate=baud, parity=parity_map.get(parity, serial.PARITY_NONE), stopbits=stop_map.get(stopbits, serial.STOPBITS_ONE), timeout=0.2)
            self.open_btn.config(text='Close')
            self.status_label.config(text=f"Status: Open {port} @ {baud}")
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            self.serial_port = None

    def _close_port(self):
        try:
            if self.serial_port:
                self.serial_port.close()
            self.open_btn.config(text='Open')
            self.status_label.config(text="Status: closed")
            self.serial_port = None
        except Exception as e:
            messagebox.showerror("Close failed", str(e))

    def build_matrix(self):
        # snapshot existing user-entered data so a resize doesn't wipe it.
        # only the data cells are preserved (last two columns are CRC and are recomputed).
        old_data = []  # list of rows, each a list of raw strings for data cells
        for widget_row in self.entry_widgets:
            ncols = len(widget_row)
            old_data.append([widget_row[c].get() for c in range(max(0, ncols - 2))])
        old_notes = [w.get() for w in self.text_widgets]
        old_enabled = [v.get() for v in self.enabled_vars]

        # clear existing — destroy ALL children (headers, packet labels, cells, notes)
        # so stale labels don't linger when the matrix shrinks or overlap when it grows.
        for child in self.matrix_frame.winfo_children():
            child.destroy()
        self.entry_widgets.clear()
        self.text_widgets.clear()
        self.response_widgets.clear()
        self.enabled_vars.clear()

        # ensure at least two bytes per packet (last two reserved for CRC)
        cols = max(2, int(self.cols_var.get()))
        rows = max(1, int(self.rows_var.get()))

        # header. column 0 is the per-row enable tick, so byte/name/response
        # columns all sit one to the right of their old positions.
        # the "On" header doubles as the select-all tick: it checks/unchecks every
        # row, and _sync_select_all keeps it in step when rows are toggled individually.
        self.select_all_chk = tk.Checkbutton(
            self.matrix_frame, text="On", variable=self.select_all_var,
            command=self._toggle_all_rows, bg=COL_CARD, activebackground=COL_CARD,
            selectcolor=COL_CARD, fg=COL_ACCENT, activeforeground=COL_ACCENT,
            font=self.bold_font, highlightthickness=0, bd=0, padx=0, pady=0,
            takefocus=0)
        self.select_all_chk.grid(row=0, column=0, padx=(6, 2), pady=4)
        for c in range(cols):
            lbl = ttk.Label(self.matrix_frame, text=f"Byte{c}", style="Header.TLabel")
            lbl.grid(row=0, column=c+2, padx=2, pady=4)
        # header for custom text column (notes only, not sent)
        lbl = ttk.Label(self.matrix_frame, text="Reg Name", style="Header.TLabel")
        lbl.grid(row=0, column=cols+2, padx=2, pady=4)
        # header for the response column
        lbl = ttk.Label(self.matrix_frame, text="Response", style="Header.TLabel")
        lbl.grid(row=0, column=cols+3, padx=2, pady=4)
        # header for the per-row send button column
        lbl = ttk.Label(self.matrix_frame, text="", style="Header.TLabel")
        lbl.grid(row=0, column=cols+4, padx=2, pady=4)

        for r in range(rows):
            # per-row enable tick: new rows start checked, existing rows keep
            # their state across a resize. Only ticked rows go out on Send All Checked;
            # the row's own Send button ignores this entirely.
            enabled_var = tk.BooleanVar(value=old_enabled[r] if r < len(old_enabled) else True)
            # classic tk.Checkbutton, not ttk: the clam theme draws an X in a ticked
            # ttk box, which reads as "excluded" — the native indicator gives a checkmark.
            enabled_var.trace_add('write', lambda *_: self._sync_select_all())
            chk = tk.Checkbutton(self.matrix_frame, variable=enabled_var,
                                 bg=COL_CARD, activebackground=COL_CARD,
                                 selectcolor=COL_CARD, highlightthickness=0,
                                 bd=0, padx=0, pady=0, takefocus=0)
            chk.grid(row=r+1, column=0, padx=(6, 2), pady=1)
            self.enabled_vars.append(enabled_var)
            lbl = ttk.Label(self.matrix_frame, text=f"Packet{r}", style="Packet.TLabel")
            lbl.grid(row=r+1, column=1, padx=6, pady=2)
            row_widgets = []
            for c in range(cols):
                e = ttk.Entry(self.matrix_frame, width=6, justify=tk.CENTER)
                e.grid(row=r+1, column=c+2, padx=2, pady=1)
                # default with zeros
                if c >= cols - 2:
                    # last two columns are CRC bytes: readonly and auto-updated
                    e.configure(style="Crc.TEntry")
                    e.insert(0, "00")
                    try:
                        e.state(['readonly'])
                    except Exception:
                        # fallback for plain Entry
                        e.config(state='readonly')
                else:
                    # restore previous value for this cell if it existed, else default
                    if r < len(old_data) and c < len(old_data[r]):
                        e.insert(0, old_data[r][c])
                    else:
                        e.insert(0, "00")
                    # update CRC when edited: update on key release and focus out
                    e.bind('<KeyRelease>', lambda ev, rr=r: self._update_row_crc(rr))
                    e.bind('<FocusOut>', lambda ev, rr=r: self._update_row_crc(rr))
                row_widgets.append(e)
            self.entry_widgets.append(row_widgets)
            # add note field for this row (display only, not sent)
            note_entry = ttk.Entry(self.matrix_frame, width=15)
            note_entry.grid(row=r+1, column=cols+2, padx=2, pady=1)
            note_entry.insert(0, old_notes[r] if r < len(old_notes) else "")
            self.text_widgets.append(note_entry)
            # response field for this row (read-only, filled after a send)
            resp_entry = ttk.Entry(self.matrix_frame, width=24, style="Resp.TEntry")
            resp_entry.grid(row=r+1, column=cols+3, padx=2, pady=1)
            try:
                resp_entry.state(['readonly'])
            except Exception:
                resp_entry.config(state='readonly')
            self.response_widgets.append(resp_entry)
            # per-row send button: sends only this packet
            row_send_btn = ttk.Button(self.matrix_frame, text="Send", width=6,
                                      style="Send.TButton",
                                      command=lambda rr=r: self.send_single(rr))
            row_send_btn.grid(row=r+1, column=cols+4, padx=4, pady=1)

        # compute CRCs for all rows initially
        self._update_all_crcs()
        self._sync_select_all()

    def _collect_data_cells(self):
        """Return matrix data cells (raw strings, CRC columns excluded) and notes."""
        data = []
        for row in self.entry_widgets:
            ncols = len(row)
            data.append([row[c].get() for c in range(max(0, ncols - 2))])
        notes = [w.get() for w in self.text_widgets]
        return data, notes

    def save_config(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON config', '*.json'), ('All files', '*.*')],
            title='Save config',
            initialdir=CONFIG_DIR,
        )
        if not path:
            return
        data, notes = self._collect_data_cells()
        config = {
            'port': self.port_var.get(),
            'baud': self.baud_var.get(),
            'parity': self.parity_var.get(),
            'stopbits': self.stop_var.get(),
            'cols': int(self.cols_var.get()),
            'rows': int(self.rows_var.get()),
            'interval': int(self.interval_var.get()),
            'continuous': bool(self.continuous_var.get()),
            'data': data,    # CRC columns excluded; recomputed on load
            'notes': notes,
            'enabled': [bool(v.get()) for v in self.enabled_vars],
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            self.status_label.config(text=f"Status: saved config to {path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def load_config(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON config', '*.json'), ('All files', '*.*')],
            title='Load config',
            initialdir=CONFIG_DIR,
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        data = config.get('data', [])
        notes = config.get('notes', [])
        # apply serial settings (fall back to current values if missing)
        self.port_var.set(config.get('port', self.port_var.get()))
        self.baud_var.set(str(config.get('baud', self.baud_var.get())))
        self.parity_var.set(config.get('parity', self.parity_var.get()))
        self.stop_var.set(str(config.get('stopbits', self.stop_var.get())))
        self.interval_var.set(int(config.get('interval', self.interval_var.get())))
        self.continuous_var.set(bool(config.get('continuous', self.continuous_var.get())))

        # derive matrix size from saved data when not explicitly stored
        rows = int(config.get('rows', len(data) or 1))
        cols = int(config.get('cols', (len(data[0]) + 2) if data else 8))
        self.cols_var.set(cols)
        self.rows_var.set(rows)
        self.build_matrix()

        # populate data cells and notes from the loaded config
        for r, row in enumerate(self.entry_widgets):
            if r >= len(data):
                break
            ncols = len(row)
            for c in range(max(0, ncols - 2)):
                if c < len(data[r]):
                    row[c].delete(0, tk.END)
                    row[c].insert(0, data[r][c])
        for i, w in enumerate(self.text_widgets):
            if i < len(notes):
                w.delete(0, tk.END)
                w.insert(0, notes[i])
        # restore the per-row "On" ticks; configs saved before this existed have no
        # 'enabled' key, so those rows default to checked.
        enabled = config.get('enabled')
        for i, v in enumerate(self.enabled_vars):
            v.set(bool(enabled[i]) if enabled is not None and i < len(enabled) else True)
        self._sync_select_all()

        self._update_all_crcs()
        self.status_label.config(text=f"Status: loaded config from {path}")

    def _read_single_packet(self, row_index: int):
        """Read one matrix row into a packet (data bytes + CRC).

        Returns the packet as bytes, or None if all data bytes are zero (empty
        packets are not sent). Raises ValueError on invalid/out-of-range input.
        """
        row = self.entry_widgets[row_index]
        packet = bytearray()
        ncols = len(row)
        # read all but last two CRC columns, validate
        for c in range(ncols - 2):
            txt = row[c].get().strip()
            if txt.startswith('0x') or txt.startswith('0X'):
                try:
                    val = int(txt, 16)
                except ValueError:
                    raise ValueError(f"Invalid hex at row {row_index} col {c}: {txt}")
            else:
                # allow decimal or hex without prefix if contains letters
                if any(ch in txt.lower() for ch in 'abcdef'):
                    try:
                        val = int(txt, 16)
                    except ValueError:
                        raise ValueError(f"Invalid hex at row {row_index} col {c}: {txt}")
                else:
                    try:
                        val = int(txt, 0)
                    except Exception:
                        raise ValueError(f"Invalid number at row {row_index} col {c}: {txt}")
            if not (0 <= val <= 255):
                raise ValueError(f"Value out of byte range at row {row_index} col {c}: {val}")
            packet.append(val)
        # skip empty packets: a packet whose data bytes are all zero is not sent.
        # (the CRC is excluded from this check since it's non-zero even for a zeroed packet)
        if not any(packet):
            return None
        # compute CRC and append low, high bytes; refresh the read-only CRC cells
        crc = compute_crc16_modbus(bytes(packet))
        packet.append(crc & 0xFF)
        packet.append((crc >> 8) & 0xFF)
        self._update_row_crc(row_index)
        return bytes(packet)

    def _toggle_all_rows(self):
        """Header "On" tick: check or uncheck every packet at once."""
        value = bool(self.select_all_var.get())
        self._suspend_sync = True   # don't let per-row traces flicker the header mid-loop
        try:
            for v in self.enabled_vars:
                v.set(value)
        finally:
            self._suspend_sync = False
        self._sync_select_all()

    def _sync_select_all(self):
        """Keep the header tick in step with the individual row ticks.

        Driven by a `write` trace on every row var, so it stays correct whether a row
        was clicked, restored from a config, or set in code.
        """
        if self._suspend_sync:
            return
        self.select_all_var.set(bool(self.enabled_vars)
                                and all(v.get() for v in self.enabled_vars))

    def _row_enabled(self, row_index: int) -> bool:
        """True if this row's "On" tick is set (a missing var counts as enabled)."""
        try:
            return bool(self.enabled_vars[row_index].get())
        except IndexError:
            return True

    def read_matrix_snapshot(self):
        """Read matrix into a list of (row_index, packet) tuples.

        Includes only rows that are ticked "On" and non-empty — this is what
        Send All Checked sends. Per-row Send bypasses this and goes straight to
        _read_single_packet, so it always sends regardless of the tick.
        """
        packets = []
        for r in range(len(self.entry_widgets)):
            if not self._row_enabled(r):
                continue
            p = self._read_single_packet(r)
            if p is not None:
                packets.append((r, p))
        return packets

    def _set_response(self, row_index: int, text: str):
        """Write text into a row's read-only response field."""
        try:
            entry = self.response_widgets[row_index]
        except IndexError:
            return
        try:
            entry.state(['!readonly'])
        except Exception:
            try:
                entry.config(state='normal')
            except Exception:
                pass
        entry.delete(0, tk.END)
        entry.insert(0, text)
        # light-red field when no reply, normal light-blue otherwise
        entry.configure(style="RespErr.TEntry" if text == "(no response)" else "Resp.TEntry")
        try:
            entry.state(['readonly'])
        except Exception:
            try:
                entry.config(state='readonly')
            except Exception:
                pass

    def _read_response(self):
        """Read a slave reply adaptively: wait for the first byte (up to the port
        timeout), then drain whatever else arrives. Returns bytes (empty if no reply).

        This returns as soon as the frame is complete instead of blocking until a
        fixed byte count / the full read timeout, so sending stays paced by the
        slave's actual response speed.
        """
        if not self.serial_port:
            return b''
        first = self.serial_port.read(1)  # blocks up to the port timeout (~0.2s)
        if not first:
            return b''
        data = bytearray(first)
        # drain the rest of the frame: poll until no new bytes for a few cycles
        idle = 0
        while idle < 3:
            time.sleep(0.01)
            n = getattr(self.serial_port, 'in_waiting', 0)
            if n:
                data.extend(self.serial_port.read(n))
                idle = 0
            else:
                idle += 1
        return bytes(data)

    def send_single(self, row_index: int):
        """Send just one packet (the row's Send button), bypassing continuous mode.

        Captures the slave's reply and shows it (hex) in the row's Response field.
        """
        if not self.serial_port or not getattr(self.serial_port, 'is_open', False):
            messagebox.showerror("Port not open", "Please open a serial port before sending")
            return
        try:
            packet = self._read_single_packet(row_index)
        except ValueError as e:
            messagebox.showerror("Matrix error", str(e))
            return
        if packet is None:
            messagebox.showwarning("Nothing to send", f"Packet{row_index} is empty (data bytes all zero). Nothing was sent.")
            return
        try:
            # clear any stale bytes, send, then read whatever the slave replies
            try:
                self.serial_port.reset_input_buffer()
            except Exception:
                pass
            self.serial_port.write(packet)
            # read the reply adaptively (returns as soon as the frame is complete)
            resp = self._read_response()
            if resp:
                self._set_response(row_index, ' '.join(f"{b:02X}" for b in resp))
                self.status_label.config(text=f"Status: sent Packet{row_index}, got {len(resp)} byte(s)")
            else:
                self._set_response(row_index, "(no response)")
                self.status_label.config(text=f"Status: sent Packet{row_index}, no response")
        except Exception as e:
            messagebox.showerror("Write error", str(e))

    def _update_row_crc(self, row_index: int):
        """Recompute CRC for one row and update the last two read-only cells."""
        try:
            row = self.entry_widgets[row_index]
        except IndexError:
            return
        # build data from non-CRC cells
        data = bytearray()
        ncols = len(row)
        for c in range(ncols - 2):
            txt = row[c].get().strip()
            if not txt:
                val = 0
            elif txt.startswith('0x') or txt.startswith('0X'):
                try:
                    val = int(txt, 16)
                except Exception:
                    val = 0
            else:
                if any(ch in txt.lower() for ch in 'abcdef'):
                    try:
                        val = int(txt, 16)
                    except Exception:
                        val = 0
                else:
                    try:
                        val = int(txt, 0)
                    except Exception:
                        val = 0
            data.append(max(0, min(255, val)))
        crc = compute_crc16_modbus(bytes(data))
        low = crc & 0xFF
        high = (crc >> 8) & 0xFF
        try:
            l_entry = row[-2]
            h_entry = row[-1]
            try:
                l_entry.state(['!readonly'])
            except Exception:
                try:
                    l_entry.config(state='normal')
                except Exception:
                    pass
            try:
                h_entry.state(['!readonly'])
            except Exception:
                try:
                    h_entry.config(state='normal')
                except Exception:
                    pass
            l_entry.delete(0, tk.END)
            l_entry.insert(0, f"{low:02X}")
            h_entry.delete(0, tk.END)
            h_entry.insert(0, f"{high:02X}")
            try:
                l_entry.state(['readonly'])
            except Exception:
                try:
                    l_entry.config(state='readonly')
                except Exception:
                    pass
            try:
                h_entry.state(['readonly'])
            except Exception:
                try:
                    h_entry.config(state='readonly')
                except Exception:
                    pass
        except Exception:
            pass

    def _update_all_crcs(self):
        for r in range(len(self.entry_widgets)):
            self._update_row_crc(r)

    def on_send(self):
        # Snapshot matrix and (re)start sending
        try:
            packets = self.read_matrix_snapshot()
        except ValueError as e:
            messagebox.showerror("Matrix error", str(e))
            return

        if not packets:
            if not any(self._row_enabled(r) for r in range(len(self.entry_widgets))):
                msg = ('No packets are checked. Tick the "On" box on at least one packet, '
                       "or use a row's own Send button.")
            else:
                msg = "All checked packets are empty (data bytes all zero). Nothing was sent."
            messagebox.showwarning("Nothing to send", msg)
            return

        if self.sender_thread and self.sender_thread.is_alive():
            # stop current sender and start new one with new snapshot
            self.stop_event.set()
            self.sender_thread.join(timeout=2)
            self.stop_event.clear()

        cont = self.continuous_var.get()
        interval_ms = max(0, int(self.interval_var.get()))

        self.sender_thread = threading.Thread(target=self._send_worker, args=(packets, cont, interval_ms/1000.0), daemon=True)
        self.sender_thread.start()
        self.status_label.config(text=f"Status: sending ({'continuous' if cont else 'once'})")

    def stop_sending(self):
        if self.sender_thread and self.sender_thread.is_alive():
            self.stop_event.set()
            self.sender_thread.join(timeout=2)
            self.stop_event.clear()
            self.status_label.config(text="Status: idle")

    def _send_worker(self, packets, continuous, interval_s):
        # If serial not open, error
        if not self.serial_port or not getattr(self.serial_port, 'is_open', False):
            self._safe_messagebox("Port not open", "Please open a serial port before sending")
            self._safe_status("Status: idle")
            return

        try:
            while True:
                for r, p in packets:
                    if self.stop_event.is_set():
                        self._safe_status("Status: idle")
                        return
                    # write as bytes, then capture the slave's reply for this row
                    try:
                        try:
                            self.serial_port.reset_input_buffer()
                        except Exception:
                            pass
                        self.serial_port.write(p)
                        resp = self._read_response()
                        text = ' '.join(f"{b:02X}" for b in resp) if resp else "(no response)"
                        # UI updates must happen on the main thread
                        self.after(0, lambda rr=r, t=text: self._set_response(rr, t))
                    except Exception as e:
                        self._safe_messagebox("Write error", str(e))
                        self._safe_status("Status: idle")
                        return
                    # fixed brief sleep between packets (100 ms)
                    # keep responsive to stop_event by sleeping in smaller chunks
                    remaining = 0.100
                    step = 0.02
                    while remaining > 0 and not self.stop_event.is_set():
                        t = min(step, remaining)
                        time.sleep(t)
                        remaining -= t
                if not continuous:
                    # finished
                    self._safe_status("Status: idle")
                    return
                # after sending the whole group, wait group-delay (user-configurable)
                remaining = interval_s
                step = 0.05
                while remaining > 0 and not self.stop_event.is_set():
                    t = min(step, remaining)
                    time.sleep(t)
                    remaining -= t
                if self.stop_event.is_set():
                    self._safe_status("Status: idle")
                    return
                # Re-read the matrix so the next pass sends what the cells say *now*:
                # edits (and tick changes) made mid-run take effect on the next pass
                # instead of being frozen at the values captured when Send was pressed.
                # A failed read means the matrix is momentarily invalid — mid-keystroke,
                # typically — so keep the last good packets rather than erroring out.
                fresh, err = self._snapshot_from_ui()
                if fresh is not None and err is None:
                    packets = fresh
                    self._safe_status("Status: sending (continuous)" if packets else
                                      "Status: sending (continuous) - nothing checked")
        finally:
            pass

    def _safe_status(self, text):
        """Set the status bar from any thread."""
        self.after(0, lambda: self.status_label.config(text=text))

    def _snapshot_from_ui(self, timeout=2.0):
        """Re-read the matrix from the sender thread.

        The matrix is Tk widgets and _read_single_packet also rewrites the CRC cells,
        so the read has to happen on the main thread — this marshals it there and waits.
        Returns (packets, error): `error` is set when the matrix currently holds invalid
        input (a half-typed cell, say), and both are None if the main thread didn't
        answer in time. Callers keep their previous packet set in either case.
        """
        box = {}
        done = threading.Event()

        def grab():
            try:
                box['packets'] = self.read_matrix_snapshot()
            except Exception as exc:
                box['error'] = exc
            finally:
                done.set()

        self.after(0, grab)
        if not done.wait(timeout):
            return None, None
        return box.get('packets'), box.get('error')

    def _safe_messagebox(self, title, msg):
        # Show messagebox safely from thread using after
        self.after(0, lambda: messagebox.showerror(title, msg))


def main():
    app = SerialSimulator()
    app.mainloop()


if __name__ == '__main__':
    main()
