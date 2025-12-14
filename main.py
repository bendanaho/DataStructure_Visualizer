import os
from dotenv import load_dotenv
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from core.global_ctrl import GlobalController
from core.command_parser import CommandParser, CommandParserError
from core.llm_client import LLMClient
from widgets.graphics_view import CustomGraphicsView
from arrayviz.arr_ctrl import ArrayController
from linklist.sl_ctrl import LinkedListController
from stack.st_ctrl import StackController
from bst.bst_ctrl import BSTController
from bst.avl_ctrl import AVLController
from huffman.huff_ctrl import HuffmanController

# ---------- LLM 配置信息（DeepSeek API） ----------
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


class LLMWorker(QThread):
    """在后台线程调用 LLM，避免阻塞 GUI。"""

    success = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client: LLMClient, prompt: str, structure: str):
        super().__init__()
        self._client = client
        self._prompt = prompt
        self._structure = structure

    def run(self):
        try:
            result = self._client.translate_to_dsl(self._prompt, self._structure)
            self.success.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


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
        self.command_parser: CommandParser = None
        self.llm_client: LLMClient = None
        self._llm_worker: LLMWorker = None

        # ---------- DSL 语法速查 ----------
        self.syntax_reference = {
            "Array": (
                "CREATE [1, 2, 3]\n"
                "APPEND 5\n"
                "INSERT 0 10\n"
                "UPDATE 1 99\n"
                "DELETE 0\n"
                "CLEAR"
            ),
            "Linked List": (
                "CREATE [1, 2, 3]\n"
                "APPEND 5\n"
                "INSERT 0 10\n"
                "UPDATE 1 99\n"
                "DELETE 0\n"
                "CLEAR"
            ),
            "Stack": (
                "PUSH 10\n"
                "POP\n"
                "POP 2\n"
                "CLEAR"
            ),
            "BST": (
                "CREATE [5, 3, 7]\n"
                "INSERT 4\n"
                "DELETE 3\n"
                "FIND 7\n"
                "CLEAR"
            ),
            "Huffman": (
                "INIT A:5, B:2, C:1\n"
                "STEP\n"
                "RESET"
            ),
        }

        self._build_ui()
        self._register_controllers()
        self.command_parser = CommandParser(self)

        if DEEPSEEK_API_KEY:
            self.llm_client = LLMClient(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)

        self._connect_signals()
        self._setup_shortcuts()

        style_path = Path(__file__).parent / "resources" / "styles.qss"
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as handle:
                self.setStyleSheet(handle.read())

        if self._controller_order:
            self.ds_combo.setCurrentIndex(0)
            self._activate_controller(self._controller_order[0])

    # ---------- UI 构建 ----------

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # 左侧
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
        self.speed_slider.setRange(50, 300)
        self.speed_slider.setValue(100)
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_slider, 1)
        speed_layout.addWidget(self.speed_value_label)
        controls_layout.addLayout(speed_layout)

        self.controls_stack = QStackedWidget()
        controls_layout.addWidget(self.controls_stack)

        left_layout.addWidget(controls_container, 0)

        # 右侧
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        note_label = QLabel("Prompt / Notes")
        self.editor = QTextEdit()
        editor_font = self.editor.font()
        editor_font.setPointSize(11)
        self.editor.setFont(editor_font)
        self.editor.setPlaceholderText("这里可以写 DSL 或自然语言描述。")

        self.syntax_hint_label = QLabel("当前语法参考:\n（尚未选择数据结构）")
        self.syntax_hint_label.setWordWrap(True)
        syntax_font = self.syntax_hint_label.font()
        syntax_font.setPointSize(10)
        self.syntax_hint_label.setFont(syntax_font)
        self.syntax_hint_label.setStyleSheet("color: gray;")

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.run_btn = QPushButton("执行 (Run)")
        self.ai_btn = QPushButton("AI 转换 (Ask AI)")
        button_row.addWidget(self.run_btn)
        button_row.addWidget(self.ai_btn)

        right_layout.addWidget(note_label)
        right_layout.addWidget(self.syntax_hint_label)
        right_layout.addWidget(self.editor, 1)
        right_layout.addLayout(button_row)

        root_layout.addWidget(left_panel, 14)
        root_layout.addWidget(right_panel, 6)

    # ---------- 控制器注册 ----------

    def _register_controllers(self):
        linked_list = LinkedListController(self.global_ctrl)
        stack = StackController(self.global_ctrl)
        array = ArrayController(self.global_ctrl)
        bst = BSTController(self.global_ctrl)
        huffman = HuffmanController(self.global_ctrl)
        avl = AVLController(self.global_ctrl)

        self._add_controller("Linked List", linked_list)
        self._add_controller("Stack", stack)
        self._add_controller("Array", array)
        self._add_controller("BST", bst)
        self._add_controller("Huffman", huffman)
        self._add_controller("AVL", avl)

    def _add_controller(self, name, controller):
        panel = controller.build_panel()
        idx = self.controls_stack.addWidget(panel)
        controller.panel_index = idx
        self._controllers[name] = controller
        self._controller_order.append(name)
        self.ds_combo.addItem(name)

    # ---------- 信号与快捷键 ----------

    def _connect_signals(self):
        self.ds_combo.currentTextChanged.connect(self._activate_controller)
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        self.run_btn.clicked.connect(self._on_run_commands)
        self.ai_btn.clicked.connect(self._on_ai_translate)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=self._on_run_commands)
        QShortcut(QKeySequence(Qt.Key_F2), self, activated=self._on_ai_translate)

    # ---------- 控制器生命周期 ----------

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

        self.syntax_hint_label.setText(self._build_syntax_hint_text(name))

    # ---------- DSL & AI ----------

    def _show_black_message(self, icon: QMessageBox.Icon, title: str, message: str):
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStyleSheet("QLabel { color: black; }")
        box.exec_()

    def _show_black_critical(self, title: str, message: str):
        self._show_black_message(QMessageBox.Critical, title, message)

    def _on_run_commands(self):
        if self.command_parser is None:
            QMessageBox.warning(self, "DSL", "指令解析器尚未就绪。")
            return
        script = self.editor.toPlainText()
        if not script.strip():
            QMessageBox.information(self, "DSL", "请先输入 DSL 指令。")
            return
        try:
            self.command_parser.parse_and_execute(script)
        except CommandParserError as exc:
            self._show_black_critical("DSL 执行失败", str(exc))
        except Exception as exc:
            self._show_black_critical("DSL 执行失败", str(exc))

    def _on_ai_translate(self):
        if not self.llm_client:
            self._show_black_message(
                QMessageBox.Warning,
                "AI 转换",
                "尚未配置 LLM（请设置 DEEPSEEK_API_KEY）。",
            )
            return

        prompt_raw = self.editor.toPlainText()
        self.editor.clear()
        prompt = prompt_raw.strip()

        if not prompt:
            self._show_black_message(
                QMessageBox.Information, "AI 转换", "请先输入自然语言描述。"
            )
            return
        if self._llm_worker and self._llm_worker.isRunning():
            self._show_black_message(
                QMessageBox.Information, "AI 转换", "已在请求中，请稍候。"
            )
            return

        structure_hint = self._active_name or ""
        self.ai_btn.setDisabled(True)
        self._llm_worker = LLMWorker(self.llm_client, prompt, structure_hint)
        self._llm_worker.success.connect(self._on_ai_success)
        self._llm_worker.error.connect(self._on_ai_error)
        self._llm_worker.finished.connect(self._on_ai_worker_finished)
        self._llm_worker.start()

    def _on_ai_success(self, dsl_text: str):
        current = self.editor.toPlainText().strip()
        merged = dsl_text if not current else f"{current}\n{dsl_text}"
        self.editor.setPlainText(merged)
        self._show_black_message(
            QMessageBox.Information, "AI 转换", "已生成 DSL 指令，并写入编辑器。"
        )

    def _on_ai_error(self, message: str):
        self._show_black_critical("AI 转换失败", message)

    def _on_ai_worker_finished(self):
        self.ai_btn.setDisabled(False)
        self._llm_worker = None

    # ---------- 供 CommandParser 调用的辅助 ----------

    @property
    def active_structure_name(self) -> str:
        return self._active_name

    def get_controller(self, name: str):
        return self._controllers.get(name)

    def ensure_structure_active(self, name: str):
        if name and name in self._controllers:
            self._activate_controller(name)

    # ---------- 语法提示辅助 ----------

    def _build_syntax_hint_text(self, name: str) -> str:
        hint_body = self.syntax_reference.get(name, "（暂无该数据结构的语法参考）")
        return f"当前语法参考:\n{hint_body}"

    # ---------- 主流程 ----------

    def build_panel(self):
        return self.panel


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()