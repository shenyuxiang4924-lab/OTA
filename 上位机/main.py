from __future__ import annotations

import binascii
import json
import os
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - depends on local installation
    serial = None
    list_ports = None

try:
    import can
except Exception:  # pragma: no cover - depends on local installation
    can = None


LogFunc = Callable[[str], None]
ProgressFunc = Callable[[int, int], None]

CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / "USART_CAN_上位机" / "config.json"


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def hex_dump(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def parse_bitrate(text: str) -> int:
    value = text.strip().lower().replace(" ", "")
    if value.endswith("kbps"):
        return int(float(value[:-4]) * 1000)
    if value.endswith("mbps"):
        return int(float(value[:-4]) * 1000 * 1000)
    if value.endswith("k"):
        return int(float(value[:-1]) * 1000)
    if value.endswith("m"):
        return int(float(value[:-1]) * 1000 * 1000)
    return int(value)


def parse_delay_seconds(value_text: str, unit_text: str) -> float:
    value = float(value_text.strip() or "0")
    if value < 0:
        raise ValueError("延时不能小于 0")
    unit = unit_text.strip().lower()
    if unit in ("us", "μs", "微秒"):
        return value / 1_000_000
    if unit in ("ms", "毫秒"):
        return value / 1_000
    if unit in ("s", "秒"):
        return value
    raise ValueError(f"不支持的延时单位: {unit_text}")


def parse_manual_payload(text: str, hex_mode: bool) -> bytes:
    if not text.strip():
        return b""
    if not hex_mode:
        return text.encode("utf-8")
    normalized = text.replace(",", " ").replace("\n", " ").replace("\t", " ")
    compact = "".join(normalized.split())
    if len(compact) % 2:
        raise ValueError("HEX 数据长度必须是偶数")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("HEX 数据包含非法字符") from exc


def parse_intel_hex(path: Path) -> bytes:
    segments: dict[int, int] = {}
    upper = 0
    min_addr: Optional[int] = None
    max_addr = 0

    for line_no, raw_line in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise ValueError(f"第 {line_no} 行不是 Intel HEX 记录")
        try:
            record = bytes.fromhex(line[1:])
        except ValueError as exc:
            raise ValueError(f"第 {line_no} 行包含非法 HEX 字符") from exc
        if len(record) < 5:
            raise ValueError(f"第 {line_no} 行记录过短")
        count = record[0]
        if len(record) != count + 5:
            raise ValueError(f"第 {line_no} 行长度字段不匹配")
        checksum = sum(record) & 0xFF
        if checksum != 0:
            raise ValueError(f"第 {line_no} 行校验和错误")

        addr = (record[1] << 8) | record[2]
        rec_type = record[3]
        data = record[4 : 4 + count]

        if rec_type == 0x00:
            base = upper + addr
            for offset, value in enumerate(data):
                absolute = base + offset
                segments[absolute] = value
            min_addr = base if min_addr is None else min(min_addr, base)
            max_addr = max(max_addr, base + len(data))
        elif rec_type == 0x01:
            break
        elif rec_type == 0x02:
            if count != 2:
                raise ValueError(f"第 {line_no} 行扩展段地址长度错误")
            upper = (((data[0] << 8) | data[1]) << 4)
        elif rec_type == 0x04:
            if count != 2:
                raise ValueError(f"第 {line_no} 行扩展线性地址长度错误")
            upper = (((data[0] << 8) | data[1]) << 16)
        elif rec_type in (0x03, 0x05):
            continue
        else:
            raise ValueError(f"第 {line_no} 行记录类型 0x{rec_type:02X} 不支持")

    if min_addr is None:
        return b""
    image = bytearray([0xFF] * (max_addr - min_addr))
    for addr, value in segments.items():
        image[addr - min_addr] = value
    return bytes(image)


def load_file_payload(path_text: str) -> bytes:
    path = Path(path_text)
    suffix = path.suffix.lower()
    if suffix == ".hex":
        return parse_intel_hex(path)
    if suffix == ".bin":
        return path.read_bytes()
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return raw
    compact = "".join(text.replace(",", " ").split())
    if compact and len(compact) % 2 == 0:
        try:
            return bytes.fromhex(compact)
        except ValueError:
            pass
    return raw


@dataclass
class SendOptions:
    chunk_bytes: int
    delay_seconds: float
    fast_chunk_bytes: int = 4096
    log_interval_seconds: float = 0.1
    progress_interval_seconds: float = 0.05
    log_every_bytes: int = 1024
    log_payload: bool = False
    log_every_chunk: bool = False


class SenderThread(threading.Thread):
    def __init__(
        self,
        payload: bytes,
        options: SendOptions,
        send_chunk: Callable[[bytes], None],
        log: LogFunc,
        progress: ProgressFunc,
        done: Callable[[], None],
    ) -> None:
        super().__init__(daemon=True)
        self.payload = payload
        self.options = options
        self.send_chunk = send_chunk
        self.log = log
        self.progress = progress
        self.done = done
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def precise_delay(self, delay_seconds: float) -> None:
        end_time = time.perf_counter() + delay_seconds
        if delay_seconds > 0.002:
            sleep_until = end_time - 0.001
            while time.perf_counter() < sleep_until:
                if self.stop_event.wait(0.0005):
                    return
        while time.perf_counter() < end_time:
            if self.stop_event.is_set():
                return

    def run(self) -> None:
        try:
            chunk_size = max(1, self.options.chunk_bytes)
            if self.options.delay_seconds == 0:
                chunk_size = max(chunk_size, self.options.fast_chunk_bytes)
            total = len(self.payload)
            sent = 0
            last_logged = 0
            started_at = time.perf_counter()
            next_log_at = started_at
            next_progress_at = started_at
            self.progress(0, total)
            while sent < total and not self.stop_event.is_set():
                chunk = self.payload[sent : sent + chunk_size]
                self.send_chunk(chunk)
                sent += len(chunk)
                now = time.perf_counter()
                should_log = (
                    sent >= total
                    or self.options.log_every_chunk
                    or now >= next_log_at
                    or sent - last_logged >= self.options.log_every_bytes
                )
                if should_log:
                    if self.options.log_payload and len(chunk) <= 64:
                        self.log(f"TX {sent}/{total}: {hex_dump(chunk)}")
                    else:
                        self.log(f"TX {sent}/{total}: {len(chunk)} 字节")
                    last_logged = sent
                    next_log_at = now + self.options.log_interval_seconds
                if sent >= total or now >= next_progress_at:
                    self.progress(sent, total)
                    next_progress_at = now + self.options.progress_interval_seconds
                if sent < total and self.options.delay_seconds > 0:
                    self.precise_delay(self.options.delay_seconds)
                elif sent < total:
                    time.sleep(0)
            if self.stop_event.is_set():
                self.log("发送已停止")
            else:
                elapsed = max(time.perf_counter() - started_at, 0.000001)
                speed = total / elapsed
                self.log(f"发送完成: 耗时={elapsed:.3f}s, 速度={speed:.1f} B/s")
        except Exception as exc:
            self.log(f"发送失败: {exc}")
        finally:
            self.done()


class SerialClient:
    def __init__(self, log: LogFunc) -> None:
        self.log = log
        self.port = None
        self.reader: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    @property
    def connected(self) -> bool:
        return self.port is not None and self.port.is_open

    def open(self, port: str, baudrate: int, bytesize: int, parity: str, stopbits: float) -> None:
        if serial is None:
            raise RuntimeError("未安装 pyserial，请先执行 pip install -r requirements.txt")
        self.close()
        self.port = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=0.05,
            write_timeout=1,
        )
        self.stop_event.clear()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self.log(f"串口已打开: {port} @ {baudrate}")

    def close(self) -> None:
        self.stop_event.set()
        if self.port is not None:
            try:
                self.port.close()
            finally:
                self.log("串口已关闭")
        self.port = None

    def send(self, data: bytes) -> None:
        if not self.connected:
            raise RuntimeError("串口未连接")
        self.port.write(data)
        self.port.flush()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set() and self.port is not None:
            try:
                data = self.port.read(4096)
                if data:
                    self.log(f"RX USART {len(data)}B: {hex_dump(data)}")
            except Exception as exc:
                self.log(f"串口接收失败: {exc}")
                break


