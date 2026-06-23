#!/usr/bin/env python3
import sys
import os
import tarfile
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QFrame, QGraphicsDropShadowEffect,
    QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QColor, QFont, QCursor

def validate_or_create_desktop_file():
    """Generates or validates ~/.local/share/applications/antigravity-ide.desktop.
    Ensures that the Exec line contains the --no-sandbox flag.
    """
    desktop_dir = os.path.expanduser("~/.local/share/applications")
    os.makedirs(desktop_dir, exist_ok=True)
    desktop_path = os.path.join(desktop_dir, "antigravity-ide.desktop")
    
    # Check what executable actually exists in /opt/antigravity-ide/
    binary_name = "antigravity-ide"
    if os.path.exists("/opt/antigravity-ide"):
        found = False
        try:
            for file in os.listdir("/opt/antigravity-ide"):
                file_path = os.path.join("/opt/antigravity-ide", file)
                if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                    if file.lower().startswith("antigravity"):
                        binary_name = file
                        found = True
                        break
        except Exception:
            pass
            
        if not found:
            candidates = ["antigravity-ide", "antigravity", "antigravity_ide"]
            for c in candidates:
                if os.path.isfile(os.path.join("/opt/antigravity-ide", c)):
                    binary_name = c
                    break
    
    exec_path = f"/opt/antigravity-ide/{binary_name}"
    exec_line = f"{exec_path} --no-sandbox %U"
    
    # Try to find an icon in the directory, fallback to generic
    icon_path = "antigravity-ide"
    if os.path.exists("/opt/antigravity-ide"):
        for root, dirs, files in os.walk("/opt/antigravity-ide"):
            for file in files:
                if file.endswith((".png", ".svg")) and "icon" in file.lower():
                    icon_path = os.path.join(root, file)
                    break
            if icon_path != "antigravity-ide":
                break

    lines = []
    updated = False
    
    if os.path.exists(desktop_path):
        with open(desktop_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        exec_found = False
        for i, line in enumerate(lines):
            if line.startswith("Exec="):
                exec_found = True
                current_exec = line.split("Exec=")[1].strip()
                # If --no-sandbox is missing or execution path is wrong, update it
                if "--no-sandbox" not in current_exec or not current_exec.startswith(exec_path):
                    lines[i] = f"Exec={exec_line}\n"
                    updated = True
        if not exec_found:
            # Insert Exec under [Desktop Entry]
            for i, line in enumerate(lines):
                if line.strip() == "[Desktop Entry]":
                    lines.insert(i + 1, f"Exec={exec_line}\n")
                    updated = True
                    break
    else:
        # Create a fresh desktop file
        lines = [
            "[Desktop Entry]\n",
            "Version=1.0\n",
            "Type=Application\n",
            "Name=Antigravity IDE\n",
            f"Exec={exec_line}\n",
            f"Icon={icon_path}\n",
            "Comment=Antigravity Integrated Development Environment\n",
            "Categories=Development;IDE;\n",
            "Terminal=false\n",
            "StartupWMClass=antigravity-ide\n",
            "MimeType=text/plain;\n"
        ]
        updated = True

    if updated:
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
            
    # Refresh the KDE app menu
    try:
        subprocess.run(["update-desktop-database", desktop_dir], check=False)
    except Exception as e:
        print(f"Error updating desktop database: {e}", file=sys.stderr)


class UpdateWorker(QThread):
    """Worker thread that executes the elevated installation helper via pkexec
    and completes user-space desktop file configuration.
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, helper_path, tarball_path):
        super().__init__()
        self.helper_path = helper_path
        self.tarball_path = tarball_path
        
    def run(self):
        try:
            self.progress.emit("Authenticating as administrator...")
            
            # Execute elevated helper script using Polkit
            cmd = ["pkexec", "python3", self.helper_path, self.tarball_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                self.progress.emit("Configuring desktop shortcut...")
                validate_or_create_desktop_file()
                self.finished.emit(True, "Antigravity IDE updated successfully!")
            else:
                # Capture stderr or provide fallback
                error_msg = result.stderr.strip()
                if not error_msg:
                    error_msg = result.stdout.strip() or f"Process exited with code {result.returncode}"
                
                # Check for Polkit rejection/cancellation
                if "pkexec" in error_msg.lower() or "polkit" in error_msg.lower() or result.returncode == 127:
                    error_msg = "Authentication cancelled or failed."
                
                self.finished.emit(False, error_msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class DropZoneFrame(QFrame):
    """Custom Frame that detects left-click releases for file dialog selection,
    while passing drag gestures to the system to allow moving the widget.
    """
    clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drag_start = None
        self.has_dragged = False
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.has_dragged = False
            event.accept()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_start is not None:
            delta = event.globalPosition().toPoint() - self.drag_start
            if delta.manhattanLength() > 6:
                self.has_dragged = True
                parent = self.window()
                if parent and parent.windowHandle():
                    parent.windowHandle().startSystemMove()
                    self.drag_start = None
                    event.accept()
                    return
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.has_dragged:
                self.clicked.emit()
            self.drag_start = None
            self.has_dragged = False
            event.accept()
        super().mouseReleaseEvent(event)


class DropZoneApp(QMainWindow):
    """PyQt6 Graphical Dropzone Application with premium animations and dark mode styling."""
    
    def __init__(self):
        super().__init__()
        self.state = "idle"
        self.worker = None
        self.drag_position = None
        
        self.init_ui()
        self.set_state("idle")
        
    def init_ui(self):
        # Window properties
        self.setWindowTitle("Antigravity IDE Updater")
        self.setFixedSize(360, 260)
        
        # Translucent glassmorphism flag settings
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Frameless window flags (allows dragging and normal window layers)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAcceptDrops(True)
        
        # Main background container frame
        self.main_frame = QFrame(self)
        self.main_frame.setObjectName("mainFrame")
        self.main_frame.setGeometry(0, 0, 360, 260)
        
        # Window Shadow / Glow Effect
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setColor(QColor(66, 153, 225, 80)) # Sky blue glow
        self.shadow.setOffset(0, 0)
        self.main_frame.setGraphicsEffect(self.shadow)
        
        # Shadow breathing animation during update state
        self.shadow_anim = QPropertyAnimation(self.shadow, b"blurRadius")
        self.shadow_anim.setDuration(1200)
        self.shadow_anim.setStartValue(12)
        self.shadow_anim.setEndValue(32)
        self.shadow_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.shadow_anim.setLoopCount(-1)
        
        # Main Layout
        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        
        # Header layout (title & utility buttons)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 0, 4, 0)
        
        self.header_title = QLabel("AGY UPDATER", self.main_frame)
        self.header_title.setStyleSheet("""
            color: rgba(255, 255, 255, 0.4);
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 1.5px;
            font-family: 'Inter', sans-serif;
        """)
        header_layout.addWidget(self.header_title)
        header_layout.addStretch()
        
        # Close Button
        self.close_button = QPushButton("✕", self.main_frame)
        self.close_button.setObjectName("closeButton")
        self.close_button.setToolTip("Close")
        self.close_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        header_layout.addWidget(self.close_button)
        
        layout.addLayout(header_layout)
        
        # Central drop zone
        self.drop_zone = DropZoneFrame(self.main_frame)
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.drop_zone.clicked.connect(self.select_file_dialog)
        
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(12, 20, 12, 20)
        drop_layout.setSpacing(6)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Icon Label
        self.icon_label = QLabel("📦", self.drop_zone)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self.icon_label)
        
        # Main Title Label
        self.title_label = QLabel("Drop Antigravity IDE .tar.gz here", self.drop_zone)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        drop_layout.addWidget(self.title_label)
        
        # Description Label
        self.desc_label = QLabel("Or click to browse files", self.drop_zone)
        self.desc_label.setObjectName("descLabel")
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setWordWrap(True)
        drop_layout.addWidget(self.desc_label)
        
        # Hidden progress indicator
        self.progress_bar = QProgressBar(self.drop_zone)
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setVisible(False)
        drop_layout.addWidget(self.progress_bar)
        
        # Make labels and progress bar transparent for mouse events
        # so they pass through to the DropZoneFrame parent
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.desc_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.progress_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        layout.addWidget(self.drop_zone)
        
        # Application-wide stylesheet
        self.setStyleSheet("""
            #mainFrame {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 rgba(26, 28, 38, 230), stop:1 rgba(15, 16, 24, 245));
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 20px;
            }
            
            #closeButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 0.5);
                border: none;
                border-radius: 12px;
                font-size: 13px;
            }
            #closeButton:hover {
                background-color: rgba(239, 68, 68, 0.15);
                color: rgb(248, 113, 113);
            }
            
            #titleLabel {
                color: #f7fafc;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Outfit', 'Inter', sans-serif;
            }
            
            #descLabel {
                color: #a0aec0;
                font-size: 11px;
                font-family: 'Inter', sans-serif;
            }
            
            QProgressBar {
                border: none;
                background-color: rgba(255, 255, 255, 0.06);
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #63b3ed, stop:1 #4299e1);
                border-radius: 3px;
            }
        """)

    def set_state(self, state, extra_info=""):
        """Updates the visual appearance and state parameters of the widget."""
        self.state = state
        self.shadow_anim.stop()
        
        if state == "idle":
            self.shadow.setColor(QColor(66, 153, 225, 80)) # Cyan-blue subtle glow
            self.shadow.setBlurRadius(15)
            self.drop_zone.setStyleSheet("""
                #dropZone {
                    border: 2px dashed rgba(99, 179, 237, 0.3);
                    border-radius: 16px;
                    background-color: rgba(255, 255, 255, 0.02);
                }
                #dropZone:hover {
                    border: 2px dashed rgba(99, 179, 237, 0.6);
                    background-color: rgba(255, 255, 255, 0.04);
                }
            """)
            self.icon_label.setText("📦")
            self.icon_label.setStyleSheet("font-size: 44px; margin-bottom: 2px;")
            self.title_label.setText("Drop Antigravity IDE .tar.gz here")
            self.desc_label.setText("Or click to browse files")
            self.progress_bar.setVisible(False)
            
        elif state == "drag_over":
            self.shadow.setColor(QColor(72, 187, 120, 150)) # Green glow
            self.shadow.setBlurRadius(25)
            self.drop_zone.setStyleSheet("""
                #dropZone {
                    border: 2px dashed rgba(72, 187, 120, 0.8);
                    border-radius: 16px;
                    background-color: rgba(72, 187, 120, 0.08);
                }
            """)
            self.icon_label.setText("📥")
            self.icon_label.setStyleSheet("font-size: 44px; margin-bottom: 2px;")
            self.title_label.setText("Release to start installation")
            self.desc_label.setText("Validating tarball structure...")
            self.progress_bar.setVisible(False)
            
        elif state == "updating":
            self.shadow.setColor(QColor(66, 153, 225, 180)) # Glowing blue
            self.shadow_anim.start() # Start pulsing glow
            self.drop_zone.setStyleSheet("""
                #dropZone {
                    border: 1px solid rgba(66, 153, 225, 0.4);
                    border-radius: 16px;
                    background-color: rgba(66, 153, 225, 0.04);
                }
            """)
            self.icon_label.setText("⚙️")
            self.icon_label.setStyleSheet("font-size: 44px; margin-bottom: 2px;")
            self.title_label.setText("Updating Antigravity IDE")
            self.desc_label.setText(extra_info or "Initializing installation...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            
        elif state == "success":
            self.shadow.setColor(QColor(72, 187, 120, 180)) # Emerald green glow
            self.shadow.setBlurRadius(25)
            self.drop_zone.setStyleSheet("""
                #dropZone {
                    border: 1.5px solid rgba(72, 187, 120, 0.6);
                    border-radius: 16px;
                    background-color: rgba(72, 187, 120, 0.08);
                }
            """)
            self.icon_label.setText("✅")
            self.icon_label.setStyleSheet("font-size: 44px; margin-bottom: 2px;")
            self.title_label.setText("Update Successful!")
            self.desc_label.setText(extra_info or "IDE has been installed successfully.")
            self.progress_bar.setVisible(False)
            
            # Revert to idle state after 5 seconds
            QTimer.singleShot(5000, lambda: self.set_state("idle") if self.state == "success" else None)
            
        elif state == "error":
            self.shadow.setColor(QColor(245, 101, 101, 180)) # Coral red glow
            self.shadow.setBlurRadius(25)
            self.drop_zone.setStyleSheet("""
                #dropZone {
                    border: 1.5px solid rgba(245, 101, 101, 0.6);
                    border-radius: 16px;
                    background-color: rgba(245, 101, 101, 0.08);
                }
            """)
            self.icon_label.setText("⚠️")
            self.icon_label.setStyleSheet("font-size: 44px; margin-bottom: 2px;")
            self.title_label.setText("Update Failed")
            # Truncate text if it's too long to display cleanly
            display_err = extra_info
            if len(display_err) > 65:
                display_err = display_err[:62] + "..."
            self.desc_label.setText(display_err)
            self.progress_bar.setVisible(False)
            
            # Revert to idle state after 6 seconds
            QTimer.singleShot(6000, lambda: self.set_state("idle") if self.state == "error" else None)



    # Drag and Drop Events
    def dragEnterEvent(self, event):
        if self.state in ["updating", "success"]:
            event.ignore()
            return
            
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                file_path = urls[0].toLocalFile()
                filename = os.path.basename(file_path).lower()
                # Initial filter: must end in .tar.gz and contain "antigravity" in its name
                if filename.endswith(".tar.gz") and "antigravity" in filename:
                    event.acceptProposedAction()
                    self.set_state("drag_over")
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        if self.state == "drag_over":
            self.set_state("idle")
        event.accept()

    def dropEvent(self, event):
        if self.state in ["updating", "success"]:
            event.ignore()
            return
            
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                file_path = urls[0].toLocalFile()
                event.acceptProposedAction()
                self.process_file(file_path)
                return
        event.ignore()
        self.set_state("idle")

    # File dialog select
    def select_file_dialog(self):
        if self.state in ["updating", "success"]:
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Antigravity IDE Archive",
            "",
            "Tarball Archives (*.tar.gz)"
        )
        if file_path:
            self.process_file(file_path)

    # Core Logic
    def process_file(self, file_path):
        """Verifies tarball and triggers elevated background installation worker thread."""
        is_valid, err = self.verify_tarball_local(file_path)
        if not is_valid:
            self.set_state("error", err)
            return
            
        # Locate helper script in the same directory as main.py
        script_dir = os.path.dirname(os.path.abspath(__file__))
        helper_path = os.path.join(script_dir, "elevated_helper.py")
        
        self.worker = UpdateWorker(helper_path, file_path)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.set_state("updating")
        self.worker.start()

    def verify_tarball_local(self, file_path):
        """Verifies if the file is a valid .tar.gz archive and contains 'antigravity'."""
        if not file_path.endswith(".tar.gz"):
            return False, "File is not a .tar.gz archive."
        if not os.path.isfile(file_path):
            return False, "Selected file does not exist."
            
        try:
            if not tarfile.is_tarfile(file_path):
                return False, "File is not a valid tar archive."
                
            # Deep check inside archive
            with tarfile.open(file_path, "r:gz") as tar:
                names = tar.getnames()
                if not names:
                    return False, "Archive is empty."
                    
                has_antigravity = False
                for name in names:
                    if "antigravity" in name.lower():
                        has_antigravity = True
                        break
                        
                filename = os.path.basename(file_path).lower()
                if not has_antigravity and "antigravity" not in filename:
                    return False, "Archive does not contain 'antigravity' content."
            return True, ""
        except Exception as e:
            return False, f"Failed to verify tarball: {str(e)}"

    def on_worker_progress(self, msg):
        self.desc_label.setText(msg)

    def on_worker_finished(self, success, msg):
        if success:
            self.set_state("success", msg)
        else:
            self.set_state("error", msg)
            
    # Frameless window dragging events (for clicking on the header / main frame margins)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            # Don't start drag on interactive utility buttons
            if child == self.close_button:
                super().mousePressEvent(event)
                return
            self.drag_start = event.globalPosition().toPoint()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_start') and self.drag_start is not None:
            delta = event.globalPosition().toPoint() - self.drag_start
            if delta.manhattanLength() > 6:
                if self.windowHandle():
                    self.windowHandle().startSystemMove()
                    self.drag_start = None
                    event.accept()
                    return
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        self.drag_start = None
        super().mouseReleaseEvent(event)


def main():
    app = QApplication(sys.argv)
    window = DropZoneApp()
    
    # Position the dropzone in the bottom-right corner of the primary screen
    screen = app.primaryScreen().geometry()
    x = screen.width() - window.width() - 40
    y = screen.height() - window.height() - 80
    window.move(x, y)
    
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
