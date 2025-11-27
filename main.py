import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.global_ctrl import GlobalController
from widgets.graphics_view import CustomGraphicsView
from arrayviz.arr_ctrl import ArrayController
from linklist.sl_ctrl import LinkedListController
from stack.st_ctrl import StackController


class MainWindow(QMainWindow):
    """Main application window with left (visualization) and right (editor) panels."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt5 Data Structure Visualizer")
        self.resize(1280, 760)

        self.global_ctrl = GlobalController()
        self._active_name = None
        self._controllers = {}
        self._controller_order = []

        self._build_ui()
        self._register_controllers()
        self._connect_signals()

        # Apply stylesheet if available
        style_path = Path(__file__).parent / "resources" / "styles.qss"
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as handle:
                self.setStyleSheet(handle.read())

        # Activate default structure
        if self._controller_order:
            self.ds_combo.setCurrentIndex(0)
            self._activate_controller(self._controller_order[0])

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # Left panel (70%)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        ds_layout = QHBoxLayout()
        ds_layout.setContentsMargins(0, 0, 0, 0)
        ds_layout.setSpacing(6)
        ds_label = QLabel("Data Structure:")
        ds_label.setObjectName("structureSelectLabel")
        self.ds_combo = QComboBox()
        self.ds_combo.setObjectName("structureSelectCombo")
        ds_layout.addWidget(ds_label)
        ds_layout.addWidget(self.ds_combo, 1)
        left_layout.addLayout(ds_layout)

        self.graphics_view = CustomGraphicsView()
        left_layout.addWidget(self.graphics_view, 1)

        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        speed_layout = QHBoxLayout()
        speed_label = QLabel("Animation Speed")
        self.speed_value_label = QLabel("1.0×")
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(50, 300)  # maps to 0.5x – 3x
        self.speed_slider.setValue(100)
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_slider, 1)
        speed_layout.addWidget(self.speed_value_label)
        controls_layout.addLayout(speed_layout)

        self.controls_stack = QStackedWidget()
        controls_layout.addWidget(self.controls_stack)

        left_layout.addWidget(controls_container, 0)

        # Right panel (30%)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        note_label = QLabel("Prompt / Notes")
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("这里可以写自然语言描述或伪代码，暂不绑定逻辑。")
        right_layout.addWidget(note_label)
        right_layout.addWidget(self.editor, 1)

        root_layout.addWidget(left_panel, 14)
        root_layout.addWidget(right_panel, 6)

    def _register_controllers(self):
        linked_list = LinkedListController(self.global_ctrl)
        stack = StackController(self.global_ctrl)
        array = ArrayController(self.global_ctrl)

        self._add_controller("Linked List", linked_list)
        self._add_controller("Stack", stack)
        self._add_controller("Array", array)

    def _add_controller(self, name, controller):
        panel = controller.build_panel()
        idx = self.controls_stack.addWidget(panel)
        controller.panel_index = idx
        self._controllers[name] = controller
        self._controller_order.append(name)
        self.ds_combo.addItem(name)

    def _connect_signals(self):
        self.ds_combo.currentTextChanged.connect(self._activate_controller)
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)

    def _on_speed_slider_changed(self, value):
        speed = value / 100.0
        self.speed_value_label.setText(f"{speed:.1f}×")
        self.global_ctrl.set_speed(speed)

    def _activate_controller(self, name):
        if not name or name == self._active_name:
            return
        if name not in self._controllers:
            return

        if self._active_name:
            prev = self._controllers[self._active_name]
            prev.on_deactivate()

        controller = self._controllers[name]
        controller.on_activate(self.graphics_view)
        self.controls_stack.setCurrentIndex(controller.panel_index)
        self._active_name = name


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()