class CanClient:
    def __init__(self, log: LogFunc) -> None:
        self.log = log
        self.bus = None
        self.reader: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    @property
    def connected(self) -> bool:
        return self.bus is not None

    def open(self, interface: str, channel: str, bitrate: int, sample_point: Optional[float] = None) -> None:
        if can is None:
            raise RuntimeError("未安装 python-can，请先执行 pip install -r requirements.txt")
        self.close()
        bus_options = {"interface": interface, "channel": channel, "bitrate": bitrate}
        if sample_point is not None:
            bus_options["sample_point"] = sample_point
        self.bus = can.Bus(**bus_options)
        self.stop_event.clear()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        sample_text = "" if sample_point is None else f", sample_point={sample_point:g}%"
        self.log(f"CAN 已打开: {interface}, channel={channel}, bitrate={bitrate}{sample_text}")

    def close(self) -> None:
        self.stop_event.set()
        if self.bus is not None:
            try:
                self.bus.shutdown()
            finally:
                self.log("CAN 已关闭")
        self.bus = None

    def send_frame(self, arbitration_id: int, data: bytes, extended: bool, remote: bool) -> None:
        if not self.connected:
            raise RuntimeError("CAN 未连接")
        if len(data) > 8:
            raise RuntimeError("经典 CAN 单帧最多 8 字节")
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=b"" if remote else data,
            dlc=len(data),
            is_extended_id=extended,
            is_remote_frame=remote,
        )
        self.bus.send(msg, timeout=1)

    def _read_loop(self) -> None:
        while not self.stop_event.is_set() and self.bus is not None:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is None:
                    continue
                kind = "EXT" if msg.is_extended_id else "STD"
                self.log(f"RX CAN {kind} ID=0x{msg.arbitration_id:X} DLC={msg.dlc}: {hex_dump(bytes(msg.data))}")
            except Exception as exc:
                self.log(f"CAN 接收失败: {exc}")
                break


class TcpClient:
    def __init__(self, log: LogFunc) -> None:
        self.log = log
        self.mode = ""
        self.socket: Optional[socket.socket] = None
        self.server_socket: Optional[socket.socket] = None
        self.reader: Optional[threading.Thread] = None
        self.acceptor: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    @property
    def connected(self) -> bool:
        if self.mode == "Server":
            return self.server_socket is not None
        return self.socket is not None

    def open_client(self, host: str, port: int) -> None:
        self.close()
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect((host, port))
        client.settimeout(0.1)
        with self.lock:
            self.socket = client
            self.mode = "Client"
        self.stop_event.clear()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self.log(f"TCP Client 已连接: host={host}, port={port}")

    def open_server(self, host: str, port: int) -> None:
        self.close()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        server.settimeout(0.1)
        with self.lock:
            self.server_socket = server
            self.mode = "Server"
        self.stop_event.clear()
        self.acceptor = threading.Thread(target=self._accept_loop, daemon=True)
        self.acceptor.start()
        self.log(f"TCP Server 正在监听: host={host}, port={port}")

    def close(self) -> None:
        self.stop_event.set()
        had_connection = self.socket is not None or self.server_socket is not None
        with self.lock:
            client = self.socket
            server = self.server_socket
            self.socket = None
            self.server_socket = None
            self.mode = ""
        for item in (client, server):
            if item is not None:
                try:
                    item.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    item.close()
                except OSError:
                    pass
        if had_connection:
            self.log("TCP 已关闭")

    def send(self, data: bytes) -> None:
        with self.lock:
            client = self.socket
        if client is None:
            raise RuntimeError("TCP 尚未建立数据连接")
        client.sendall(data)

    def _accept_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                server = self.server_socket
            if server is None:
                return
            try:
                client, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            client.settimeout(0.1)
            with self.lock:
                old_client = self.socket
                self.socket = client
            if old_client is not None:
                try:
                    old_client.close()
                except OSError:
                    pass
            self.log(f"TCP Client 已接入: host={address[0]}, port={address[1]}")
            self._read_loop()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                client = self.socket
            if client is None:
                return
            try:
                data = client.recv(4096)
                if not data:
                    self.log("TCP 对端已断开")
                    break
                self.log(f"RX TCP {len(data)}B: {hex_dump(data)}")
            except socket.timeout:
                continue
            except OSError as exc:
                if not self.stop_event.is_set():
                    self.log(f"TCP 接收失败: {exc}")
                break
        with self.lock:
            if self.socket is client:
                self.socket = None
        try:
            client.close()
        except OSError:
            pass


class HostComputerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("USART/CAN/TCP 上位机")
        self.geometry("1120x760")
        self.minsize(980, 680)

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.serial_client = SerialClient(self.enqueue_log)
        self.can_client = CanClient(self.enqueue_log)
        self.tcp_client = TcpClient(self.enqueue_log)
        self.sender: Optional[SenderThread] = None

        self._build_vars()
        self.load_settings()
        self._configure_theme()
        self._build_ui()
        self._poll_logs()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_theme(self) -> None:
        self.colors = {
            "window": "#181818",
            "panel": "#1e1e1e",
            "panel_alt": "#252526",
            "field": "#1f1f1f",
            "field_alt": "#2d2d30",
            "border": "#3c3c3c",
            "cursor": "#ffffff",
            "text": "#d4d4d4",
            "muted": "#858585",
            "accent": "#007acc",
            "accent_active": "#0e639c",
            "log_bg": "#1e1e1e",
            "log_text": "#d4d4d4",
            "log_time": "#858585",
            "log_tx": "#9cdcfe",
            "log_rx": "#6a9955",
            "log_error": "#f48771",
            "log_warn": "#dcdcaa",
            "log_ok": "#4ec9b0",
            "log_key": "#569cd6",
            "log_equal": "#d4d4d4",
            "log_value": "#b5cea8",
            "log_data": "#ce9178",
            "log_path": "#c586c0",
            "log_count": "#dcdcaa",
        }
        self.configure(background=self.colors["window"])
        self.option_add("*TCombobox*Listbox.background", self.colors["field"])
        self.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 9), foreground=self.colors["text"])
        style.configure("TFrame", background=self.colors["panel"])
        style.configure("Window.TFrame", background=self.colors["window"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure(
            "TLabelframe",
            background=self.colors["panel"],
            bordercolor=self.colors["border"],
            darkcolor=self.colors["border"],
            lightcolor=self.colors["border"],
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=self.colors["panel"],
            foreground=self.colors["text"],
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure("TLabel", background=self.colors["panel"], foreground=self.colors["text"])
        style.configure(
            "TEntry",
            fieldbackground=self.colors["field"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            insertcolor=self.colors["cursor"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", self.colors["field_alt"]), ("readonly", self.colors["field_alt"])],
            foreground=[("disabled", self.colors["muted"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.colors["field"],
            background=self.colors["field"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            insertcolor=self.colors["cursor"],
            arrowcolor=self.colors["muted"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors["field"]), ("disabled", self.colors["field_alt"])],
            foreground=[("disabled", self.colors["muted"])],
            arrowcolor=[("disabled", self.colors["muted"]), ("active", self.colors["text"])],
        )
        style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["text"])
        style.map(
            "TCheckbutton",
            background=[("active", self.colors["panel"])],
            foreground=[("disabled", self.colors["muted"])],
            indicatorcolor=[("selected", self.colors["accent"]), ("!selected", self.colors["field_alt"])],
        )
        style.configure(
            "TButton",
            background=self.colors["field_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            focusthickness=1,
            focuscolor=self.colors["accent"],
            padding=(10, 5),
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
        )
        style.map(
            "TButton",
            background=[("active", "#3e3e42"), ("pressed", "#094771"), ("disabled", "#2a2a2a")],
            foreground=[("disabled", self.colors["muted"])],
        )
        style.configure("Accent.TButton", background=self.colors["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", self.colors["accent_active"])])
        style.configure(
            "Horizontal.TProgressbar",
            background=self.colors["accent"],
            troughcolor=self.colors["field_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
        )

    def _build_vars(self) -> None:
        self.protocol_var = tk.StringVar(value="USART")
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.bytesize_var = tk.StringVar(value="8")
        self.parity_var = tk.StringVar(value="N")
        self.stopbits_var = tk.StringVar(value="1")

        self.can_interface_var = tk.StringVar(value="pcan")
        self.can_channel_var = tk.StringVar(value="PCAN_USBBUS1")
        self.can_bitrate_var = tk.StringVar(value="500 kbps")
        self.can_sample_point_var = tk.StringVar(value="87.5")
        self.can_id_var = tk.StringVar(value="0x123")
        self.can_extended_var = tk.BooleanVar(value=False)
        self.can_remote_var = tk.BooleanVar(value=False)

        self.tcp_mode_var = tk.StringVar(value="Client")
        self.tcp_remote_host_var = tk.StringVar(value="127.0.0.1")
        self.tcp_remote_port_var = tk.StringVar(value="8080")
        self.tcp_listen_host_var = tk.StringVar(value="0.0.0.0")
        self.tcp_listen_port_var = tk.StringVar(value="8080")

        self.manual_hex_var = tk.BooleanVar(value=True)
        self.file_path_var = tk.StringVar()
        self.chunk_var = tk.StringVar(value="8")
        self.delay_var = tk.StringVar(value="0")
        self.delay_unit_var = tk.StringVar(value="ms")
        self.repeat_var = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text_var = tk.StringVar(value="0 / 0 字节")

    def settings_payload(self) -> dict[str, object]:
        return {
            "protocol": self.protocol_var.get(),
            "serial": {
                "port": self.port_var.get(),
                "baudrate": self.baud_var.get(),
                "bytesize": self.bytesize_var.get(),
                "parity": self.parity_var.get(),
                "stopbits": self.stopbits_var.get(),
            },
            "can": {
                "interface": self.can_interface_var.get(),
                "channel": self.can_channel_var.get(),
                "bitrate": self.can_bitrate_var.get(),
                "sample_point": self.can_sample_point_var.get(),
                "id": self.can_id_var.get(),
                "extended": self.can_extended_var.get(),
                "remote": self.can_remote_var.get(),
            },
            "tcp": {
                "mode": self.tcp_mode_var.get(),
                "remote_host": self.tcp_remote_host_var.get(),
                "remote_port": self.tcp_remote_port_var.get(),
                "listen_host": self.tcp_listen_host_var.get(),
                "listen_port": self.tcp_listen_port_var.get(),
            },
            "send": {
                "manual_hex": self.manual_hex_var.get(),
                "file_path": self.file_path_var.get(),
                "chunk_bytes": self.chunk_var.get(),
                "delay": self.delay_var.get(),
                "delay_unit": self.delay_unit_var.get(),
            },
        }

    def load_settings(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        serial_settings = data.get("serial", {})
        can_settings = data.get("can", {})
        tcp_settings = data.get("tcp", {})
        send_settings = data.get("send", {})

        self.protocol_var.set(str(data.get("protocol", self.protocol_var.get())))
        self.port_var.set(str(serial_settings.get("port", self.port_var.get())))
        self.baud_var.set(str(serial_settings.get("baudrate", self.baud_var.get())))
        self.bytesize_var.set(str(serial_settings.get("bytesize", self.bytesize_var.get())))
        self.parity_var.set(str(serial_settings.get("parity", self.parity_var.get())))
        self.stopbits_var.set(str(serial_settings.get("stopbits", self.stopbits_var.get())))

        self.can_interface_var.set(str(can_settings.get("interface", self.can_interface_var.get())))
        self.can_channel_var.set(str(can_settings.get("channel", self.can_channel_var.get())))
        self.can_bitrate_var.set(str(can_settings.get("bitrate", self.can_bitrate_var.get())))
        self.can_sample_point_var.set(str(can_settings.get("sample_point", self.can_sample_point_var.get())))
        self.can_id_var.set(str(can_settings.get("id", self.can_id_var.get())))
        self.can_extended_var.set(bool(can_settings.get("extended", self.can_extended_var.get())))
        self.can_remote_var.set(bool(can_settings.get("remote", self.can_remote_var.get())))

        self.tcp_mode_var.set(str(tcp_settings.get("mode", self.tcp_mode_var.get())))
        self.tcp_remote_host_var.set(str(tcp_settings.get("remote_host", self.tcp_remote_host_var.get())))
        self.tcp_remote_port_var.set(str(tcp_settings.get("remote_port", self.tcp_remote_port_var.get())))
        self.tcp_listen_host_var.set(str(tcp_settings.get("listen_host", self.tcp_listen_host_var.get())))
        self.tcp_listen_port_var.set(str(tcp_settings.get("listen_port", self.tcp_listen_port_var.get())))

        self.manual_hex_var.set(bool(send_settings.get("manual_hex", self.manual_hex_var.get())))
        self.file_path_var.set(str(send_settings.get("file_path", self.file_path_var.get())))
        self.chunk_var.set(str(send_settings.get("chunk_bytes", self.chunk_var.get())))
        self.delay_var.set(str(send_settings.get("delay", self.delay_var.get())))
        self.delay_unit_var.set(str(send_settings.get("delay_unit", self.delay_unit_var.get())))

    def save_settings(self) -> None:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                json.dumps(self.settings_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self.enqueue_log(f"配置保存失败: {exc}")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_propagate(False)
        left.configure(width=380)
        right = ttk.Frame(self, padding=(0, 10, 10, 10), style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_connection_panel(left)
        self._build_send_panel(left)
        self.update_protocol_config()
        self._build_log_panel(right)

    def _build_connection_panel(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="连接", padding=10)
        box.grid(row=0, column=0, sticky="ew")
        box.configure(width=360)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="协议").grid(row=0, column=0, sticky="w", pady=3)
        self.protocol_combo = ttk.Combobox(
            box, textvariable=self.protocol_var, values=["USART", "CAN", "TCP"], state="readonly", width=18
        )
        self.protocol_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.protocol_combo.bind("<<ComboboxSelected>>", self.on_protocol_changed)

        self.serial_config_frame = ttk.Frame(box)
        self.config_stack = ttk.Frame(box, height=205)
        self.config_stack.grid(row=1, column=0, columnspan=3, sticky="nsew")
        self.config_stack.grid_propagate(False)
        self.config_stack.rowconfigure(0, weight=1)
        self.config_stack.columnconfigure(0, weight=1)

        self.serial_config_frame = ttk.Frame(self.config_stack, style="Panel.TFrame")
        self.serial_config_frame.grid(row=0, column=0, sticky="nsew")
        self.serial_config_frame.columnconfigure(1, weight=1)

        ttk.Label(self.serial_config_frame, text="串口").grid(row=0, column=0, sticky="w", pady=3)
        self.port_combo = ttk.Combobox(self.serial_config_frame, textvariable=self.port_var, width=18)
        self.port_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.serial_refresh_button = ttk.Button(self.serial_config_frame, text="刷新", command=self.refresh_ports)
        self.serial_refresh_button.grid(row=0, column=2, padx=(6, 0), pady=3)

        ttk.Label(self.serial_config_frame, text="波特率").grid(row=1, column=0, sticky="w", pady=3)
        self.baud_combo = ttk.Combobox(
            self.serial_config_frame,
            textvariable=self.baud_var,
            values=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"],
            width=18,
        )
        self.baud_combo.grid(row=1, column=1, sticky="ew", pady=3)

        ttk.Label(self.serial_config_frame, text="数据位").grid(row=2, column=0, sticky="w", pady=3)
        self.bytesize_combo = ttk.Combobox(
            self.serial_config_frame, textvariable=self.bytesize_var, values=["5", "6", "7", "8"], state="readonly"
        )
        self.bytesize_combo.grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(self.serial_config_frame, text="校验").grid(row=3, column=0, sticky="w", pady=3)
        self.parity_combo = ttk.Combobox(
            self.serial_config_frame, textvariable=self.parity_var, values=["N", "E", "O", "M", "S"], state="readonly"
        )
        self.parity_combo.grid(row=3, column=1, sticky="ew", pady=3)

        ttk.Label(self.serial_config_frame, text="停止位").grid(row=4, column=0, sticky="w", pady=3)
        self.stopbits_combo = ttk.Combobox(
            self.serial_config_frame, textvariable=self.stopbits_var, values=["1", "1.5", "2"], state="readonly"
        )
        self.stopbits_combo.grid(row=4, column=1, sticky="ew", pady=3)

        self.can_config_frame = ttk.Frame(self.config_stack, style="Panel.TFrame")
        self.can_config_frame.grid(row=0, column=0, sticky="nsew")
        self.can_config_frame.columnconfigure(1, weight=1)

        ttk.Label(self.can_config_frame, text="CAN 接口").grid(row=0, column=0, sticky="w", pady=3)
        self.can_interface_combo = ttk.Combobox(
            self.can_config_frame,
            textvariable=self.can_interface_var,
            values=["pcan", "slcan", "socketcan", "kvaser", "vector", "nican", "usb2can", "virtual"],
        )
        self.can_interface_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.can_interface_combo.bind("<<ComboboxSelected>>", self.on_can_interface_changed)

        ttk.Label(self.can_config_frame, text="CAN 通道").grid(row=1, column=0, sticky="w", pady=3)
        self.can_channel_combo = ttk.Combobox(self.can_config_frame, textvariable=self.can_channel_var)
        self.can_channel_combo.grid(row=1, column=1, sticky="ew", pady=3)
        self.can_refresh_button = ttk.Button(self.can_config_frame, text="刷新", command=self.refresh_can_channels)
        self.can_refresh_button.grid(row=1, column=2, padx=(6, 0), pady=3)

        ttk.Label(self.can_config_frame, text="CAN 速率").grid(row=2, column=0, sticky="w", pady=3)
        self.can_bitrate_combo = ttk.Combobox(
            self.can_config_frame,
            textvariable=self.can_bitrate_var,
            values=["125 kbps", "250 kbps", "500 kbps", "1 Mbps"],
        )
        self.can_bitrate_combo.grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(self.can_config_frame, text="采样点(%)").grid(row=3, column=0, sticky="w", pady=3)
        self.can_sample_point_entry = ttk.Entry(self.can_config_frame, textvariable=self.can_sample_point_var)
        self.can_sample_point_entry.grid(row=3, column=1, sticky="ew", pady=3)

        ttk.Label(self.can_config_frame, text="CAN ID").grid(row=4, column=0, sticky="w", pady=3)
        self.can_id_entry = ttk.Entry(self.can_config_frame, textvariable=self.can_id_var)
        self.can_id_entry.grid(row=4, column=1, sticky="ew", pady=3)

        frame_line = ttk.Frame(self.can_config_frame)
        frame_line.grid(row=5, column=0, columnspan=2, sticky="ew", pady=3)
        self.can_extended_check = tk.Checkbutton(
            frame_line,
            text="扩展帧",
            variable=self.can_extended_var,
            background=self.colors["panel"],
            foreground=self.colors["text"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            selectcolor=self.colors["field_alt"],
            highlightthickness=0,
            highlightbackground=self.colors["panel"],
            relief="flat",
            borderwidth=0,
            disabledforeground=self.colors["muted"],
        )
        self.can_extended_check.grid(row=0, column=0, sticky="w")
        self.can_remote_check = tk.Checkbutton(
            frame_line,
            text="远程帧",
            variable=self.can_remote_var,
            background=self.colors["panel"],
            foreground=self.colors["text"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            selectcolor=self.colors["field_alt"],
            highlightthickness=0,
            highlightbackground=self.colors["panel"],
            relief="flat",
            borderwidth=0,
            disabledforeground=self.colors["muted"],
        )
        self.can_remote_check.grid(row=0, column=1, sticky="w", padx=(16, 0))

        self.tcp_config_frame = ttk.Frame(self.config_stack, style="Panel.TFrame")
        self.tcp_config_frame.grid(row=0, column=0, sticky="nsew")
        self.tcp_config_frame.columnconfigure(1, weight=1)

        ttk.Label(self.tcp_config_frame, text="TCP 模式").grid(row=0, column=0, sticky="w", pady=3)
        self.tcp_mode_combo = ttk.Combobox(
            self.tcp_config_frame,
            textvariable=self.tcp_mode_var,
            values=["Client", "Server"],
            state="readonly",
        )
        self.tcp_mode_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.tcp_mode_combo.bind("<<ComboboxSelected>>", self.on_tcp_mode_changed)

        self.tcp_endpoint_stack = ttk.Frame(self.tcp_config_frame, height=74)
        self.tcp_endpoint_stack.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.tcp_endpoint_stack.grid_propagate(False)
        self.tcp_endpoint_stack.rowconfigure(0, weight=1)
        self.tcp_endpoint_stack.columnconfigure(0, weight=1)

        self.tcp_client_frame = ttk.Frame(self.tcp_endpoint_stack, style="Panel.TFrame")
        self.tcp_client_frame.grid(row=0, column=0, sticky="nsew")
        self.tcp_client_frame.columnconfigure(1, weight=1)
        ttk.Label(self.tcp_client_frame, text="远端 IP").grid(row=0, column=0, sticky="w", pady=3)
        self.tcp_remote_host_entry = ttk.Entry(self.tcp_client_frame, textvariable=self.tcp_remote_host_var)
        self.tcp_remote_host_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(self.tcp_client_frame, text="远端端口").grid(row=1, column=0, sticky="w", pady=3)
        self.tcp_remote_port_entry = ttk.Entry(self.tcp_client_frame, textvariable=self.tcp_remote_port_var)
        self.tcp_remote_port_entry.grid(row=1, column=1, sticky="ew", pady=3)

        self.tcp_server_frame = ttk.Frame(self.tcp_endpoint_stack, style="Panel.TFrame")
        self.tcp_server_frame.grid(row=0, column=0, sticky="nsew")
        self.tcp_server_frame.columnconfigure(1, weight=1)
        ttk.Label(self.tcp_server_frame, text="监听地址").grid(row=0, column=0, sticky="w", pady=3)
        self.tcp_listen_host_entry = ttk.Entry(self.tcp_server_frame, textvariable=self.tcp_listen_host_var)
        self.tcp_listen_host_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(self.tcp_server_frame, text="监听端口").grid(row=1, column=0, sticky="w", pady=3)
        self.tcp_listen_port_entry = ttk.Entry(self.tcp_server_frame, textvariable=self.tcp_listen_port_var)
        self.tcp_listen_port_entry.grid(row=1, column=1, sticky="ew", pady=3)

        buttons = ttk.Frame(box)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        buttons.columnconfigure(0, weight=1)
        self.connect_button = ttk.Button(buttons, text="连接", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=0, sticky="ew")

        self.refresh_ports()
        self.refresh_can_channels()
        self.update_tcp_mode_config()
        self.update_protocol_config()
        self.update_connect_button()

    def _build_send_panel(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="发送", padding=10)
        box.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        box.configure(width=360)
        parent.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)

        ttk.Label(box, text="手动数据").grid(row=0, column=0, sticky="w")
        self.manual_text = tk.Text(
            box,
            height=7,
            width=42,
            wrap="word",
            undo=True,
            background=self.colors["field"],
            foreground=self.colors["text"],
            insertbackground=self.colors["cursor"],
            selectbackground="#264f78",
            selectforeground="#ffffff",
            relief="solid",
            borderwidth=1,
            font=("Consolas", 10),
        )
        self.manual_text.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
        box.rowconfigure(1, weight=1)

        mode_line = ttk.Frame(box)
        mode_line.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.manual_hex_check = tk.Checkbutton(
            mode_line,
            text="按 HEX 解析",
            variable=self.manual_hex_var,
            background=self.colors["panel"],
            foreground=self.colors["text"],
            activebackground=self.colors["panel"],
            activeforeground=self.colors["text"],
            selectcolor=self.colors["field_alt"],
            highlightthickness=0,
            highlightbackground=self.colors["panel"],
            relief="flat",
            borderwidth=0,
            disabledforeground=self.colors["muted"],
        )
        self.manual_hex_check.grid(row=0, column=0, sticky="w")
        ttk.Button(mode_line, text="发送手动数据", command=self.send_manual).grid(row=0, column=1, padx=(12, 0))

        file_line = ttk.Frame(box)
        file_line.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        file_line.columnconfigure(0, weight=1)
        ttk.Entry(file_line, textvariable=self.file_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(file_line, text="选择文件", command=self.choose_file).grid(row=0, column=1, padx=(6, 0))

        delay_line = ttk.Frame(box)
        delay_line.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(delay_line, text="每").grid(row=0, column=0)
        ttk.Entry(delay_line, textvariable=self.chunk_var, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(delay_line, text="字节延时").grid(row=0, column=2)
        ttk.Entry(delay_line, textvariable=self.delay_var, width=8).grid(row=0, column=3, padx=4)
        self.delay_unit_combo = ttk.Combobox(
            delay_line,
            textvariable=self.delay_unit_var,
            values=["us", "ms", "s"],
            state="readonly",
            width=5,
        )
        self.delay_unit_combo.grid(row=0, column=4)

        action_line = ttk.Frame(box)
        action_line.grid(row=5, column=0, sticky="ew")
        action_line.columnconfigure((0, 1), weight=1)
        ttk.Button(action_line, text="发送文件", command=self.send_file, style="Accent.TButton").grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(action_line, text="停止发送", command=self.stop_sender).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        progress_line = ttk.Frame(box)
        progress_line.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        progress_line.columnconfigure(0, weight=1)
        self.send_progress = ttk.Progressbar(
            progress_line,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.send_progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_line, textvariable=self.progress_text_var, width=18).grid(row=0, column=1, padx=(8, 0))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="收发日志", padding=10)
        box.grid(row=0, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            box,
            wrap="none",
            state="disabled",
            font=("Consolas", 10),
            background=self.colors["log_bg"],
            foreground=self.colors["log_text"],
            insertbackground=self.colors["cursor"],
            selectbackground="#264f78",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self._configure_log_tags()
        scroll_y = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll_y.set)
        toolbar = ttk.Frame(box)
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(toolbar, text="清空日志", command=self.clear_log).pack(side="left")

    def _configure_log_tags(self) -> None:
        self.log_text.tag_configure("time", foreground=self.colors["log_time"])
        self.log_text.tag_configure("tx", foreground=self.colors["log_tx"])
        self.log_text.tag_configure("rx", foreground=self.colors["log_rx"])
        self.log_text.tag_configure("error", foreground=self.colors["log_error"])
        self.log_text.tag_configure("warn", foreground=self.colors["log_warn"])
        self.log_text.tag_configure("ok", foreground=self.colors["log_ok"])
        self.log_text.tag_configure("key", foreground=self.colors["log_key"])
        self.log_text.tag_configure("equal", foreground=self.colors["log_equal"])
        self.log_text.tag_configure("value", foreground=self.colors["log_value"])
        self.log_text.tag_configure("data", foreground=self.colors["log_data"])
        self.log_text.tag_configure("path", foreground=self.colors["log_path"])
        self.log_text.tag_configure("count", foreground=self.colors["log_count"])
        self.log_text.tag_configure("normal", foreground=self.colors["log_text"])

    def log_tag_for_line(self, line: str) -> str:
        if "失败" in line or "错误" in line or "未连接" in line:
            return "error"
        if "停止" in line or "未检测到" in line:
            return "warn"
        if "完成" in line or "已打开" in line or "已关闭" in line or "已载入" in line:
            return "ok"
        if "] TX " in line:
            return "tx"
        if "] RX " in line:
            return "rx"
        return "normal"

    def insert_log_line(self, line: str) -> None:
        if line.startswith("[") and "]" in line:
            end = line.index("]") + 1
            self.log_text.insert("end", line[:end], ("time",))
            self.insert_log_body(line[end:].lstrip())
            self.log_text.insert("end", "\n", ("normal",))
        else:
            self.insert_log_body(line)
            self.log_text.insert("end", "\n", ("normal",))

    def insert_log_body(self, body: str) -> None:
        if self.insert_can_rx_log(body):
            return
        if self.insert_tx_log(body):
            return
        if self.insert_loaded_file_log(body):
            return
        self.insert_key_value_segments(body, self.log_tag_for_line(body))

    def insert_can_rx_log(self, body: str) -> bool:
        match = re.fullmatch(r"(RX)\s+(CAN)\s+(STD|EXT)\s+ID=(0x[0-9A-Fa-f]+)\s+DLC=(\d+):\s*(.*)", body)
        if not match:
            return False
        direction, proto, frame_type, can_id, dlc, data = match.groups()
        self.log_text.insert("end", direction, ("rx",))
        self.log_text.insert("end", " ", ("normal",))
        self.log_text.insert("end", proto, ("key",))
        self.log_text.insert("end", " ", ("normal",))
        self.log_text.insert("end", frame_type, ("key",))
        self.log_text.insert("end", " ID", ("key",))
        self.log_text.insert("end", "=", ("equal",))
        self.log_text.insert("end", can_id, ("value",))
        self.log_text.insert("end", " DLC", ("key",))
        self.log_text.insert("end", "=", ("equal",))
        self.log_text.insert("end", dlc, ("value",))
        self.log_text.insert("end", ": ", ("equal",))
        self.log_text.insert("end", data, ("data",))
        return True

    def insert_tx_log(self, body: str) -> bool:
        match = re.fullmatch(r"(TX)\s+(\d+)/(\d+):\s*(.*)", body)
        if not match:
            return False
        direction, sent, total, data = match.groups()
        self.log_text.insert("end", direction, ("tx",))
        self.log_text.insert("end", " ", ("normal",))
        self.log_text.insert("end", sent, ("count",))
        self.log_text.insert("end", "/", ("equal",))
        self.log_text.insert("end", total, ("count",))
        self.log_text.insert("end", ": ", ("equal",))
        tag = "count" if data.endswith(" 字节") else "data"
        self.log_text.insert("end", data, (tag,))
        return True

    def insert_loaded_file_log(self, body: str) -> bool:
        match = re.fullmatch(r"(已载入文件)\s+(.+)，(\d+)\s+(字节)", body)
        if not match:
            return False
        label, path, count, unit = match.groups()
        self.log_text.insert("end", label, ("ok",))
        self.log_text.insert("end", " ", ("normal",))
        self.log_text.insert("end", path, ("path",))
        self.log_text.insert("end", "，", ("equal",))
        self.log_text.insert("end", count, ("count",))
        self.log_text.insert("end", f" {unit}", ("key",))
        return True

    def insert_key_value_segments(self, body: str, default_tag: str) -> None:
        pos = 0
        for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)(=)([^,\s]+)", body):
            if match.start() > pos:
                self.log_text.insert("end", body[pos : match.start()], (default_tag,))
            self.log_text.insert("end", match.group(1), ("key",))
            self.log_text.insert("end", match.group(2), ("equal",))
            self.log_text.insert("end", match.group(3), ("value",))
            pos = match.end()
        if pos < len(body):
            self.log_text.insert("end", body[pos:], (default_tag,))

    def refresh_ports(self) -> None:
        ports = []
        if list_ports is not None:
            ports = [port.device for port in list_ports.comports()]
        self.port_combo.configure(values=ports)
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def refresh_can_channels(self) -> None:
        interface = self.can_interface_var.get().strip()
        channels: list[str] = []

        if can is not None:
            detector = getattr(can, "detect_available_configs", None)
            if detector is not None:
                try:
                    configs = detector(interfaces=[interface])
                except TypeError:
                    try:
                        configs = detector()
                    except Exception as exc:
                        configs = []
                        self.enqueue_log(f"CAN 通道自动检测失败: {exc}")
                except Exception as exc:
                    configs = []
                    self.enqueue_log(f"CAN 通道自动检测失败: {exc}")
                for config in configs:
                    if config.get("interface") not in (None, interface):
                        continue
                    channel = config.get("channel")
                    if channel is not None:
                        channels.append(str(channel))

        if interface == "slcan" and list_ports is not None:
            channels.extend(port.device for port in list_ports.comports())

        channels = list(dict.fromkeys(channel for channel in channels if channel))
        self.can_channel_combo.configure(values=channels)
        if not channels:
            self.can_channel_var.set("")
        elif not self.can_channel_var.get() or self.can_channel_var.get() not in channels:
            self.can_channel_var.set(channels[0])

    def on_can_interface_changed(self, _event: object | None = None) -> None:
        self.refresh_can_channels()

    def on_tcp_mode_changed(self, _event: object | None = None) -> None:
        self.update_tcp_mode_config()

    def update_tcp_mode_config(self) -> None:
        if self.tcp_mode_var.get() == "Server":
            self.tcp_server_frame.tkraise()
        else:
            self.tcp_client_frame.tkraise()

    def on_protocol_changed(self, _event: object | None = None) -> None:
        self.update_protocol_config()
        self.update_connect_button()

    def update_protocol_config(self) -> None:
        if self.protocol_var.get() == "USART":
            self.serial_config_frame.tkraise()
        elif self.protocol_var.get() == "CAN":
            self.can_config_frame.tkraise()
        else:
            self.tcp_config_frame.tkraise()

    def current_connected(self) -> bool:
        if self.protocol_var.get() == "USART":
            return self.serial_client.connected
        if self.protocol_var.get() == "CAN":
            return self.can_client.connected
        return self.tcp_client.connected

    def update_connect_button(self) -> None:
        if self.current_connected():
            self.connect_button.configure(text="断开")
        else:
            self.connect_button.configure(text="连接")
        self.update_config_state()

    def update_config_state(self) -> None:
        connected = self.current_connected()
        state = "disabled" if connected else "normal"
        readonly_state = "disabled" if connected else "readonly"

        self.protocol_combo.configure(state=readonly_state)
        for widget in (
            self.port_combo,
            self.baud_combo,
            self.can_interface_combo,
            self.can_channel_combo,
            self.can_bitrate_combo,
            self.can_sample_point_entry,
            self.can_id_entry,
            self.tcp_remote_host_entry,
            self.tcp_remote_port_entry,
            self.tcp_listen_host_entry,
            self.tcp_listen_port_entry,
        ):
            widget.configure(state=state)
        for widget in (
            self.bytesize_combo,
            self.parity_combo,
            self.stopbits_combo,
            self.tcp_mode_combo,
        ):
            widget.configure(state=readonly_state)
        for widget in (
            self.serial_refresh_button,
            self.can_refresh_button,
            self.can_extended_check,
            self.can_remote_check,
        ):
            widget.configure(state=state)

    def toggle_connection(self) -> None:
        if self.current_connected():
            self.disconnect_current()
        else:
            self.connect_current()

    def connect_current(self) -> None:
        try:
            if self.protocol_var.get() == "USART":
                self.can_client.close()
                self.tcp_client.close()
                self.serial_client.open(
                    self.port_var.get(),
                    int(self.baud_var.get()),
                    int(self.bytesize_var.get()),
                    self.parity_var.get(),
                    float(self.stopbits_var.get()),
                )
            elif self.protocol_var.get() == "CAN":
                self.serial_client.close()
                self.tcp_client.close()
                sample_point = self.can_sample_point_var.get().strip()
                sample_point_value = None if not sample_point else float(sample_point)
                if sample_point_value is not None and not (0 < sample_point_value < 100):
                    raise ValueError("CAN 采样点必须在 0 到 100 之间")
                channel = self.can_channel_var.get().strip()
                if not channel:
                    raise ValueError("未检测到 CAN 通道，请连接设备后点击刷新")
                self.can_client.open(
                    self.can_interface_var.get().strip(),
                    channel,
                    parse_bitrate(self.can_bitrate_var.get()),
                    sample_point_value,
                )
            else:
                self.serial_client.close()
                self.can_client.close()
                if self.tcp_mode_var.get() == "Server":
                    host = self.tcp_listen_host_var.get().strip() or "0.0.0.0"
                    port = self.parse_tcp_port(self.tcp_listen_port_var.get())
                    self.tcp_client.open_server(host, port)
                else:
                    host = self.tcp_remote_host_var.get().strip()
                    if not host:
                        raise ValueError("请输入 TCP 远端 IP 或主机名")
                    port = self.parse_tcp_port(self.tcp_remote_port_var.get())
                    self.tcp_client.open_client(host, port)
        except Exception as exc:
            messagebox.showerror("连接失败", str(exc))
            self.enqueue_log(f"连接失败: {exc}")
        finally:
            self.update_connect_button()

    def disconnect_current(self) -> None:
        if self.protocol_var.get() == "USART":
            self.serial_client.close()
        elif self.protocol_var.get() == "CAN":
            self.can_client.close()
        else:
            self.tcp_client.close()
        self.update_connect_button()

    @staticmethod
    def parse_tcp_port(value: str) -> int:
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError("TCP 端口必须在 1 到 65535 之间")
        return port

    def send_manual(self) -> None:
        try:
            payload = parse_manual_payload(self.manual_text.get("1.0", "end-1c"), self.manual_hex_var.get())
            self.start_sender(payload, log_payload=True, log_every_chunk=True)
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc))

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择发送文件",
            filetypes=[
                ("固件/数据文件", "*.bin *.hex *.txt *.dat"),
                ("BIN 文件", "*.bin"),
                ("Intel HEX 文件", "*.hex"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.file_path_var.set(path)

    def send_file(self) -> None:
        try:
            if not self.file_path_var.get():
                raise ValueError("请先选择文件")
            payload = load_file_payload(self.file_path_var.get())
            self.enqueue_log(f"已载入文件 {self.file_path_var.get()}，{len(payload)} 字节")
            self.start_sender(payload, log_payload=False, log_every_chunk=True)
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc))

    def start_sender(self, payload: bytes, log_payload: bool = False, log_every_chunk: bool = False) -> None:
        if not payload:
            raise ValueError("发送数据为空")
        if self.sender is not None:
            raise RuntimeError("已有发送任务正在运行")
        options = SendOptions(
            chunk_bytes=int(self.chunk_var.get()),
            delay_seconds=parse_delay_seconds(self.delay_var.get(), self.delay_unit_var.get()),
            log_payload=log_payload,
            log_every_chunk=log_every_chunk,
        )
        if options.chunk_bytes <= 0:
            raise ValueError("分块字节数必须大于 0")

        if self.protocol_var.get() == "USART":
            options.fast_chunk_bytes = 4096
            send_chunk = self.serial_client.send
        elif self.protocol_var.get() == "CAN":
            if options.chunk_bytes > 8:
                self.enqueue_log("经典 CAN 单帧最多 8 字节，发送分块已按 8 字节执行")
                options.chunk_bytes = 8
            options.fast_chunk_bytes = max(1, options.chunk_bytes)
            arbitration_id = int(self.can_id_var.get(), 0)
            extended = self.can_extended_var.get()
            remote = self.can_remote_var.get()

            def send_chunk(data: bytes) -> None:
                for offset in range(0, len(data), 8):
                    self.can_client.send_frame(arbitration_id, data[offset : offset + 8], extended, remote)
        else:
            options.fast_chunk_bytes = 4096
            send_chunk = self.tcp_client.send

        self.progress_var.set(0)
        self.progress_text_var.set(f"0 / {len(payload)} 字节")
        self.sender = SenderThread(payload, options, send_chunk, self.enqueue_log, self.enqueue_progress, self.sender_done)
        self.sender.start()

    def stop_sender(self) -> None:
        if self.sender is not None:
            self.sender.stop()

    def sender_done(self) -> None:
        self.sender = None

    def enqueue_log(self, text: str) -> None:
        self.ui_queue.put(("log", f"[{now_text()}] {text}"))

    def enqueue_progress(self, sent: int, total: int) -> None:
        self.ui_queue.put(("progress", (sent, total)))

    def _poll_logs(self) -> None:
        logs_processed = 0
        events_processed = 0
        latest_progress: Optional[tuple[int, int]] = None
        while events_processed < 160:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            events_processed += 1
            if kind == "log":
                self.log_text.configure(state="normal")
                self.insert_log_line(str(payload))
                logs_processed += 1
            elif kind == "progress":
                latest_progress = payload
        if logs_processed:
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        if latest_progress is not None:
            sent, total = latest_progress
            percent = 0 if total <= 0 else sent * 100 / total
            self.progress_var.set(percent)
            self.progress_text_var.set(f"{sent} / {total} 字节")
        self.after(20 if not self.ui_queue.empty() else 50, self._poll_logs)

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def on_close(self) -> None:
        self.save_settings()
        self.stop_sender()
        self.serial_client.close()
        self.can_client.close()
        self.tcp_client.close()
        self.destroy()


def main() -> None:
    app = HostComputerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
