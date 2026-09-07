from __future__ import annotations

import logging
import queue
import threading

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)

_LINE_TERMINATORS = (0x0D, 0x0A)  # CR, LF — acceptés seuls ou combinés (CRLF)
_RECONNECT_DELAY_SECONDS = 2.0
_READ_TIMEOUT_SECONDS = 0.2
_READ_CHUNK_SIZE = 64


def list_serial_ports() -> list[tuple[str, str]]:
    """Retourne (device, description) pour chaque port série détecté,
    ex. ("COM5", "USB Serial Device (COM5)")."""
    try:
        return [(p.device, p.description or p.device) for p in list_ports.comports()]
    except Exception:
        return []


class SerialScanner:
    """Lit en tâche de fond une douchette configurée en mode "USB-COM Virtual
    Serial Port" (ex. Tera 9000, cf. notes/guide_architecture_impression.md).

    Contrairement au mode émulation clavier (HID), ce mode ne nécessite PAS que
    la fenêtre TMO ait le focus Windows : les octets arrivent sur le port COM
    indépendamment de la fenêtre active.
    """

    def __init__(self, port: str, baudrate: int = 9600) -> None:
        self.port = port
        self.baudrate = baudrate
        self.lines: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="tmo_serial_scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with serial.Serial(self.port, self.baudrate, timeout=_READ_TIMEOUT_SECONDS) as ser:
                    log.info("serial_scanner_connected port=%s baud=%d", self.port, self.baudrate)
                    self._read_loop(ser)
            except Exception as e:
                log.warning("serial_scanner_error port=%s error=%s", self.port, e)
                self._stop_event.wait(_RECONNECT_DELAY_SECONDS)

    def _read_loop(self, ser: "serial.Serial") -> None:
        buf = bytearray()
        while not self._stop_event.is_set():
            chunk = ser.read(_READ_CHUNK_SIZE)
            if not chunk:
                continue
            for byte in chunk:
                if byte in _LINE_TERMINATORS:
                    if buf:
                        self._emit(bytes(buf))
                        buf.clear()
                else:
                    buf.append(byte)

    def _emit(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            return
        if text:
            self.lines.put_nowait(text)
