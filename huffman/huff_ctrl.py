import json
from pathlib import Path
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from huffman.huff_model import HuffmanModel
from huffman.huff_view import HuffmanView


class HuffmanController(QWidget):
    """哈夫曼树可视化控制器，负责输入、步骤驱动与状态更新。"""

    def __init__(self, global_ctrl):
        super().__init__()
        self.global_ctrl = global_ctrl
        self.model = HuffmanModel()
        self.view = HuffmanView(global_ctrl)
        self._panel_locked = False

        self.panel = self._build_panel()

        self.view.interactionLocked.connect(self._on_lock_state)
        self.view.saveRequested.connect(self._save_to_file)
        self.view.loadRequested.connect(self._load_from_file)
        self.view.saveImageRequested.connect(self._save_as_image)  # [新增] 连接图片保存信号

    def _save_as_image(self):
        if self._panel_locked or self.view.is_busy():
            return

        # 简单检查是否有内容
        if not self.model.has_data:
            QMessageBox.information(self, "保存图片", "当前没有哈夫曼树内容，无需保存。")
            return

        # 1. 确定保存目录
        base_dir = Path(__file__).resolve().parents[1] / "save_as_photo" / "huff"
        base_dir.mkdir(parents=True, exist_ok=True)
        suggested = str(base_dir / "huffman_snapshot.png")

        # 2. 弹出文件选择框
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存为图片",
            suggested,
            "Images (*.png *.jpg *.bmp);;All Files (*)",
        )
        if not path:
            return

        # 3. 获取场景边界并渲染
        scene = self.view.scene
        content_rect = scene.itemsBoundingRect()

        # 如果场景为空或计算出的边界无效，给一个默认大小
        if content_rect.isNull():
            content_rect = QRectF(0, 0, 800, 600)

        # 添加一些内边距
        padding = 40
        target_rect = content_rect.adjusted(-padding, -padding, padding, padding)

        # 创建图片画布
        image = QImage(target_rect.size().toSize(), QImage.Format_ARGB32)
        image.fill(Qt.white)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 渲染场景
        scene.render(painter, target=QRectF(image.rect()), source=target_rect)
        painter.end()

        # 4. 保存文件
        if image.save(path):
            QMessageBox.information(self, "保存图片", f"图片已保存至：\n{path}")
        else:
            QMessageBox.critical(self, "保存图片", "图片保存失败，请检查路径或权限。")

    # ---------- UI 构建 ----------

    def _build_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        input_group = QGroupBox("输入与初始化")
        input_group.setStyleSheet("QGroupBox { color: white; }")
        input_layout = QFormLayout()
        input_layout.setContentsMargins(12, 8, 12, 12)
        input_layout.setSpacing(6)

        self.weights_edit = QLineEdit()
        self.weights_edit.setPlaceholderText("例如：5, 9, 12, 13, 16, 45 或 A:5, B:9")
        self.weights_edit.returnPressed.connect(self._on_initialize)
        input_layout.addRow("权重序列：", self.weights_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.build_btn = QPushButton("初始化")
        self.build_btn.clicked.connect(self._on_initialize)
        self.next_btn = QPushButton("下一步")
        self.next_btn.clicked.connect(self._on_next_step)
        btn_row.addWidget(self.build_btn)
        btn_row.addWidget(self.next_btn)
        input_layout.addRow(btn_row)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        status_group = QGroupBox("状态")
        status_group.setStyleSheet("QGroupBox { color: white; }")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(12, 8, 12, 12)
        self.stage_label = QLabel("尚未初始化")
        status_layout.addWidget(self.stage_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch(1)
        self._refresh_controls()
        return container

    def build_panel(self):
        return self.panel

    # ---------- 生命周期 ----------

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)

    def on_deactivate(self):
        pass

    # ---------- 事件处理 ----------

    def _on_initialize(self):
        if self._panel_locked:
            return
        text = self.weights_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Huffman", "请输入至少一个权重。")
            return
        try:
            self.model.initialize(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Huffman", str(exc))
            return

        snapshot = self.model.snapshot()
        self.view.animate_initialize(snapshot)
        self._update_status()
        self._refresh_controls()

    def _on_next_step(self):
        if self._panel_locked or self.view.is_busy():
            return
        if not self.model.has_data:
            QMessageBox.information(self, "Huffman", "请先初始化权重序列。")
            return

        stage = self.model.stage
        if stage == HuffmanModel.STAGE_SORTING:
            steps = []
            while True:
                before = self.model.snapshot()
                op = self.model.next_sort_operation()
                after = self.model.snapshot()
                if op is None:
                    break
                steps.append((before, after, op))

            if steps:
                self.view.animate_full_sorting(steps)
            else:
                QMessageBox.information(self, "Huffman", "排序阶段已完成，开始合并。")
        elif stage in (HuffmanModel.STAGE_BUILDING, HuffmanModel.STAGE_COMPLETE):
            if self.model.is_complete():
                QMessageBox.information(self, "Huffman", "哈夫曼树已经构建完成。")
                self._refresh_controls()
                return
            before = self.model.snapshot()
            info = self.model.perform_merge()
            after = self.model.snapshot()
            if info:
                self.view.animate_merge_step(before, after, info)
        else:
            QMessageBox.information(self, "Huffman", "请先初始化。")

        self._update_status()
        self._refresh_controls()

    def _save_to_file(self):
        if self._panel_locked or self.view.is_busy():
            return
        snapshot = self.model.snapshot()
        if not snapshot.get("nodes"):
            QMessageBox.information(self, "Huffman", "当前无可保存的节点。")
            return

        base_dir = Path(__file__).resolve().parents[1] / "save_file" / "huff"
        base_dir.mkdir(parents=True, exist_ok=True)
        suggested = str(base_dir / "huffman.json")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 Huffman 森林",
            suggested,
            "Huffman (*.json);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        payload = {
            "schema": "pyqt_ds_visualizer",
            "version": 1,
            "structure": "huff",
            "snapshot": snapshot,
        }

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"无法写入文件：\n{exc}")
            return

        QMessageBox.information(self, "Huffman", f"已保存到：\n{path}")

    def _load_from_file(self):
        if self._panel_locked or self.view.is_busy():
            return

        base_dir = Path(__file__).resolve().parents[1] / "save_file" / "huff"
        base_dir.mkdir(parents=True, exist_ok=True)

        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 Huffman 森林",
            str(base_dir),
            "Huffman (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "打开失败", f"无法读取文件：\n{exc}")
            return

        if (
            payload.get("schema") != "pyqt_ds_visualizer"
            or payload.get("structure") != "huff"
            or "snapshot" not in payload
        ):
            QMessageBox.critical(self, "打开失败", "文件格式不受支持。")
            return

        snapshot = payload["snapshot"]
        if not hasattr(self.model, "load_snapshot"):
            QMessageBox.critical(self, "加载失败", "当前模型未实现快照加载能力。")
            return

        self.model.load_snapshot(snapshot)
        fresh_snapshot = self.model.snapshot()

        if fresh_snapshot.get("nodes"):
            self.view.render_snapshot(fresh_snapshot)
        else:
            self.view.reset()

        self._update_status()
        self._refresh_controls()
        QMessageBox.information(self, "Huffman", "文件加载完成。")

    # ---------- 状态管理 ----------

    def _update_status(self):
        if not self.model.has_data:
            self.stage_label.setText("尚未初始化")
            return
        stage_map = {
            HuffmanModel.STAGE_SORTING: "阶段：排序（冒泡）",
            HuffmanModel.STAGE_BUILDING: "阶段：合并构建",
            HuffmanModel.STAGE_COMPLETE: "阶段：完成",
        }
        stage_text = stage_map.get(self.model.stage, "阶段：未知")
        forest_size = len(self.model.forest)
        self.stage_label.setText(f"{stage_text} | 森林棵数：{forest_size}")

    def _refresh_controls(self):
        ready = self.model.has_data
        complete = self.model.is_complete()
        locked = self._panel_locked
        self.build_btn.setDisabled(locked)
        self.weights_edit.setDisabled(locked)
        self.next_btn.setDisabled(locked or not ready or complete)

    def _on_lock_state(self, locked: bool):
        self._panel_locked = locked
        self._refresh_controls()