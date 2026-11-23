from __future__ import annotations

from core.serial_scanner import SerialScanner


class _FakeSerial:
    """Port série simulé : un scan complet déjà reçu, puis plus rien."""

    def __init__(self, scanner: SerialScanner, data: bytes) -> None:
        self._scanner = scanner
        self._data = data
        self.sizes: list[int] = []

    @property
    def in_waiting(self) -> int:
        return len(self._data)

    def read(self, size: int) -> bytes:
        self.sizes.append(size)
        out, self._data = self._data[:size], self._data[size:]
        if not self._data:
            self._scanner._stop_event.set()
        return out


def test_scan_emitted_without_waiting_for_a_full_block():
    scanner = SerialScanner("COM_TEST")
    ser = _FakeSerial(scanner, b"Tk-1234567890\r\n")
    scanner._read_loop(ser)
    assert scanner.lines.get_nowait() == "Tk-1234567890"
    # Jamais plus que les octets disponibles : sinon pyserial attend le timeout.
    assert ser.sizes == [15]


def test_blocks_on_a_single_byte_when_idle():
    scanner = SerialScanner("COM_TEST")
    ser = _FakeSerial(scanner, b"")
    scanner._read_loop(ser)
    assert ser.sizes == [1]
