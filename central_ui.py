import datetime
import sqlite3
import socket
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from lib.pparser import emRadParser
from lib.recording_store import RecordingStore

SEQUENCE_MODULO = 2**32
MAX_REASONABLE_SEQUENCE_GAP = 100000


def resource_path(relative_path):
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative_path
    return Path(__file__).resolve().parent / relative_path


EMPKINS_LOGO_PATH = resource_path(Path("ui") / "icons" / "empkins_logo.jpg")


def format_time(timestamp):
    if timestamp is None:
        return "-"
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def parse_udp_packet(timestamp, payload):
    if len(payload) < 28:
        return None
    (
        sensor_id,
        sequence_id,
        data_format,
        uptime,
        dummy1,
        dummy2,
        data_size,
    ) = struct.unpack_from("<IIIIIII", payload)
    data = payload[28 : 28 + data_size]
    if len(data) != data_size:
        return None
    return {
        "timestamp": timestamp,
        "sensor_id": sensor_id,
        "sequence_id": sequence_id,
        "data_format": data_format,
        "uptime": uptime,
        "dummy1": dummy1,
        "dummy2": dummy2,
        "data_size": data_size,
        "data": data,
    }


def payload_quality(samples, radar_index):
    if samples is None or samples.shape[1] < 8:
        return False, 0.0
    i_col = radar_index * 2
    q_col = i_col + 1
    signal = float(np.std(samples[:, [i_col, q_col]]))
    return signal > 1.0, signal


def missing_packet_count_between(previous_sequence, current_sequence):
    if previous_sequence is None:
        return 0

    gap = current_sequence - previous_sequence - 1
    if gap >= 0:
        return gap

    wrap_gap = SEQUENCE_MODULO - previous_sequence - 1 + current_sequence
    if 0 < wrap_gap <= MAX_REASONABLE_SEQUENCE_GAP:
        return wrap_gap

    return 0


