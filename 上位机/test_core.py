import tempfile
import unittest
from pathlib import Path

from main import HostComputerApp, load_file_payload, parse_bitrate, parse_delay_seconds, parse_intel_hex, parse_manual_payload


class ParserTests(unittest.TestCase):
    def test_parse_manual_hex(self) -> None:
        self.assertEqual(parse_manual_payload("01 02,0A\nff", True), bytes([1, 2, 10, 255]))

    def test_parse_manual_text(self) -> None:
        self.assertEqual(parse_manual_payload("hello", False), b"hello")

    def test_parse_bitrate_with_units(self) -> None:
        self.assertEqual(parse_bitrate("500 kbps"), 500000)
        self.assertEqual(parse_bitrate("1 Mbps"), 1000000)
        self.assertEqual(parse_bitrate("250000"), 250000)

    def test_parse_delay_with_units(self) -> None:
        self.assertEqual(parse_delay_seconds("100", "us"), 0.0001)
        self.assertEqual(parse_delay_seconds("5", "ms"), 0.005)
        self.assertEqual(parse_delay_seconds("1", "s"), 1.0)

    def test_parse_tcp_port(self) -> None:
        self.assertEqual(HostComputerApp.parse_tcp_port("8080"), 8080)
        with self.assertRaises(ValueError):
            HostComputerApp.parse_tcp_port("70000")

    def test_parse_intel_hex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sample = Path(temp_dir) / "sample.hex"
            sample.write_text(
                "\n".join(
                    [
                        ":020000040800F2",
                        ":100000000102030405060708090A0B0C0D0E0F1068",
                        ":00000001FF",
                    ]
                ),
                encoding="ascii",
            )
            self.assertEqual(parse_intel_hex(sample), bytes(range(1, 17)))

    def test_load_text_hex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sample = Path(temp_dir) / "payload.txt"
            sample.write_text("AA 55 00 FF", encoding="ascii")
            self.assertEqual(load_file_payload(str(sample)), bytes([0xAA, 0x55, 0x00, 0xFF]))


if __name__ == "__main__":
    unittest.main()
