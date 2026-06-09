# Serial Simulator

Simple Python/Tkinter GUI to send packets of bytes over a serial port.

Features
- Select serial port and open/close
- Configure baud, parity, stop bits
- Build a matrix where columns = bytes per packet and rows = packets
- Send once or continuously with configurable interval between packets
- While continuous sending is active, edits to the matrix won't affect the active send until you press Send again

Requirements
- Python 3.8+
- pyserial

Install:

```
pip install -r requirements.txt
```

Run:

```
python serial_simulator.py
```

Notes
- Enter bytes as decimal (e.g. 10), hex (0x0A) or hex without prefix (0A). Values must be 0..255.
- Matrix: use "Bytes/packet" and "Packets" to set the size and click "Apply Matrix Size".