class RecorderWorker(QtCore.QObject):
    packet_received = QtCore.Signal(dict)
    stats_changed = QtCore.Signal(int)
    error = QtCore.Signal(str)
    stopped = QtCore.Signal(str)

    def __init__(self, db_path, port, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.port = int(port)
        self._running = False
        self._socket = None

    @QtCore.Slot()
    def run(self):
        store = None
        pending = []
        packet_count = 0
        last_stats = time.time()
        self._running = True
        try:
            store = RecordingStore(self.db_path)
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.settimeout(0.1)
            self._socket.bind(("0.0.0.0", self.port))
        except OSError as exc:
            self.error.emit(f"Could not start UDP listener on port {self.port}: {exc}")
            self._running = False

        while self._running:
            try:
                data, _addr = self._socket.recvfrom(4096)
            except socket.timeout:
                pass
            except OSError:
                break
            else:
                packet = parse_udp_packet(time.time(), data)
                if packet is not None:
                    pending.append(packet)
                    packet_count += 1
                    self.packet_received.emit(packet)

            now = time.time()
            if store and (len(pending) >= 200 or (pending and now - last_stats > 1.0)):
                store.insert_packets(pending)
                pending.clear()

            if now - last_stats >= 1.0:
                self.stats_changed.emit(packet_count)
                packet_count = 0
                last_stats = now

        try:
            if store and pending:
                store.insert_packets(pending)
            if store:
                store.stop_open_session()
                store.close()
        finally:
            if self._socket is not None:
                self._socket.close()
            self.stopped.emit("Recording stopped")

    @QtCore.Slot()
    def stop(self):
        self._running = False
        if self._socket is not None:
            self._socket.close()


class StatusDot(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor("#6b7280")
        self.setFixedSize(18, 18)

    def set_color(self, color):
        self._color = QtGui.QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)


class SignalPlotWidget(QtWidgets.QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.values = np.asarray([], dtype=float)
        self.setMinimumHeight(180)

    def set_values(self, values):
        self.values = np.asarray(values, dtype=float)
        if self.values.size > 1200:
            self.values = self.values[-1200:]
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#0f1f1b"))
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        plot_rect = self.rect().adjusted(12, 30, -12, -12)
        painter.setPen(QtGui.QPen(QtGui.QColor("#27443a"), 1))
        for index in range(1, 4):
            y = plot_rect.top() + index * plot_rect.height() / 4
            painter.drawLine(plot_rect.left(), y, plot_rect.right(), y)

        painter.setPen(QtGui.QColor("#ecfdf5"))
        painter.drawText(12, 20, self.title)

        if self.values.size < 2:
            painter.setPen(QtGui.QColor("#a7b7b0"))
            painter.drawText(plot_rect, QtCore.Qt.AlignCenter, "Waiting for signal")
            return

        values = self.values.astype(float)
        values = values - np.nanmean(values)
        span = float(np.nanmax(np.abs(values))) or 1.0
        x_step = plot_rect.width() / max(1, values.size - 1)
        mid_y = plot_rect.center().y()
        scale_y = plot_rect.height() * 0.44 / span

        path = QtGui.QPainterPath()
        path.moveTo(plot_rect.left(), mid_y - values[0] * scale_y)
        for index, value in enumerate(values[1:], start=1):
            path.lineTo(plot_rect.left() + index * x_step, mid_y - value * scale_y)

        painter.setPen(QtGui.QPen(QtGui.QColor("#57ff3a"), 2))
        painter.drawPath(path)


class TimelineWidget(QtWidgets.QWidget):
    selection_changed = QtCore.Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.coverage = []
        self.bounds = None
        self.selection = None
        self._drag_start = None
        self.setMinimumHeight(120)

    def set_coverage(self, coverage, bounds):
        self.coverage = coverage
        self.bounds = bounds
        if bounds and self.selection is None:
            self.selection = bounds
            self.selection_changed.emit(*self.selection)
        self.update()

    def clear_selection(self):
        self.selection = None
        self._drag_start = None
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#f8faf9"))
        track = self.rect().adjusted(18, 34, -18, -34)

        painter.setPen(QtGui.QColor("#17211d"))
        painter.drawText(18, 22, "Recorded coverage")

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#e4ebe7"))
        painter.drawRoundedRect(track, 4, 4)

        if not self.bounds:
            painter.setPen(QtGui.QColor("#65746d"))
            painter.drawText(track, QtCore.Qt.AlignCenter, "No packets recorded yet")
            return

        start, stop = self.bounds
        span = max(1.0, stop - start)
        max_count = max((count for _, _, count in self.coverage), default=1)

        painter.setBrush(QtGui.QColor("#2f7d68"))
        for bucket_start, bucket_stop, count in self.coverage:
            left = track.left() + (bucket_start - start) / span * track.width()
            right = track.left() + (bucket_stop - start) / span * track.width()
            height = max(6, track.height() * count / max_count)
            rect = QtCore.QRectF(
                left,
                track.bottom() - height,
                max(2, right - left),
                height,
            )
            painter.drawRoundedRect(rect, 2, 2)

        if self.selection:
            sel_start, sel_stop = sorted(self.selection)
            left = track.left() + (sel_start - start) / span * track.width()
            right = track.left() + (sel_stop - start) / span * track.width()
            selection_rect = QtCore.QRectF(left, track.top(), max(2, right - left), track.height())
            painter.setBrush(QtGui.QColor(87, 255, 58, 56))
            painter.drawRect(selection_rect)
            painter.setPen(QtGui.QPen(QtGui.QColor("#35b52c"), 2))
            painter.drawLine(left, track.top(), left, track.bottom())
            painter.drawLine(right, track.top(), right, track.bottom())

        painter.setPen(QtGui.QColor("#607169"))
        painter.drawText(18, self.height() - 10, format_time(start))
        right_text = format_time(stop)
        width = painter.fontMetrics().horizontalAdvance(right_text)
        painter.drawText(self.width() - width - 18, self.height() - 10, right_text)

    def _timestamp_at(self, pos):
        if not self.bounds:
            return None
        track = self.rect().adjusted(18, 34, -18, -34)
        ratio = min(1.0, max(0.0, (pos.x() - track.left()) / max(1, track.width())))
        start, stop = self.bounds
        return start + ratio * (stop - start)

    def mousePressEvent(self, event):
        timestamp = self._timestamp_at(event.position())
        if timestamp is None:
            return
        self._drag_start = timestamp
        self.selection = (timestamp, timestamp)
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        timestamp = self._timestamp_at(event.position())
        if timestamp is None:
            return
        self.selection = tuple(sorted((self._drag_start, timestamp)))
        self.selection_changed.emit(*self.selection)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_start is None:
            return
        timestamp = self._timestamp_at(event.position())
        if timestamp is not None:
            self.selection = tuple(sorted((self._drag_start, timestamp)))
            self.selection_changed.emit(*self.selection)
        self._drag_start = None
        self.update()


class CentralWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EmpkinS Radar Recorder")
        self.resize(1180, 820)

        self.store = RecordingStore.create_new()
        self.db_path = self.store.db_path
        self.parser = emRadParser()
        self.worker = None
        self.worker_thread = None
        self.is_recording = False
        self.current_samples = np.asarray([], dtype=float)
        self.current_heartbeat = np.asarray([], dtype=float)
        self.selection = None
        self.last_recorded_sequence = None
        self.missing_packet_count = 0
        self.can_record = True
        self.store_has_open_session = True
        self.radar_state = self._empty_radar_state()

        self._build_ui()
        self._connect_timers()
        self.refresh_timeline()

    def _empty_radar_state(self):
        return {
            index: {
                "last_seen": None,
                "last_sequence": None,
                "sequence_changed": False,
                "valid_signal": False,
                "signal": 0.0,
                "packets": 0,
            }
            for index in range(4)
        }

    def _build_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(16)
        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setObjectName("logoLabel")
        logo = QtGui.QPixmap(str(EMPKINS_LOGO_PATH))
        if not logo.isNull():
            self.logo_label.setPixmap(
                logo.scaledToHeight(54, QtCore.Qt.SmoothTransformation)
            )
        self.logo_label.setFixedSize(185, 62)
        self.logo_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        header.addWidget(self.logo_label)
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(2)
        title = QtWidgets.QLabel("Radar Recorder")
        title.setObjectName("appTitle")
        subtitle = QtWidgets.QLabel("EmpkinS overnight acquisition")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setObjectName("statusPill")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        main_tab = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(main_tab)
        main_layout.setSpacing(14)
        self.tabs.addTab(main_tab, "Recording")

        settings_tab = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout(settings_tab)
        settings_layout.setSpacing(14)
        self.tabs.addTab(settings_tab, "Settings")

        info = QtWidgets.QGridLayout()
        self.path_label = QtWidgets.QLabel(str(self.db_path))
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.new_recording_button = QtWidgets.QPushButton("New Recording")
        self.new_recording_button.setObjectName("secondaryButton")
        self.new_recording_button.clicked.connect(self.create_new_recording)
        self.open_recording_button = QtWidgets.QPushButton("Open Existing Recording")
        self.open_recording_button.setObjectName("secondaryButton")
        self.open_recording_button.clicked.connect(self.open_existing_recording)
        info.addWidget(QtWidgets.QLabel("Recording database"), 0, 0)
        info.addWidget(self.path_label, 0, 1, 1, 3)
        info.addWidget(self.new_recording_button, 0, 4)
        info.addWidget(self.open_recording_button, 0, 5)
        main_layout.addLayout(info)

        settings_box = QtWidgets.QGroupBox("Acquisition settings")
        settings_form = QtWidgets.QGridLayout(settings_box)
        self.port_spin = QtWidgets.QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(300)
        self.node_spin = QtWidgets.QSpinBox()
        self.node_spin.setRange(0, 63)
        self.node_spin.setValue(0)
        self.auto_detect_check = QtWidgets.QCheckBox("Auto-detect node and expected radars")
        self.auto_detect_check.setChecked(True)
        self.expected_checks = []
        expected_box = QtWidgets.QHBoxLayout()
        for index in range(4):
            check = QtWidgets.QCheckBox(f"Radar {index + 1}")
            check.setChecked(True)
            self.expected_checks.append(check)
            expected_box.addWidget(check)
        expected_box.addStretch()

        settings_form.addWidget(self.auto_detect_check, 0, 0, 1, 4)
        settings_form.addWidget(QtWidgets.QLabel("UDP port"), 1, 0)
        settings_form.addWidget(self.port_spin, 1, 1)
        settings_form.addWidget(QtWidgets.QLabel("Node ID"), 1, 2)
        settings_form.addWidget(self.node_spin, 1, 3)
        settings_form.addWidget(QtWidgets.QLabel("Expected radars"), 2, 0)
        settings_form.addLayout(expected_box, 2, 1, 1, 3)
        settings_layout.addWidget(settings_box)
        settings_layout.addStretch()

        controls = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start Recording")
        self.start_button.setObjectName("startButton")
        self.start_button.setMinimumHeight(44)
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button = QtWidgets.QPushButton("Stop Recording")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setMinimumHeight(44)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        self.packet_rate_label = QtWidgets.QLabel("0 packets/s")
        self.packet_rate_label.setObjectName("metricPill")
        controls.addWidget(self.packet_rate_label)
        self.missing_packet_label = QtWidgets.QLabel("0 missing packets")
        self.missing_packet_label.setObjectName("metricOk")
        controls.addWidget(self.missing_packet_label)
        controls.addStretch()
        main_layout.addLayout(controls)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_status_panel(), 1)
        body.addWidget(self._build_plot_panel(), 2)
        main_layout.addLayout(body, 1)

        export_box = QtWidgets.QGroupBox("Export")
        export_layout = QtWidgets.QVBoxLayout(export_box)
        self.timeline = TimelineWidget()
        self.timeline.selection_changed.connect(self.on_selection_changed)
        export_layout.addWidget(self.timeline)
        export_controls = QtWidgets.QHBoxLayout()
        self.selection_label = QtWidgets.QLabel("No export range selected")
        self.export_button = QtWidgets.QPushButton("Export Selected Range")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.clicked.connect(self.export_selected_range)
        self.refresh_button = QtWidgets.QPushButton("Refresh Timeline")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh_timeline)
        export_controls.addWidget(self.selection_label, 1)
        export_controls.addWidget(self.refresh_button)
        export_controls.addWidget(self.export_button)
        export_layout.addLayout(export_controls)
        main_layout.addWidget(export_box)

        self.setStyleSheet(
            """
            QMainWindow { background: #f3f6f4; }
            QWidget {
                background: #f3f6f4;
                color: #17211d;
                font-size: 13px;
            }
            QLabel#logoLabel {
                background: transparent;
            }
            QLabel#appTitle {
                background: transparent;
                font-size: 26px;
                font-weight: 750;
                color: #17211d;
            }
            QLabel#appSubtitle {
                background: transparent;
                font-size: 13px;
                color: #607169;
            }
            QLabel#statusPill, QLabel#metricPill, QLabel#metricOk {
                background: #ffffff;
                border: 1px solid #dce5df;
                border-radius: 14px;
                padding: 6px 12px;
                font-size: 14px;
                font-weight: 650;
            }
            QLabel#statusPill {
                color: #2f7d68;
            }
            QLabel#metricPill {
                color: #17211d;
            }
            QLabel#metricOk {
                color: #1f8f39;
            }
            QTabWidget::pane {
                border: 0;
                top: -1px;
            }
            QTabBar::tab {
                background: #e7eee9;
                color: #45564d;
                border: 1px solid #d2ded6;
                border-bottom: 0;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 10px 18px;
                margin-right: 4px;
                font-weight: 650;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #17211d;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #dce5df;
                border-radius: 6px;
                margin-top: 12px;
                padding: 14px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #40534a;
            }
            QLabel {
                background: transparent;
            }
            QPushButton {
                background: #2f7d68;
                color: white;
                border: 0;
                border-radius: 6px;
                padding: 9px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #286d5b;
            }
            QPushButton:disabled {
                background: #a9b5af;
                color: #eef3f0;
            }
            QPushButton#startButton {
                background: #35a853;
                font-size: 15px;
            }
            QPushButton#startButton:hover {
                background: #2f9449;
            }
            QPushButton#startButton:disabled {
                background: #a9b5af;
                color: #eef3f0;
            }
            QPushButton#stopButton {
                background: #c2413a;
                font-size: 15px;
            }
            QPushButton#stopButton:hover {
                background: #a93631;
            }
            QPushButton#stopButton:disabled {
                background: #a9b5af;
                color: #eef3f0;
            }
            QPushButton#secondaryButton {
                background: #ffffff;
                color: #2f7d68;
                border: 1px solid #c7d8cf;
            }
            QPushButton#secondaryButton:hover {
                background: #edf7f1;
            }
            QSpinBox, QLineEdit {
                background: #ffffff;
                border: 1px solid #cbd9d1;
                border-radius: 4px;
                padding: 6px;
                min-height: 24px;
            }
            QCheckBox {
                background: transparent;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #aebfb5;
                border-radius: 3px;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #2f7d68;
                border-radius: 3px;
                background: #57ff3a;
            }
            """
        )

    def _build_status_panel(self):
        box = QtWidgets.QGroupBox("Radar status")
        layout = QtWidgets.QVBoxLayout(box)
        self.radar_rows = {}
        for index in range(4):
            row = QtWidgets.QHBoxLayout()
            dot = StatusDot()
            label = QtWidgets.QLabel(f"Radar {index + 1}")
            detail = QtWidgets.QLabel("No packets")
            detail.setStyleSheet("color: #607169; background: transparent;")
            row.addWidget(dot)
            row.addWidget(label)
            row.addStretch()
            row.addWidget(detail)
            layout.addLayout(row)
            self.radar_rows[index] = {"dot": dot, "detail": detail}
        layout.addStretch()
        return box

    def _build_plot_panel(self):
        box = QtWidgets.QGroupBox("Live signal")
        layout = QtWidgets.QVBoxLayout(box)
        self.sensor_select = QtWidgets.QSpinBox()
        self.sensor_select.setRange(1, 4)
        self.sensor_select.setValue(1)
        selector = QtWidgets.QHBoxLayout()
        selector.addWidget(QtWidgets.QLabel("Displayed radar"))
        selector.addWidget(self.sensor_select)
        selector.addStretch()
        layout.addLayout(selector)
        self.iq_plot = SignalPlotWidget("I channel")
        self.heartbeat_plot = SignalPlotWidget("Magnitude")
        layout.addWidget(self.iq_plot)
        layout.addWidget(self.heartbeat_plot)
        return box

    def _connect_timers(self):
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.update_radar_status)
        self.status_timer.start(500)

        self.timeline_timer = QtCore.QTimer(self)
        self.timeline_timer.timeout.connect(self.refresh_timeline)
        self.timeline_timer.start(15000)

    def base_sensor_id(self):
        return int(self.node_spin.value())

    def close_store(self, mark_stopped=False):
        if self.store is None:
            return
        if mark_stopped and self.store_has_open_session:
            self.store.stop_open_session()
            self.store_has_open_session = False
        self.store.close()
        self.store = None

    def reset_live_state(self):
        self.radar_state = self._empty_radar_state()
        self.last_recorded_sequence = None
        self.missing_packet_count = 0
        self.missing_packet_label.setText("0 missing packets")
        self.missing_packet_label.setStyleSheet(
            "background: #ffffff; border: 1px solid #dce5df; border-radius: 14px; "
            "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #1f8f39;"
        )
        self.packet_rate_label.setText("0 packets/s")
        self.iq_plot.set_values([])
        self.heartbeat_plot.set_values([])
        self.update_radar_status()

    def set_settings_enabled(self, can_edit_recording_settings):
        self.port_spin.setEnabled(can_edit_recording_settings)
        self.node_spin.setEnabled(can_edit_recording_settings or not self.can_record)
        self.auto_detect_check.setEnabled(can_edit_recording_settings)
        for check in self.expected_checks:
            check.setEnabled(can_edit_recording_settings)

    def set_store(self, store, can_record, status_text):
        self.close_store(mark_stopped=True)
        self.store = store
        self.db_path = store.db_path
        self.can_record = can_record
        self.store_has_open_session = can_record
        self.path_label.setText(str(self.db_path))
        self.selection = None
        self.selection_label.setText("No export range selected")
        self.timeline.clear_selection()
        self.reset_live_state()
        self.refresh_timeline()
        self.start_button.setEnabled(can_record)
        self.set_settings_enabled(can_record)
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(
            "background: #ffffff; border: 1px solid #dce5df; border-radius: 14px; "
            "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #2f7d68;"
        )

    @QtCore.Slot()
    def create_new_recording(self):
        if self.is_recording:
            QtWidgets.QMessageBox.information(
                self,
                "Recording is active",
                "Stop the current recording before creating a new one.",
            )
            return
        try:
            store = RecordingStore.create_new()
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Could not create recording", str(exc))
            return
        self.set_store(store, can_record=True, status_text="Ready")

    @QtCore.Slot()
    def open_existing_recording(self):
        if self.is_recording:
            QtWidgets.QMessageBox.information(
                self,
                "Recording is active",
                "Stop the current recording before opening another recording.",
            )
            return
        filename, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open existing recording",
            str(RecordingStore.default_recordings_root()),
            "SQLite Recordings (*.sqlite *.db *.sql);;All Files (*)",
        )
        if not filename:
            return
        db_path = Path(filename)
        if not db_path.exists():
            QtWidgets.QMessageBox.critical(self, "Recording not found", str(db_path))
            return
        try:
            store = RecordingStore(db_path)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Could not open recording", str(exc))
            return
        self.set_store(store, can_record=False, status_text="Existing recording loaded")

    @QtCore.Slot()
    def start_recording(self):
        if self.is_recording or not self.can_record:
            return
        self.worker_thread = QtCore.QThread(self)
        self.worker = RecorderWorker(str(self.db_path), self.port_spin.value())
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.packet_received.connect(self.on_packet_received)
        self.worker.stats_changed.connect(self.on_stats_changed)
        self.worker.error.connect(self.on_worker_error)
        self.worker.stopped.connect(self.on_worker_stopped)
        self.worker.stopped.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.start()

        self.is_recording = True
        self.radar_state = self._empty_radar_state()
        self.last_recorded_sequence = None
        self.missing_packet_count = 0
        if self.auto_detect_check.isChecked():
            for check in self.expected_checks:
                check.setChecked(False)
        self.missing_packet_label.setText("0 missing packets")
        self.missing_packet_label.setStyleSheet(
            "background: #ffffff; border: 1px solid #dce5df; border-radius: 14px; "
            "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #1f8f39;"
        )
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.new_recording_button.setEnabled(False)
        self.open_recording_button.setEnabled(False)
        self.set_settings_enabled(False)
        self.status_label.setText("Recording")
        self.status_label.setStyleSheet(
            "background: #eaffea; border: 1px solid #aceca6; border-radius: 14px; "
            "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #207d1d;"
        )

    @QtCore.Slot()
    def stop_recording(self):
        if self.worker is not None:
            self.worker.stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping")

    @QtCore.Slot(dict)
    def on_packet_received(self, packet):
        parsed = self.parser.parse(packet["data"])
        if parsed is None:
            return

        if self.auto_detect_check.isChecked() and self.is_recording:
            detected_node_id = int(packet["sensor_id"])
            if self.last_recorded_sequence is None and detected_node_id != self.base_sensor_id():
                self.node_spin.setValue(detected_node_id)
                self.status_label.setText(f"Recording node {detected_node_id}")

            for index, check in enumerate(self.expected_checks):
                valid_signal, _signal = payload_quality(parsed, index)
                if valid_signal and not check.isChecked():
                    check.setChecked(True)

        if int(packet["sensor_id"]) != self.base_sensor_id():
            return

        sequence_id = int(packet["sequence_id"])
        missing_count = missing_packet_count_between(
            self.last_recorded_sequence, sequence_id
        )
        if missing_count:
            self.missing_packet_count += missing_count
            self.missing_packet_label.setText(
                f"{self.missing_packet_count} missing packets"
            )
            self.missing_packet_label.setStyleSheet(
                "background: #fff1f0; border: 1px solid #f1b7b2; border-radius: 14px; "
                "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #b42318;"
            )
        self.last_recorded_sequence = sequence_id

        for index in range(4):
            state = self.radar_state[index]
            if state["last_sequence"] is not None and packet["sequence_id"] != state["last_sequence"]:
                state["sequence_changed"] = True
            state["last_sequence"] = packet["sequence_id"]
            state["last_seen"] = packet["timestamp"]
            state["packets"] += 1
            state["valid_signal"], state["signal"] = payload_quality(parsed, index)

        index = self.sensor_select.value() - 1
        i_col = index * 2
        q_col = i_col + 1
        self.current_samples = parsed[:, i_col]
        magnitude = np.sqrt(np.square(parsed[:, i_col]) + np.square(parsed[:, q_col]))
        self.current_heartbeat = magnitude
        self.iq_plot.set_values(self.current_samples)
        self.heartbeat_plot.set_values(self.current_heartbeat)

    @QtCore.Slot(int)
    def on_stats_changed(self, packets_per_second):
        self.packet_rate_label.setText(f"{packets_per_second} packets/s")

    @QtCore.Slot(str)
    def on_worker_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Recorder error", message)
        self.status_label.setText("Error")

    @QtCore.Slot(str)
    def on_worker_stopped(self, message):
        self.is_recording = False
        self.worker = None
        self.worker_thread = None
        self.store_has_open_session = False
        self.store.close()
        self.store = RecordingStore(self.db_path)
        self.refresh_timeline()
        self.start_button.setEnabled(self.can_record)
        self.stop_button.setEnabled(False)
        self.new_recording_button.setEnabled(True)
        self.open_recording_button.setEnabled(True)
        self.set_settings_enabled(self.can_record)
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet(
            "background: #fff1f0; border: 1px solid #f1b7b2; border-radius: 14px; "
            "padding: 6px 12px; font-size: 14px; font-weight: 650; color: #b42318;"
        )

    def update_radar_status(self):
        now = time.time()
        for index, row in self.radar_rows.items():
            expected = self.expected_checks[index].isChecked()
            state = self.radar_state[index]
            last_seen = state["last_seen"]

            if not expected:
                row["dot"].set_color("#9ca3af")
                row["detail"].setText("Not expected")
                continue

            fresh = last_seen is not None and now - last_seen <= 2.5
            healthy = fresh and state["sequence_changed"] and state["valid_signal"]
            warning = fresh and not healthy

            if healthy:
                row["dot"].set_color("#22c55e")
                row["detail"].setText(f"{state['packets']} packets, signal {state['signal']:.1f}")
            elif warning:
                row["dot"].set_color("#f59e0b")
                row["detail"].setText("Packets present, signal not valid yet")
            else:
                row["dot"].set_color("#ef4444")
                row["detail"].setText("No valid recent signal")

    def refresh_timeline(self):
        try:
            coverage = self.store.get_coverage(bucket_seconds=60)
            bounds = self.store.get_time_bounds()
        except sqlite3.Error:
            return
        self.timeline.set_coverage(coverage, bounds)

    def on_selection_changed(self, start, stop):
        self.selection = (start, stop)
        self.selection_label.setText(f"{format_time(start)} to {format_time(stop)}")

    def export_selected_range(self):
        if not self.selection:
            QtWidgets.QMessageBox.information(self, "No range selected", "Select a time range on the timeline first.")
            return
        start, stop = self.selection
        if stop - start < 1:
            QtWidgets.QMessageBox.information(self, "Range too short", "Select a longer time range.")
            return

        default_name = f"export_{datetime.datetime.fromtimestamp(start).strftime('%Y%m%d_%H%M%S')}.h5"
        output_path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export selected range",
            str(self.db_path.parent / default_name),
            "HDF5 Files (*.h5)",
        )
        if not output_path:
            return

        try:
            self.store.export_range_to_h5(start, stop, output_path, node_id=self.node_spin.value())
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Export complete", f"Exported to {output_path}")

    def closeEvent(self, event):
        if self.is_recording:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Recording is active",
                "Stop the recording and close the application?",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.stop_recording()
            if self.worker_thread is not None:
                self.worker_thread.quit()
                self.worker_thread.wait(2000)
        if self.store:
            self.close_store(mark_stopped=True)
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("EmpkinS Radar Recorder")
    window = CentralWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
