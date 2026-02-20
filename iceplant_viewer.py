import os
import sys
import time
import select
import threading
import shlex
import subprocess
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

import matplotlib as mpl
import matplotlib.text as mtext
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

DEFAULT_HOST = "pi@raspberrypi"
DEFAULT_REMOTE_DIR = "/home/pi/ICE_PLANT/data"
SAMPLE_RATE = 4.0
PACKET_SAMPLES = 4
WINDOW_SECONDS = 120
MAX_SPEC_WINDOW_SECONDS = 300
REFRESH_SECONDS = 0.5
DEFAULT_SPEC_WINDOW_SECONDS = 16


def decode_hr_sample(hi: int, lo: int) -> Optional[float]:
    value = ((hi & 0x07) << 8) | lo
    if value == 0:
        return 0.0
    return value * 0.25


def decode_hr_samples(payload: List[int], start_index: int) -> List[Optional[float]]:
    if len(payload) < start_index + 8:
        return []
    samples = []
    for i in range(start_index, start_index + 8, 2):
        samples.append(decode_hr_sample(payload[i], payload[i + 1]))
    return samples


def decode_hr1_samples(payload: List[int]) -> List[Optional[float]]:
    return decode_hr_samples(payload, 3)


def decode_hr2_samples(payload: List[int]) -> List[Optional[float]]:
    return decode_hr_samples(payload, 11)


def decode_mhr_samples(payload: List[int]) -> List[Optional[float]]:
    return decode_hr_samples(payload, 19)


def parse_payload_line(line: str) -> Optional[Tuple[float, List[int]]]:
    row = line.strip().split(",", 2)
    if len(row) < 3 or row[0] == "timestamp":
        return None
    try:
        ts = float(row[0])
    except ValueError:
        return None
    try:
        payload_len = int(row[1])
    except ValueError:
        payload_len = 0
    parts = row[2].strip().split()
    values: List[int] = []
    for p in parts:
        token = p.strip()
        if token.startswith("0x") or token.startswith("0X"):
            token = token[2:]
        if not token:
            continue
        try:
            values.append(int(token, 16))
        except ValueError:
            return None
    if payload_len > 0:
        if len(values) < payload_len:
            return None
        values = values[:payload_len]
    if not values or values[0] not in (0x43, 0x53):
        return None
    return ts, values


def ssh_cmd(host: str, remote_cmd: str) -> List[str]:
    return ["ssh", host, remote_cmd]


def get_latest_remote_file(host: str, remote_dir: str) -> Optional[str]:
    cmd = (
        f"ls -t {shlex.quote(remote_dir)}/ctg_frames_*.csv "
        f"{shlex.quote(remote_dir)}/ctg_frames_sim_*.csv 2>/dev/null | head -n1"
    )
    proc = subprocess.run(ssh_cmd(host, cmd), capture_output=True, text=True)
    path = proc.stdout.strip()
    return path if path else None


