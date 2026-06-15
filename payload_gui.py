#!/usr/bin/env python3
"""
AOSP Payload Dumper GUI
Modern UI for extracting Android OTA payloads.
v2.0.0
"""

import sys
import os
import time
import subprocess
import platform
from pathlib import Path
from typing import Optional, Dict, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QFileDialog, QMessageBox, QListWidget, QTabWidget,
    QGroupBox, QStatusBar, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QPropertyAnimation, QEasingCurve, QRectF, pyqtProperty
from PyQt6.QtGui import QFont, QPalette, QColor, QPainter, QPen, QBrush

try:
    import payload_core
except ImportError as e:
    print(f"Error: Cannot import payload_core module: {e}")
    sys.exit(1)

VERSION = "2.0.0"
APP_NAME = "AOSP Payload Dumper"


# ---------------------------------------------------------------------------
# Custom Slider Toggle Switch widget
# ---------------------------------------------------------------------------
class ToggleSwitch(QWidget):
    """
    A pill-shaped slider toggle switch.
    Left side shows 🌙 (dark mode active), right side shows ☀️ (light mode active).
    The knob slides smoothly between sides via QPropertyAnimation.
    """
    toggled = pyqtSignal(bool)  # True = dark mode ON

    def __init__(self, parent=None, checked=False):
        super().__init__(parent)
        self.setFixedSize(80, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked          # True = dark mode
        # _knob_pos: 0.0 = left (dark), 1.0 = right (light)
        self._knob_pos = 0.0 if checked else 1.0

        self._animation = QPropertyAnimation(self, b"knob_pos", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # --- Property for animation ---
    def get_knob_pos(self):
        return self._knob_pos

    def set_knob_pos(self, value):
        self._knob_pos = value
        self.update()

    knob_pos = pyqtProperty(float, fget=get_knob_pos, fset=set_knob_pos)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked == checked:
            return
        self._checked = checked
        target = 0.0 if checked else 1.0
        self._animation.stop()
        self._animation.setStartValue(self._knob_pos)
        self._animation.setEndValue(target)
        self._animation.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            target = 0.0 if self._checked else 1.0
            self._animation.stop()
            self._animation.setStartValue(self._knob_pos)
            self._animation.setEndValue(target)
            self._animation.start()
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        padding = 3
        knob_diameter = h - 2 * padding

        # --- Track ---
        # Dark mode active → deep blue track; Light mode → amber/orange track
        if self._checked:
            track_color = QColor(42, 100, 200)
        else:
            track_color = QColor(240, 160, 30)

        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        # --- Emoji labels ---
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)

        # Moon on the left
        moon_rect = QRectF(4, 0, 28, h)
        painter.drawText(moon_rect, Qt.AlignmentFlag.AlignCenter, "🌙")

        # Sun on the right
        sun_rect = QRectF(w - 32, 0, 28, h)
        painter.drawText(sun_rect, Qt.AlignmentFlag.AlignCenter, "☀️")

        # --- Knob ---
        # knob_pos 0.0 = leftmost (dark mode active), 1.0 = rightmost (light mode)
        travel = w - 2 * padding - knob_diameter
        knob_x = padding + self._knob_pos * travel

        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawEllipse(
            int(knob_x), padding,
            knob_diameter, knob_diameter
        )

        painter.end()


# ---------------------------------------------------------------------------
# Extraction worker thread
# ---------------------------------------------------------------------------
class ExtractionWorker(QThread):
    """Worker thread — runs extraction in background so UI doesn't freeze"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    partition_signal = pyqtSignal(str, int, int)
    completed_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, payload_path: str, output_dir: str, images: Optional[List[str]] = None):
        super().__init__()
        self.payload_path = payload_path
        self.output_dir = output_dir
        self.images = images
        self.is_cancelled = False
        self.extracted_files = []
        self.current_partition = ""
        self.total_partitions = 0
        self.current_partition_idx = 0

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            self.log_signal.emit("🚀 Starting payload extraction...")

            if not os.path.exists(self.payload_path):
                raise FileNotFoundError(f"Payload file not found: {self.payload_path}")

            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir, exist_ok=True)

            test_file = os.path.join(self.output_dir, ".write_test")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except Exception:
                raise PermissionError(f"Cannot write to output directory: {self.output_dir}")

            start_time = time.time()
            payload_core.run_payload_dumper(
                payload_path=self.payload_path,
                out_dir=self.output_dir,
                images=self.images,
                log_callback=self._log_callback,
                progress_callback=self._progress_callback,
                cancel_flag=lambda: self.is_cancelled,
                setup_callback=self._setup_callback
            )

            if not self.is_cancelled:
                elapsed = time.time() - start_time
                self._scan_extracted_files()
                self.log_signal.emit(f"✅ Extraction completed in {elapsed:.1f} seconds!")
                self.completed_signal.emit(self.extracted_files)

        except Exception as e:
            self.error_signal.emit(f"❌ Extraction failed: {str(e)}")

    def _setup_callback(self, total_parts: int, total_ops: int):
        """Called by the backend before the extraction loop starts.
        Sets self.total_partitions so the partition label shows the correct denominator."""
        self.total_partitions = total_parts

    def _log_callback(self, message: str):
        if "Processing" in message and "partition" in message:
            try:
                partition_name = message.split("Processing ")[1].split(" partition")[0]
                self.current_partition = partition_name
                self.current_partition_idx += 1
                self.partition_signal.emit(partition_name, self.current_partition_idx, self.total_partitions)
            except Exception:
                pass
        self.log_signal.emit(message)

    def _progress_callback(self, percentage: int):
        self.progress_signal.emit(percentage)

    def _scan_extracted_files(self):
        try:
            for file_path in Path(self.output_dir).glob("*.img"):
                size = file_path.stat().st_size
                self.extracted_files.append({
                    'name': file_path.name,
                    'path': str(file_path),
                    'size': size,
                })
        except Exception as e:
            self.log_signal.emit(f"Warning: Could not scan extracted files: {e}")


def format_size(num_bytes: int) -> str:
    """Return a human-readable file size string, picking the right unit automatically."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 ** 3:
        return f"{num_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{num_bytes / (1024 ** 3):.2f} GB"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class PayloadDumperGUI(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, "Settings")
        self.worker = None
        self.extraction_start_time = None

        self.init_ui()
        self.restore_settings()
        self.setup_timer()

        # Apply saved theme on startup
        if self.settings.value("dark_mode", False, type=bool):
            self.apply_dark_theme()

    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setMinimumSize(900, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Top bar: title + dark mode toggle ---
        top_bar = QHBoxLayout()
        app_label = QLabel(f"<b>{APP_NAME}</b>")
        app_label.setFont(QFont("Arial", 11))
        top_bar.addWidget(app_label)
        top_bar.addStretch()

        # Label to the left of the switch showing current state
        self.theme_label = QLabel("Light Mode")
        self.theme_label.setFont(QFont("Arial", 9))
        top_bar.addWidget(self.theme_label)

        self.toggle_switch = ToggleSwitch(
            checked=self.settings.value("dark_mode", False, type=bool)
        )
        self.toggle_switch.toggled.connect(self.toggle_dark_mode)
        top_bar.addWidget(self.toggle_switch)

        main_layout.addLayout(top_bar)

        # --- Tabs ---
        tab_widget = QTabWidget()
        tab_widget.addTab(self.create_extraction_tab(), "📂 Extraction")
        tab_widget.addTab(self.create_results_tab(), "📋 Results")
        main_layout.addWidget(tab_widget)

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Sync label to saved state
        self._sync_theme_label()

    def _sync_theme_label(self):
        """Keep the label next to the toggle in sync with actual state."""
        if self.settings.value("dark_mode", False, type=bool):
            self.theme_label.setText("Dark Mode")
        else:
            self.theme_label.setText("Light Mode")

    def create_extraction_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # --- Input section ---
        input_group = QGroupBox("📁 Input Files")
        input_layout = QVBoxLayout(input_group)

        # Payload file
        payload_layout = QHBoxLayout()
        payload_layout.addWidget(QLabel("Payload/OTA File:"))
        self.payload_entry = QLineEdit()
        self.payload_entry.setPlaceholderText("Select payload.bin or OTA zip file...")
        payload_layout.addWidget(self.payload_entry)
        self.browse_payload_btn = QPushButton("📁 Browse")
        self.browse_payload_btn.clicked.connect(self.browse_payload)
        payload_layout.addWidget(self.browse_payload_btn)
        input_layout.addLayout(payload_layout)

        # Output directory (optional)
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Directory:"))
        self.output_entry = QLineEdit()
        self.output_entry.setPlaceholderText("Leave empty to extract alongside the payload file...")
        output_layout.addWidget(self.output_entry)
        self.browse_output_btn = QPushButton("📁 Browse")
        self.browse_output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.browse_output_btn)
        input_layout.addLayout(output_layout)

        # Partition filter (optional text input)
        partition_layout = QHBoxLayout()
        partition_layout.addWidget(QLabel("Partitions (optional):"))
        self.images_entry = QLineEdit()
        self.images_entry.setPlaceholderText("e.g., system,boot,vendor  —  leave empty to extract all")
        partition_layout.addWidget(self.images_entry)
        input_layout.addLayout(partition_layout)

        layout.addWidget(input_group)

        # --- Progress section ---
        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.current_partition_label = QLabel("Ready to start...")
        progress_layout.addWidget(self.current_partition_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 Start Extraction")
        self.start_btn.clicked.connect(self.start_extraction)
        self.start_btn.setMinimumHeight(40)
        button_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("⏹ Cancel")
        self.cancel_btn.clicked.connect(self.cancel_extraction)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(40)
        button_layout.addWidget(self.cancel_btn)

        progress_layout.addLayout(button_layout)
        layout.addWidget(progress_group)

        # --- Log area ---
        log_group = QGroupBox("📝 Extraction Log")
        log_layout = QVBoxLayout(log_group)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(200)
        log_layout.addWidget(self.log_area)
        layout.addWidget(log_group)

        return widget

    def create_results_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header_layout = QHBoxLayout()
        self.results_label = QLabel("📋 Extracted Files")
        self.results_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        header_layout.addWidget(self.results_label)
        header_layout.addStretch()
        self.open_folder_btn = QPushButton("📂 Open Output Folder")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        self.open_folder_btn.setEnabled(False)
        header_layout.addWidget(self.open_folder_btn)
        layout.addLayout(header_layout)

        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        layout.addWidget(self.results_list)

        return widget

    def setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_elapsed_time)

    def restore_settings(self):
        if self.settings.contains("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        self.payload_entry.setText(self.settings.value("last_payload_path", ""))
        self.output_entry.setText(self.settings.value("last_output_path", ""))
        self.images_entry.setText(self.settings.value("last_images", ""))

    def save_settings(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("last_payload_path", self.payload_entry.text())
        self.settings.setValue("last_output_path", self.output_entry.text())
        self.settings.setValue("last_images", self.images_entry.text())

    def toggle_dark_mode(self, dark_on: bool):
        """Called when the toggle switch is clicked."""
        self.settings.setValue("dark_mode", dark_on)
        if dark_on:
            self.theme_label.setText("Dark Mode")
            self.apply_dark_theme()
        else:
            self.theme_label.setText("Light Mode")
            self.apply_light_theme()

    def apply_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        self.setPalette(dark_palette)
        # Keep the toggle switch in sync if called from startup
        self.toggle_switch.setChecked(True)
        self.theme_label.setText("Dark Mode")

    def apply_light_theme(self):
        self.setPalette(QApplication.style().standardPalette())
        self.toggle_switch.setChecked(False)
        self.theme_label.setText("Light Mode")

    # --- File browsing ---

    def browse_payload(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Payload File",
            self.payload_entry.text() or os.path.expanduser("~"),
            "All Supported Files (*.bin *.zip);;Payload Files (*.bin);;ZIP Files (*.zip);;All Files (*.*)"
        )
        if file_path:
            self.payload_entry.setText(file_path)
            self.validate_inputs()


    def browse_output(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.output_entry.text() or os.path.expanduser("~")
        )
        if dir_path:
            self.output_entry.setText(dir_path)
            self.validate_inputs()


    # --- Validation ---

    def validate_inputs(self) -> bool:
        """Only the payload file is required. Output directory is optional."""
        payload_path = self.payload_entry.text().strip()

        if not payload_path or not os.path.exists(payload_path):
            self.status_bar.showMessage("❌ Please select a valid payload file")
            self.start_btn.setEnabled(False)
            return False

        try:
            if payload_path.endswith('.zip'):
                import zipfile
                with zipfile.ZipFile(payload_path, 'r') as zf:
                    if "payload.bin" not in zf.namelist():
                        raise ValueError("ZIP file does not contain payload.bin")
            else:
                with open(payload_path, 'rb') as f:
                    magic = f.read(4)
                    if magic != b'CrAU':
                        raise ValueError("Invalid payload file format")
        except Exception as e:
            self.status_bar.showMessage(f"❌ Invalid file: {str(e)}")
            self.start_btn.setEnabled(False)
            return False

        self.status_bar.showMessage("✅ Ready to extract")
        self.start_btn.setEnabled(True)
        return True

    # --- Extraction ---

    def start_extraction(self):
        if not self.validate_inputs():
            return

        payload_path = self.payload_entry.text().strip()
        output_dir = self.output_entry.text().strip()

        # Default: extract to the same folder as the payload file
        if not output_dir:
            output_dir = str(Path(payload_path).parent)
            self.output_entry.setText(output_dir)

        # Parse comma-separated partition names (empty = extract all)
        images_text = self.images_entry.text().strip()
        images = [p.strip() for p in images_text.split(",") if p.strip()] if images_text else None

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot create output directory:\n{str(e)}")
            return

        self.log_area.clear()
        self.results_list.clear()
        self.progress_bar.setValue(0)
        self.current_partition_label.setText("Preparing...")
        self.save_settings()

        self.worker = ExtractionWorker(
            payload_path=payload_path,
            output_dir=output_dir,
            images=images
        )
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.partition_signal.connect(self.update_partition_progress)
        self.worker.completed_signal.connect(self.extraction_completed)
        self.worker.error_signal.connect(self.extraction_error)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.browse_payload_btn.setEnabled(False)
        self.browse_output_btn.setEnabled(False)

        self.extraction_start_time = time.time()
        self.timer.start(1000)
        self.worker.start()

    def cancel_extraction(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.append_log("🛑 Cancellation requested...")
            self.status_bar.showMessage("Cancelling extraction...")

    # --- Signal handlers ---

    def append_log(self, message: str):
        self.log_area.append(message)
        self.log_area.ensureCursorVisible()

    def update_progress(self, percentage: int):
        self.progress_bar.setValue(percentage)

    def update_partition_progress(self, partition_name: str, current: int, total: int):
        self.current_partition_label.setText(f"📂 Processing: {partition_name} ({current}/{total})")

    def update_elapsed_time(self):
        if self.extraction_start_time:
            elapsed = int(time.time() - self.extraction_start_time)
            mins, secs = divmod(elapsed, 60)
            self.status_bar.showMessage(f"⏱ Elapsed time: {mins:02d}:{secs:02d}")

    def extraction_completed(self, extracted_files: List[Dict]):
        self.timer.stop()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.browse_payload_btn.setEnabled(True)
        self.browse_output_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(True)

        self.update_results_list(extracted_files)
        self.current_partition_label.setText("✅ Extraction completed!")
        self.progress_bar.setValue(100)

        total_bytes = sum(f['size'] for f in extracted_files)
        QMessageBox.information(
            self,
            "Extraction Complete",
            f"Successfully extracted {len(extracted_files)} partition(s)\n"
            f"Total size: {format_size(total_bytes)}"
        )

    def extraction_error(self, error_message: str):
        self.timer.stop()
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.browse_payload_btn.setEnabled(True)
        self.browse_output_btn.setEnabled(True)

        self.current_partition_label.setText("❌ Extraction failed")
        self.status_bar.showMessage("❌ Extraction failed")
        QMessageBox.critical(self, "Extraction Failed", error_message)

    def update_results_list(self, extracted_files: List[Dict]):
        self.results_list.clear()
        for file_info in extracted_files:
            item_text = f"📱 {file_info['name']} ({format_size(file_info['size'])})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, file_info['path'])
            self.results_list.addItem(item)
        total_bytes = sum(f['size'] for f in extracted_files)
        self.results_label.setText(
            f"📋 Extracted Files ({len(extracted_files)} files, {format_size(total_bytes)})"
        )

    def open_output_folder(self):
        output_path = self.output_entry.text().strip()
        if not output_path or not os.path.exists(output_path):
            QMessageBox.warning(self, "Warning", "Output directory not found")
            return
        try:
            if platform.system() == "Windows":
                os.startfile(output_path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", output_path])
            else:
                subprocess.run(["xdg-open", output_path])
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Cannot open folder:\n{str(e)}")

    def closeEvent(self, event):
        self.save_settings()
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Extraction is in progress. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait(5000)
            else:
                event.ignore()
                return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("AOSP Tools")

    window = PayloadDumperGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()