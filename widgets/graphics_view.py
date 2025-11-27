from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtGui import QWheelEvent


class CustomGraphicsView(QGraphicsView):
    """
    Graphics view with constrained wheel behaviour:
    - normal wheel: vertical panning only
    - Ctrl + wheel: zoom with factor 1.1
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(self.renderHints() | self.viewportUpdateMode())
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setInteractive(True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._vertical_scroll_step = 40

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.1 if angle > 0 else (1 / 1.1)
            self.scale(factor, factor)
        else:
            delta = event.angleDelta().y()
            self.translate(0, -delta * 0.2)
        event.accept()

    def ensureVisible(self, rect, xpad=20, ypad=20):
        """Expose ensureVisible publicly (parent already has)."""
        super().ensureVisible(rect, xpad, ypad)