def read_remote_file(host: str, path: str) -> List[str]:
    cmd = f"cat {shlex.quote(path)}"
    proc = subprocess.run(ssh_cmd(host, cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Failed to read remote file.")
    return proc.stdout.splitlines()


class TailWorker(QtCore.QObject):
    line_received = QtCore.Signal(str)
    status = QtCore.Signal(str)
    stopped = QtCore.Signal()
    prefill_done = QtCore.Signal()
    file_selected = QtCore.Signal(str)

    def __init__(
        self,
        host: str,
        remote_dir: str,
        prefill_seconds: int = 0,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._remote_dir = remote_dir
        self._prefill_seconds = max(0, int(prefill_seconds))
        self._proc: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._current_path: Optional[str] = None
        self._switch_requested = False
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()

    @QtCore.Slot()
    def run(self) -> None:
        self._start_poll_thread()
        while not self._stop_requested:
            try:
                remote_path = get_latest_remote_file(self._host, self._remote_dir)
            except Exception as exc:
                self.status.emit(f"Error finding remote file: {exc}")
                self.stopped.emit()
                return

            if not remote_path:
                self.status.emit("No remote CSV found. Start ice_plant.py and try again.")
                self.stopped.emit()
                return

            if remote_path != self._current_path:
                self._current_path = remote_path
                self.file_selected.emit(remote_path)
                self.status.emit(f"Tailing {remote_path}")
                if self._prefill_seconds > 0:
                    try:
                        last_line_proc = subprocess.run(
                            ssh_cmd(self._host, f"tail -n 1 {shlex.quote(remote_path)}"),
                            capture_output=True,
                            text=True,
                        )
                        last_line = last_line_proc.stdout.strip()
                        last_parsed = parse_payload_line(last_line) if last_line else None
                        if last_parsed is not None:
                            latest_ts, _ = last_parsed
                            cutoff = latest_ts - float(self._prefill_seconds)
                            awk_cmd = (
                                f"awk -F, 'NR>1 && $1+0>={cutoff:.6f} {{print}}' "
                                f"{shlex.quote(remote_path)}"
                            )
                            prefill_proc = subprocess.run(
                                ssh_cmd(self._host, awk_cmd),
                                capture_output=True,
                                text=True,
                            )
                            for line in prefill_proc.stdout.splitlines():
                                if self._stop_requested:
                                    break
                                self.line_received.emit(line)
                    except Exception as exc:
                        self.status.emit(f"Prefill failed: {exc}")
                    finally:
                        self.prefill_done.emit()
                else:
                    self.prefill_done.emit()

            cmd = f"tail -F -n 0 {shlex.quote(remote_path)}"
            try:
                self._proc = subprocess.Popen(ssh_cmd(self._host, cmd), stdout=subprocess.PIPE, text=True)
            except Exception as exc:
                self.status.emit(f"SSH failed: {exc}")
                self.stopped.emit()
                break

            if self._proc.stdout is None:
                self.status.emit("Failed to open SSH stream.")
                self.stopped.emit()
                break

            while not self._stop_requested:
                if self._proc.stdout is None:
                    break
                rlist, _, _ = select.select([self._proc.stdout], [], [], 1.0)
                if rlist:
                    line = self._proc.stdout.readline()
                    if not line:
                        break
                    self.line_received.emit(line)
                if self._switch_requested:
                    self._switch_requested = False
                    self._cleanup()
                    break

            self._cleanup()

        self._stop_poll_thread()
        self.stopped.emit()

    def stop(self) -> None:
        self._stop_requested = True
        self._stop_poll_thread()
        self._cleanup()

    def _cleanup(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _start_poll_thread(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop_poll_thread(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_stop.set()
            self._poll_thread.join(timeout=2.0)
        self._poll_thread = None

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            try:
                latest = get_latest_remote_file(self._host, self._remote_dir)
            except Exception:
                latest = None
            if latest and latest != self._current_path:
                self._switch_requested = True
            self._poll_stop.wait(1.0)


class StaticWorker(QtCore.QObject):
    data_ready = QtCore.Signal(list)
    status = QtCore.Signal(str)
    stopped = QtCore.Signal()
    file_selected = QtCore.Signal(str)

    def __init__(self, host: str, remote_dir: str, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._remote_dir = remote_dir

    @QtCore.Slot()
    def run(self) -> None:
        try:
            remote_path = get_latest_remote_file(self._host, self._remote_dir)
        except Exception as exc:
            self.status.emit(f"Error finding remote file: {exc}")
            self.stopped.emit()
            return

        if not remote_path:
            self.status.emit("No remote CSV found. Start ice_plant.py and try again.")
            self.stopped.emit()
            return

        self.file_selected.emit(remote_path)
        self.status.emit(f"Loading {remote_path}")
        try:
            lines = read_remote_file(self._host, remote_path)
        except Exception as exc:
            self.status.emit(f"Read failed: {exc}")
            self.stopped.emit()
            return

        self.data_ready.emit(lines)
        self.stopped.emit()


class DownloadWorker(QtCore.QObject):
    status = QtCore.Signal(str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, host: str, remote_dir: str, dest_dir: str, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._remote_dir = remote_dir
        self._dest_dir = dest_dir

    @QtCore.Slot()
    def run(self) -> None:
        list_cmd = f"ls -1 {shlex.quote(self._remote_dir)}/ctg_frames_*.csv 2>/dev/null"
        proc = subprocess.run(ssh_cmd(self._host, list_cmd), capture_output=True, text=True)
        if proc.returncode != 0 or not proc.stdout.strip():
            self.status.emit("No remote CSV files found.")
            self.finished.emit()
            return

        self.status.emit("Downloading remote CSV files...")
        tar_cmd = f"cd {shlex.quote(self._remote_dir)} && tar -czf - ctg_frames_*.csv"
        ssh_proc = subprocess.Popen(
            ssh_cmd(self._host, tar_cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if ssh_proc.stdout is None:
            self.status.emit("Failed to start SSH download.")
            self.finished.emit()
            return

        tar_proc = subprocess.Popen(
            ["tar", "-xzf", "-", "-C", self._dest_dir],
            stdin=ssh_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ssh_proc.stdout.close()

        ssh_err = ssh_proc.stderr.read().decode("utf-8", errors="replace") if ssh_proc.stderr else ""
        _, tar_err = tar_proc.communicate()
        ssh_proc.wait()

        if ssh_proc.returncode != 0:
            msg = ssh_err.strip() or "SSH download failed."
            self.status.emit("Download failed. See details.")
            self.error.emit(msg)
            self.finished.emit()
            return

        if tar_proc.returncode != 0:
            msg = (tar_err.decode("utf-8", errors="replace") if tar_err else "").strip()
            self.status.emit("Download failed. See details.")
            self.error.emit(msg or "Failed to extract downloaded files.")
            self.finished.emit()
            return

        self.status.emit(f"Downloaded CSV files to {self._dest_dir}")
        self.finished.emit()


class FileCheckWorker(QtCore.QObject):
    result = QtCore.Signal(object)

    def __init__(self, host: str, remote_dir: str, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._remote_dir = remote_dir

    @QtCore.Slot()
    def run(self) -> None:
        try:
            latest = get_latest_remote_file(self._host, self._remote_dir)
        except Exception:
            latest = None
        self.result.emit(latest)


class PlotWidget(QtWidgets.QWidget):
    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(self._figure)
        self.ax = self._figure.add_subplot(111)
        self.ax.set_title(title)
        self.ax.set_xlabel("time")
        self.ax.set_ylabel("bpm")
        self.ax.xaxis_date()
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax.grid(True, alpha=0.3)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)


class SpectrogramWidget(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(self._figure)
        self.ax = self._figure.add_subplot(111)
        self.ax.set_title("Spectrogram")
        self.ax.set_xlabel("Hz")
        self.ax.set_ylabel("time")
        self.ax.yaxis_date()
        self.ax.yaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.yaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)


class MainWindow(QtWidgets.QMainWindow):
    def __getattr__(self, name: str):
        if name == "_update_visibility":
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def _update_visibility_wrapper(self, _checked: bool = False) -> None:
        self._update_visibility()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ICE PLANT Viewer")
        if not hasattr(self, "_update_visibility"):
            self._update_visibility = lambda: None

        self._settings = QtCore.QSettings("ICE_PLANT", "viewer")
        self._default_rc = mpl.rcParams.copy()
        self._follow_theme = False
        self._theme_override: Optional[str] = "dark"
        self._theme_mode = self._settings.value("theme_mode", "dark")

        self._host_input = QtWidgets.QLineEdit()
        self._host_input.setPlaceholderText("pi@raspberrypi or 192.168.1.10")
        self._host_input.setText(self._settings.value("recent_host", DEFAULT_HOST))

        self._connect_button = QtWidgets.QPushButton("Connect")
        self._connect_button.clicked.connect(self._toggle_connection)

        self._load_button = QtWidgets.QPushButton("Load Latest")
        self._load_button.clicked.connect(self._load_latest)

        self._status_label = QtWidgets.QLabel("Disconnected")

        self._build_menu()

        spec_window = self._settings.value("spec_window_seconds", None)
        if spec_window is None:
            legacy_nfft = int(self._settings.value("spec_nfft", DEFAULT_SPEC_WINDOW_SECONDS * SAMPLE_RATE))
            spec_window = int(round(legacy_nfft / SAMPLE_RATE))
        else:
            spec_window = int(spec_window)
        if spec_window not in (16, 32, 60, 180, 300):
            spec_window = DEFAULT_SPEC_WINDOW_SECONDS
        self._spec_window_seconds = spec_window

        self._spec_freq_range = self._settings.value("spec_freq_range", "0-2.0")
        if self._spec_freq_range not in ("0-0.5", "0-1.0", "0-2.0"):
            self._spec_freq_range = "0-2.0"
        self._spec_nfft = int(self._spec_window_seconds * SAMPLE_RATE)
        self._spec_hop = max(4, self._spec_nfft // 8)

        # Ensure we never crash if update_visibility gets into a bad state.
        self._update_visibility = getattr(self, "_update_visibility", lambda: None)

        self._hr1_toggle = QtWidgets.QCheckBox("HR1")
        self._hr2_toggle = QtWidgets.QCheckBox("HR2")
        self._mhr_toggle = QtWidgets.QCheckBox("MHR")
        self._hr1_toggle.setChecked(self._settings.value("show_hr1", True, type=bool))
        self._hr2_toggle.setChecked(self._settings.value("show_hr2", True, type=bool))
        self._mhr_toggle.setChecked(self._settings.value("show_mhr", True, type=bool))
        # Use lambdas so the attribute lookup happens at emit time.
        self._hr1_toggle.toggled.connect(lambda _checked=False: self._update_visibility_wrapper())
        self._hr2_toggle.toggled.connect(lambda _checked=False: self._update_visibility_wrapper())
        self._mhr_toggle.toggled.connect(lambda _checked=False: self._update_visibility_wrapper())

        self._tabs = QtWidgets.QTabWidget()
        self._time_plot = PlotWidget("HR (bpm)")
        self._tabs.addTab(self._time_plot, "Time Domain")

        spec_tab = QtWidgets.QWidget()
        self._spec_layout = QtWidgets.QGridLayout(spec_tab)
        self._spec_layout.setContentsMargins(0, 0, 0, 0)
        self._spec_layout.setSpacing(8)
        self._tabs.addTab(spec_tab, "Spectrogram")

        top_controls = QtWidgets.QHBoxLayout()
        top_controls.addWidget(QtWidgets.QLabel("Host:"))
        top_controls.addWidget(self._host_input, 1)
        top_controls.addWidget(self._connect_button)
        top_controls.addWidget(self._load_button)
        top_controls.addWidget(self._status_label, 2)

        toggles = QtWidgets.QHBoxLayout()
        toggles.addWidget(QtWidgets.QLabel("Signals:"))
        toggles.addWidget(self._hr1_toggle)
        toggles.addWidget(self._hr2_toggle)
        toggles.addWidget(self._mhr_toggle)
        self._spec_nfft_combo = QtWidgets.QComboBox()
        self._spec_nfft_combo.addItems(["16", "32", "60", "180", "300"])
        self._spec_nfft_combo.setCurrentText(str(self._spec_window_seconds))
        self._spec_nfft_combo.currentTextChanged.connect(self._on_spec_window_changed)

        self._spec_freq_combo = QtWidgets.QComboBox()
        self._spec_freq_combo.addItems(["0-0.5", "0-1.0", "0-2.0"])
        self._spec_freq_combo.setCurrentText(self._spec_freq_range)
        self._spec_freq_combo.currentTextChanged.connect(self._on_spec_freq_changed)
        toggles.addSpacing(12)
        toggles.addWidget(QtWidgets.QLabel("Spec Window (s):"))
        toggles.addWidget(self._spec_nfft_combo)
        toggles.addSpacing(12)
        toggles.addWidget(QtWidgets.QLabel("Freq Range (Hz):"))
        toggles.addWidget(self._spec_freq_combo)
        toggles.addStretch(1)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.addLayout(top_controls)
        layout.addLayout(toggles)
        layout.addWidget(self._tabs)

        self.setCentralWidget(container)

        self._worker: Optional[TailWorker] = None
        self._thread: Optional[QtCore.QThread] = None
        self._static_worker: Optional[StaticWorker] = None
        self._static_thread: Optional[QtCore.QThread] = None
        self._download_worker: Optional[DownloadWorker] = None
        self._download_thread: Optional[QtCore.QThread] = None
        self._connected = False
        self._static_loading = False
        self._static_view = False
        self._suppress_spec_rows = False
        self._current_remote_file: Optional[str] = None
        self._last_packet_ts: Optional[float] = None

        self._signal_map = {
            "hr1": decode_hr1_samples,
            "hr2": decode_hr2_samples,
            "mhr": decode_mhr_samples,
        }

        self._times: Dict[str, Deque[float]] = {
            "hr1": deque(),
            "hr2": deque(),
            "mhr": deque(),
        }
        self._values: Dict[str, Deque[float]] = {
            "hr1": deque(),
            "hr2": deque(),
            "mhr": deque(),
        }

        self._spec_plots = {
            "hr1": SpectrogramWidget(),
            "hr2": SpectrogramWidget(),
            "mhr": SpectrogramWidget(),
        }
        self._spec_plots["hr1"].ax.set_title("HR1 Spectrogram")
        self._spec_plots["hr2"].ax.set_title("HR2 Spectrogram")
        self._spec_plots["mhr"].ax.set_title("MHR Spectrogram")
        self._simulated_data = False

        for sig in ("hr1", "hr2", "mhr"):
            self._spec_plots[sig].setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
            )
            self._spec_layout.addWidget(self._spec_plots[sig], 0, 0)

        self._spec_bins = self._spec_nfft // 2 + 1
        self._spec_norm = mcolors.Normalize(vmin=0.0, vmax=1.0)
        self._spec_low_color = "#0b1d3a"
        self._spec_cmap = mcolors.LinearSegmentedColormap.from_list(
            "blue_green",
            [self._spec_low_color, "#0b3d91", "#00ff6a"],
        )
        self._spec_cmap.set_bad(self._spec_low_color)

        self._lines = {
            "hr1": self._time_plot.ax.plot([], [], lw=1, color="tab:blue", label="HR1")[0],
            "hr2": self._time_plot.ax.plot([], [], lw=1, color="tab:orange", label="HR2")[0],
            "mhr": self._time_plot.ax.plot([], [], lw=1, color="tab:green", label="MHR")[0],
        }
        self._time_plot.ax.legend(loc="upper right")

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(REFRESH_SECONDS * 1000))
        self._timer.timeout.connect(self._refresh_plots)
        self._timer.start()

        self._configure_spectrogram_storage(self._window_spec_cols())
        self._set_theme_mode(self._theme_mode)
        self._update_visibility()
        QtCore.QTimer.singleShot(0, self._auto_connect_if_enabled)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[name-defined]
        self._disconnect()
        self._stop_static_worker()
        self._stop_download_worker()
        super().closeEvent(event)

    def _toggle_connection(self) -> None:
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        host = self._host_input.text().strip() or DEFAULT_HOST
        self._settings.setValue("recent_host", host)
        self._status_label.setText("Connecting...")
        self._connect_button.setEnabled(False)
        self._connect_button.setText("Connecting...")
        self._load_button.setEnabled(False)
        if self._static_view:
            self._reset_live_buffers()
        self._static_view = False

        prefill_seconds = max(MAX_SPEC_WINDOW_SECONDS, WINDOW_SECONDS)
        self._worker = TailWorker(host, DEFAULT_REMOTE_DIR, prefill_seconds=prefill_seconds)
        self._thread = QtCore.QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.line_received.connect(self._on_line)
        self._worker.prefill_done.connect(self._on_prefill_done)
        self._worker.status.connect(self._status_label.setText)
        self._worker.file_selected.connect(self._on_file_selected)
        self._worker.stopped.connect(self._on_worker_stopped)
        self._thread.start()

        self._connected = True
        self._connect_button.setText("Disconnect")
        self._connect_button.setEnabled(True)
        self._load_button.setEnabled(True)
        self._suppress_spec_rows = True

    def _disconnect(self) -> None:
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._worker = None
        self._thread = None
        self._connected = False
        self._connect_button.setText("Connect")
        self._status_label.setText("Disconnected")
        self._load_button.setEnabled(True)

    def _on_worker_stopped(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(1000)
        self._worker = None
        self._thread = None
        self._connected = False
        self._connect_button.setText("Connect")
        self._load_button.setEnabled(True)
        self._suppress_spec_rows = False

    def _on_prefill_done(self) -> None:
        self._suppress_spec_rows = False

    def _load_latest(self) -> None:
        if self._connected:
            self._disconnect()
        if self._static_thread:
            return

        host = self._host_input.text().strip() or DEFAULT_HOST
        self._settings.setValue("recent_host", host)
        self._status_label.setText("Loading latest file...")
        self._load_button.setEnabled(False)
        self._connect_button.setEnabled(False)
        self._static_view = True

        self._static_worker = StaticWorker(host, DEFAULT_REMOTE_DIR)
        self._static_thread = QtCore.QThread()
        self._static_worker.moveToThread(self._static_thread)

        self._static_thread.started.connect(self._static_worker.run)
        self._static_worker.status.connect(self._status_label.setText)
        self._static_worker.file_selected.connect(self._on_file_selected)
        self._static_worker.data_ready.connect(self._on_static_data)
        self._static_worker.stopped.connect(self._on_static_stopped)
        self._static_thread.start()

    def _stop_static_worker(self) -> None:
        if self._static_thread:
            self._static_thread.quit()
            self._static_thread.wait(1000)
        self._static_worker = None
        self._static_thread = None

    def _on_static_stopped(self) -> None:
        self._stop_static_worker()
        self._load_button.setEnabled(True)
        self._connect_button.setEnabled(True)
        if self._static_view:
            self._connect_button.setText("Go Live")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        download_action = QtGui.QAction("Download All Remote CSVs...", self)
        download_action.triggered.connect(self._download_all_files)
        file_menu.addAction(download_action)

        file_menu.addSeparator()
        self._autoconnect_action = QtGui.QAction("Auto-connect on Launch", self)
        self._autoconnect_action.setCheckable(True)
        self._autoconnect_action.setChecked(self._settings.value("auto_connect", True, type=bool))
        self._autoconnect_action.toggled.connect(self._on_autoconnect_toggled)
        file_menu.addAction(self._autoconnect_action)

        view_menu = self.menuBar().addMenu("View")
        theme_menu = view_menu.addMenu("Theme")

        self._theme_group = QtGui.QActionGroup(self)
        self._theme_group.setExclusive(True)

        self._theme_light_action = QtGui.QAction("Light", self)
        self._theme_light_action.setCheckable(True)
        self._theme_group.addAction(self._theme_light_action)

        self._theme_dark_action = QtGui.QAction("Dark", self)
        self._theme_dark_action.setCheckable(True)
        self._theme_group.addAction(self._theme_dark_action)

        theme_menu.addAction(self._theme_light_action)
        theme_menu.addAction(self._theme_dark_action)

        self._theme_group.triggered.connect(self._on_theme_selected)

    def _on_theme_selected(self, action: QtGui.QAction) -> None:
        if action is self._theme_light_action:
            self._set_theme_mode("light")
        else:
            self._set_theme_mode("dark")

    def _on_autoconnect_toggled(self, checked: bool) -> None:
        self._settings.setValue("auto_connect", checked)

    def _auto_connect_if_enabled(self) -> None:
        if self._connected or self._static_view:
            return
        if self._settings.value("auto_connect", True, type=bool):
            self._connect()

    # File switching is handled inside TailWorker now.

    def _on_spec_window_changed(self, text: str) -> None:
        try:
            window_seconds = int(text)
        except ValueError:
            return
        if window_seconds not in (16, 32, 60, 180, 300):
            return
        if window_seconds == self._spec_window_seconds:
            return
        self._spec_window_seconds = window_seconds
        self._spec_nfft = int(self._spec_window_seconds * SAMPLE_RATE)
        self._spec_hop = max(4, self._spec_nfft // 8)
        self._spec_bins = self._spec_nfft // 2 + 1
        self._settings.setValue("spec_window_seconds", self._spec_window_seconds)
        self._configure_spectrogram_storage(self._window_spec_cols())
        self._refresh_spectrogram()

    def _on_spec_freq_changed(self, text: str) -> None:
        if text not in ("0-0.5", "0-1.0", "0-2.0"):
            return
        if text == self._spec_freq_range:
            return
        self._spec_freq_range = text
        self._settings.setValue("spec_freq_range", self._spec_freq_range)
        self._refresh_spectrogram()

    def _set_theme_mode(self, mode: str) -> None:
        mode = mode if mode in {"light", "dark"} else "dark"
        self._theme_mode = mode
        self._settings.setValue("theme_mode", mode)

        if mode == "light":
            self._follow_theme = False
            self._theme_override = "light"
            self._theme_light_action.setChecked(True)
        else:
            self._follow_theme = False
            self._theme_override = "dark"
            self._theme_dark_action.setChecked(True)

        self._apply_theme()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.ApplicationPaletteChange:
            if self._follow_theme:
                self._apply_theme()
        super().changeEvent(event)

    def _apply_theme(self) -> None:
        if self._theme_override == "dark":
            window_color = "#2b2b2b"
            base_color = "#1e1e1e"
            text_color = "#e6e6e6"
            grid_color = "#5a5a5a"
            edge_color = "#8a8a8a"
        else:
            window_color = "#f6f6f6"
            base_color = "#ffffff"
            text_color = "#111111"
            grid_color = "#c8c8c8"
            edge_color = "#999999"

        mpl.rcParams.update({
            "figure.facecolor": window_color,
            "axes.facecolor": base_color,
            "axes.edgecolor": edge_color,
            "axes.labelcolor": text_color,
            "axes.titlecolor": text_color,
            "xtick.color": text_color,
            "ytick.color": text_color,
            "text.color": text_color,
            "grid.color": grid_color,
            "legend.frameon": True,
            "legend.facecolor": base_color,
            "legend.edgecolor": edge_color,
        })
        self._apply_axes_theme(self._time_plot.ax)
        for widget in self._spec_plots.values():
            self._apply_axes_theme(widget.ax)

        self._time_plot.canvas.draw_idle()
        for widget in self._spec_plots.values():
            widget.canvas.draw_idle()


    def _apply_axes_theme(self, ax: mpl.axes.Axes) -> None:  # type: ignore[name-defined]
        ax.set_facecolor(mpl.rcParams["axes.facecolor"])
        ax.figure.set_facecolor(mpl.rcParams["figure.facecolor"])
        for spine in ax.spines.values():
            spine.set_color(mpl.rcParams["axes.edgecolor"])
        ax.xaxis.label.set_color(mpl.rcParams["axes.labelcolor"])
        ax.yaxis.label.set_color(mpl.rcParams["axes.labelcolor"])
        ax.tick_params(colors=mpl.rcParams["xtick.color"])
        ax.title.set_color(mpl.rcParams["axes.titlecolor"])
        text_color = self._resolved_text_color()
        for text in ax.findobj(mtext.Text):
            if text.get_color() == "auto":
                text.set_color(text_color)
        for text in ax.texts:
            if text.get_color() == "auto":
                text.set_color(text_color)
        if ax.get_legend():
            leg = ax.get_legend()
            face = mpl.rcParams["legend.facecolor"]
            if face == "inherit":
                face = mpl.rcParams["axes.facecolor"]
            edge = mpl.rcParams["legend.edgecolor"]
            if edge == "inherit":
                edge = mpl.rcParams["axes.edgecolor"]
            leg.get_frame().set_facecolor(face)
            leg.get_frame().set_edgecolor(edge)
            for text in leg.get_texts():
                text.set_color(text_color)

    def _resolved_text_color(self) -> str:
        text_color = mpl.rcParams.get("text.color", "black")
        if text_color == "auto":
            return str(mpl.rcParams.get("axes.labelcolor", "black"))
        return str(text_color)

    def _download_all_files(self) -> None:
        if self._download_thread:
            return
        dest = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if not dest:
            return
        host = self._host_input.text().strip() or DEFAULT_HOST
        self._settings.setValue("recent_host", host)

        self._status_label.setText("Preparing download...")
        self._download_worker = DownloadWorker(host, DEFAULT_REMOTE_DIR, dest)
        self._download_thread = QtCore.QThread()
        self._download_worker.moveToThread(self._download_thread)

        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.status.connect(self._status_label.setText)
        self._download_worker.error.connect(self._show_error)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_thread.start()

    def _show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Download Error", message)

    def _on_download_finished(self) -> None:
        self._stop_download_worker()

    def _on_file_selected(self, path: str) -> None:
        self._current_remote_file = path
        name = os.path.basename(path).lower()
        is_sim = "_sim" in name or "sim_" in name or name.endswith("sim.csv")
        if is_sim:
            self._status_label.setStyleSheet("color: #ff8c00;")
        else:
            self._status_label.setStyleSheet("")
        if is_sim != self._simulated_data:
            self._simulated_data = is_sim
            self._apply_plot_titles()

    def _apply_plot_titles(self) -> None:
        if self._simulated_data:
            self._time_plot.ax.set_title("Simulated HR (bpm)")
            self._spec_plots["hr1"].ax.set_title("Simulated HR1 Spectrogram")
            self._spec_plots["hr2"].ax.set_title("Simulated HR2 Spectrogram")
            self._spec_plots["mhr"].ax.set_title("Simulated MHR Spectrogram")
        else:
            self._time_plot.ax.set_title("HR (bpm)")
            self._spec_plots["hr1"].ax.set_title("HR1 Spectrogram")
            self._spec_plots["hr2"].ax.set_title("HR2 Spectrogram")
            self._spec_plots["mhr"].ax.set_title("MHR Spectrogram")
        self._time_plot.canvas.draw_idle()
        for widget in self._spec_plots.values():
            widget.canvas.draw_idle()

    def _stop_download_worker(self) -> None:
        if self._download_thread:
            self._download_thread.quit()
            self._download_thread.wait(1000)
        self._download_worker = None
        self._download_thread = None

    def _on_static_data(self, lines: List[str]) -> None:
        self._clear_buffers()
        self._static_loading = True
        for line in lines:
            self._on_line(line)
        self._static_loading = False
        total_samples = max((len(self._values[s]) for s in self._signal_map), default=0)
        if total_samples > 0:
            cols = max(1, int(np.ceil(total_samples / PACKET_SAMPLES)))
            self._configure_spectrogram_storage(max(cols, 10))
            self._rebuild_spectrogram_all()
        self._refresh_plots()
        self._status_label.setText("Loaded latest file")
        self._connect_button.setEnabled(True)
        self._connect_button.setText("Go Live")

    def _on_line(self, line: str) -> None:
        parsed = parse_payload_line(line)
        if parsed is None:
            return
        ts, payload = parsed
        if (
            self._last_packet_ts is not None
            and not self._static_loading
            and not self._suppress_spec_rows
        ):
            gap = ts - self._last_packet_ts
            if gap >= 1.5:
                missing = int(gap) - 1
                max_fill = max(MAX_SPEC_WINDOW_SECONDS, WINDOW_SECONDS)
                if missing > max_fill:
                    missing = max_fill
                for step in range(1, missing + 1):
                    fill_ts = self._last_packet_ts + step
                    for sig in self._signal_map:
                        self._append_spec_blank(sig, fill_ts)
        for sig, decoder in self._signal_map.items():
            samples = decoder(payload)
            if not samples:
                continue
            sample_times: List[float] = []
            for i, bpm in enumerate(samples):
                t = ts - (3 - i) * 0.25
                self._times[sig].append(t)
                sample_times.append(t)
                if bpm is None:
                    bpm = 0.0
                self._values[sig].append(bpm)
            if not self._static_loading and not self._suppress_spec_rows:
                self._process_spectrogram(sig, samples, sample_times)
        self._last_packet_ts = ts

        latest_time = max((times[-1] for times in self._times.values() if times), default=None)
        if latest_time is None:
            return
        if self._static_loading:
            return
        history_seconds = max(WINDOW_SECONDS, MAX_SPEC_WINDOW_SECONDS)
        for sig in self._signal_map:
            while self._times[sig] and (latest_time - self._times[sig][0]) > history_seconds:
                self._times[sig].popleft()
                self._values[sig].popleft()

    def _clear_buffers(self) -> None:
        for sig in self._signal_map:
            self._times[sig].clear()
            self._values[sig].clear()
            # Spectrogram data is stored in a ring buffer.
        self._last_packet_ts = None

    def _reset_live_buffers(self) -> None:
        self._clear_buffers()
        for sig, line in self._lines.items():
            line.set_data([], [])
        self._configure_spectrogram_storage(self._window_spec_cols())
        self._time_plot.canvas.draw_idle()
        self._refresh_spectrogram()

    def _process_spectrogram(self, sig: str, samples: List[float], times: List[float]) -> None:
        if not samples or not times:
            return
        nfft = self._spec_nfft
        values = list(self._values[sig])
        if len(values) < nfft:
            return
        seg = np.asarray(values[-nfft:], dtype=float)
        window = np.hanning(nfft)
        seg = seg - np.mean(seg)
        fft_vals = np.fft.rfft(seg * window)
        power = np.abs(fft_vals) ** 2
        self._append_spec_column(sig, power, times[-1])

    def _rebuild_spectrogram(self, sig: str) -> None:
        self._spec_col_index[sig] = 0
        self._spec_filled[sig] = 0
        self._spec_next_index[sig] = 0
        self._spec_data[sig][:] = np.nan
        self._spec_times[sig][:] = 0.0

        values = list(self._values[sig])
        times = list(self._times[sig])
        if not values or not times:
            return
        for start in range(0, len(values), PACKET_SAMPLES):
            chunk = values[start : start + PACKET_SAMPLES]
            chunk_times = times[start : start + PACKET_SAMPLES]
            if not chunk or not chunk_times:
                continue
            self._process_spectrogram(sig, chunk, chunk_times)

    def _rebuild_spectrogram_all(self) -> None:
        for sig in self._signal_map:
            self._rebuild_spectrogram(sig)

    def _compute_spectrogram(self, series: np.ndarray, times: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = len(series)
        nfft = self._spec_nfft
        hop = self._spec_hop
        freqs = np.fft.rfftfreq(nfft, d=1.0 / SAMPLE_RATE)
        window = np.hanning(nfft)

        if n == 0:
            return np.array([]), np.array([]), np.array([[]])

        cols = []
        tcols = []

        if n < nfft:
            padded = np.zeros(nfft, dtype=float)
            padded[:n] = series
            fft_vals = np.fft.rfft(padded * window)
            cols.append(np.abs(fft_vals) ** 2)
            tcols.append(times[-1])
        else:
            for start in range(0, n - nfft + 1, hop):
                segment = series[start : start + nfft]
                fft_vals = np.fft.rfft(segment * window)
                cols.append(np.abs(fft_vals) ** 2)
                tcols.append(times[start + nfft - 1])

        if not cols:
            return np.array([]), np.array([]), np.array([[]])
        Sxx = np.stack(cols, axis=1)  # freq x time
        return freqs, np.array(tcols), Sxx

    def _active_signals(self) -> List[str]:
        active = []
        if self._hr1_toggle.isChecked():
            active.append("hr1")
        if self._hr2_toggle.isChecked():
            active.append("hr2")
        if self._mhr_toggle.isChecked():
            active.append("mhr")
        return active

    def _update_visibility(self) -> None:
        active = set(self._active_signals())
        for sig, line in self._lines.items():
            line.set_visible(sig in active)
        for sig, widget in self._spec_plots.items():
            widget.setVisible(sig in active)
        self._reflow_spectrogram_layout(active)
        self._adjust_spec_margins(len(active))
        self._settings.setValue("show_hr1", self._hr1_toggle.isChecked())
        self._settings.setValue("show_hr2", self._hr2_toggle.isChecked())
        self._settings.setValue("show_mhr", self._mhr_toggle.isChecked())
        self._time_plot.canvas.draw_idle()
        self._refresh_spectrogram()

    def _refresh_plots(self) -> None:
        active = self._active_signals()
        if not active:
            self._time_plot.canvas.draw_idle()
            return

        base_time = None
        latest_time = None
        for sig in active:
            if self._times[sig]:
                if base_time is None or self._times[sig][0] < base_time:
                    base_time = self._times[sig][0]
                if latest_time is None or self._times[sig][-1] > latest_time:
                    latest_time = self._times[sig][-1]

        if base_time is None or latest_time is None:
            return

        for sig in active:
            if not self._times[sig]:
                continue
            x = mdates.date2num([datetime.fromtimestamp(t) for t in self._times[sig]])
            y = np.array(self._values[sig])
            self._lines[sig].set_data(x[: len(y)], y)

        if self._static_view:
            x_min = mdates.date2num(datetime.fromtimestamp(base_time))
            x_max = mdates.date2num(datetime.fromtimestamp(latest_time))
        else:
            x_min = mdates.date2num(datetime.fromtimestamp(latest_time - WINDOW_SECONDS))
            x_max = mdates.date2num(datetime.fromtimestamp(latest_time))
        if x_max <= x_min:
            x_max = x_min + 1 / (24 * 60 * 60)
        self._time_plot.ax.set_xlim(x_min, x_max)

        all_vals = np.concatenate([np.array(self._values[s]) for s in active if len(self._values[s])])
        if len(all_vals):
            self._time_plot.ax.set_ylim(max(0, all_vals.min() - 5), all_vals.max() + 5)

        self._time_plot.canvas.draw_idle()
        self._refresh_spectrogram()

    def _spec_title(self, sig: str) -> str:
        base = f"{sig.upper()} Spectrogram"
        if self._simulated_data:
            return f"Simulated {base}"
        return base

    def _refresh_spectrogram(self) -> None:
        active = self._active_signals()
        if not active:
            for sig, widget in self._spec_plots.items():
                widget.ax.clear()
                self._setup_spec_axis(widget.ax, self._spec_title(sig))
                widget.ax.text(
                    0.5, 0.5, "Enable a signal", ha="center", va="center",
                    color=self._resolved_text_color(),
                )
                widget.canvas.draw_idle()
            return

        for sig in active:
            widget = self._spec_plots[sig]
            if len(self._values[sig]) == 0 or self._spec_filled.get(sig, 0) == 0:
                widget.ax.clear()
                self._setup_spec_axis(widget.ax, self._spec_title(sig))
                widget.ax.text(
                    0.5, 0.5, "Waiting for samples...", ha="center", va="center",
                    color=self._resolved_text_color(),
                )
                widget.canvas.draw_idle()
                continue

            data, times = self._ordered_spec_data(sig)
            if data.size == 0 or times.size == 0:
                continue

            freqs = np.fft.rfftfreq(self._spec_nfft, d=1.0 / SAMPLE_RATE)
            spec_power = 10 * np.log10(data + 1e-12)
            # Normalize each time slice so relative spectral shape is visible.
            row_max = np.nanmax(spec_power, axis=1, keepdims=True)
            spec_power = spec_power - row_max
            newest_first = spec_power[::-1, :]

            if self._spec_freq_range == "0-0.5":
                f_max = 0.5
            elif self._spec_freq_range == "0-1.0":
                f_max = 1.0
            else:
                f_max = 2.0
            freq_mask = freqs <= f_max
            freqs = freqs[freq_mask]
            newest_first = newest_first[:, freq_mask]

            if not self._static_view:
                rows = self._spec_cols
                spec_display = np.full((rows, newest_first.shape[1]), np.nan, dtype=float)
                count = min(rows, newest_first.shape[0])
                spec_display[:count, :] = newest_first[:count, :]
                latest = float(times[-1])
                latest = float(int(round(latest)))
                t_max = mdates.date2num(datetime.fromtimestamp(latest))
                t_min = mdates.date2num(datetime.fromtimestamp(latest - WINDOW_SECONDS))
            else:
                spec_display = newest_first
                t_min = mdates.date2num(datetime.fromtimestamp(float(times[0])))
                t_max = mdates.date2num(datetime.fromtimestamp(float(times[-1])))
                if t_max <= t_min:
                    t_max = t_min + 1 / (24 * 60 * 60)

            extent = [0, freqs[-1], t_min, t_max]
            widget.ax.clear()
            self._setup_spec_axis(widget.ax, self._spec_title(sig))
            finite = spec_display[np.isfinite(spec_display)]
            if finite.size == 0:
                spec_display = np.zeros_like(spec_display)
                finite = spec_display.ravel()
            vmax = float(np.percentile(finite, 99))
            vmin = vmax - 60.0
            if not np.isfinite(vmax):
                vmax = 0.0
                vmin = -60.0
            norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
            widget.ax.imshow(
                np.ma.masked_invalid(spec_display),
                origin="upper",
                aspect="auto",
                cmap=self._spec_cmap,
                norm=norm,
                extent=extent,
                interpolation="nearest",
            )
            widget.canvas.draw_idle()

    def _reflow_spectrogram_layout(self, active: Optional[set] = None) -> None:
        if active is None:
            active = set(self._active_signals())
        while self._spec_layout.count():
            item = self._spec_layout.takeAt(0)
            if item is None:
                break
        for i in range(3):
            self._spec_layout.setColumnStretch(i, 0)
        col = 0
        for sig in ("hr1", "hr2", "mhr"):
            widget = self._spec_plots[sig]
            if sig in active:
                self._spec_layout.addWidget(widget, 0, col)
                self._spec_layout.setColumnStretch(col, 1)
                col += 1
        self._spec_layout.setRowStretch(0, 1)
        self._spec_layout.invalidate()
        self._spec_layout.activate()
        parent = self._spec_layout.parentWidget()
        if parent is not None:
            parent.updateGeometry()
            parent.update()

    def _window_spec_cols(self) -> int:
        packet_seconds = PACKET_SAMPLES / SAMPLE_RATE
        return max(10, int(WINDOW_SECONDS / packet_seconds))

    def _configure_spectrogram_storage(self, cols: int) -> None:
        self._spec_cols = max(1, int(cols))
        self._spec_data = {
            "hr1": np.full((self._spec_cols, self._spec_bins), np.nan, dtype=float),
            "hr2": np.full((self._spec_cols, self._spec_bins), np.nan, dtype=float),
            "mhr": np.full((self._spec_cols, self._spec_bins), np.nan, dtype=float),
        }
        self._spec_times = {
            "hr1": np.zeros(self._spec_cols, dtype=float),
            "hr2": np.zeros(self._spec_cols, dtype=float),
            "mhr": np.zeros(self._spec_cols, dtype=float),
        }
        self._spec_col_index = {"hr1": 0, "hr2": 0, "mhr": 0}
        self._spec_filled = {"hr1": 0, "hr2": 0, "mhr": 0}
        self._spec_next_index = {"hr1": 0, "hr2": 0, "mhr": 0}

    def _append_spec_column(self, sig: str, power: np.ndarray, timestamp: float) -> None:
        if sig not in self._spec_data:
            return
        idx = self._spec_next_index[sig]
        self._spec_data[sig][idx, :] = power
        self._spec_times[sig][idx] = timestamp
        self._spec_next_index[sig] = (idx + 1) % self._spec_cols
        self._spec_filled[sig] = min(self._spec_filled[sig] + 1, self._spec_cols)

    def _append_spec_blank(self, sig: str, timestamp: float) -> None:
        if sig not in self._spec_data:
            return
        idx = self._spec_next_index[sig]
        self._spec_data[sig][idx, :] = np.nan
        self._spec_times[sig][idx] = timestamp
        self._spec_next_index[sig] = (idx + 1) % self._spec_cols
        self._spec_filled[sig] = min(self._spec_filled[sig] + 1, self._spec_cols)

    def _ordered_spec_data(self, sig: str) -> Tuple[np.ndarray, np.ndarray]:
        filled = self._spec_filled.get(sig, 0)
        if filled <= 0:
            return np.array([]), np.array([])
        data = self._spec_data[sig]
        times = self._spec_times[sig]
        if filled < self._spec_cols:
            ordered_data = data[:filled, :]
            ordered_times = times[:filled]
        else:
            start = self._spec_next_index[sig]
            ordered_data = np.concatenate((data[start:], data[:start]), axis=0)
            ordered_times = np.concatenate((times[start:], times[:start]), axis=0)
        return ordered_data, ordered_times

    def _setup_spec_axis(self, ax: mpl.axes.Axes, title: str) -> None:  # type: ignore[name-defined]
        ax.set_title(title)
        ax.set_xlabel("Hz")
        ax.set_ylabel("time")
        ax.yaxis_date()
        ax.yaxis.set_major_locator(mdates.AutoDateLocator())
        ax.yaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.tick_params(axis="y", labelsize=8, pad=2)
        ax.tick_params(axis="x", labelsize=8, pad=2)

    def _adjust_spec_margins(self, active_count: int) -> None:
        if active_count >= 3:
            left = 0.24
        elif active_count == 2:
            left = 0.19
        else:
            left = 0.12
        for widget in self._spec_plots.values():
            widget._figure.subplots_adjust(left=left, bottom=0.15, right=0.98, top=0.9)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.resize(1100, 700)
    window.show()
    QtCore.QTimer.singleShot(0, window._apply_theme)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
