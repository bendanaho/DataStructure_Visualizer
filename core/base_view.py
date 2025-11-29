from PyQt5.QtCore import QObject, pyqtSignal, QRectF, QPointF, QVariantAnimation
import math
from PyQt5.QtWidgets import QGraphicsScene

from core.animation import AnimationToolkit


class BaseStructureView(QObject):
    interactionLocked = pyqtSignal(bool)
    """
    Base class for structure-specific views, providing:
    - shared QGraphicsScene
    - animation helper + lifecycle management
    - interaction locking to keep controllers in sync
    """

    interactionLocked = pyqtSignal(bool)

    def __init__(self, global_ctrl):
        super().__init__()
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-200, -200, 1200, 800)
        self.anim = AnimationToolkit(global_ctrl)
        self._locked = False
        self._running = []
        self._canvas = None  # bound QGraphicsView (optional)
        self._base_scene_rect = QRectF(self.scene.sceneRect())
        self._view_anim = None
        self._max_view_scale = 1  # 防止节点过少时放得太大

    def bind_canvas(self, view):
        self._cancel_view_anim()
        self._canvas = view
        if view:
            view.setScene(self.scene)
            view.resetTransform()

    def auto_fit_view(self, padding=120, skip_if=None):
        if skip_if and skip_if():
            return

        if not self._canvas:
            return

        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            target_rect = QRectF(self._base_scene_rect)
        else:
            padded = QRectF(items_rect)
            padded.adjust(-padding, -padding, padding, padding)
            target_rect = (
                QRectF(self._base_scene_rect)
                if self._base_scene_rect.contains(padded)
                else padded
            )

        self.scene.setSceneRect(target_rect)
        self._animate_view_to_rect(target_rect)

    def _animate_view_to_rect(self, target_rect, duration=360):
        if not self._canvas or target_rect.isNull():
            return

        viewport = self._canvas.viewport().rect()
        if viewport.isNull():
            return

        current_center = self._canvas.mapToScene(viewport.center())
        target_center = target_rect.center()

        current_scale = self._canvas.transform().m11()
        if not math.isfinite(current_scale) or abs(current_scale) < 1e-4:
            current_scale = 1.0

        width = max(target_rect.width(), 1.0)
        height = max(target_rect.height(), 1.0)
        desired_scale = min(viewport.width() / width, viewport.height() / height)
        desired_scale = min(max(0.05, desired_scale), self._max_view_scale)

        center_delta = (target_center - current_center).manhattanLength()
        scale_delta = abs(desired_scale - current_scale)

        # 只有在目标与当前视图完全一致时直接退出，其余情况一律执行动画，
        # 这样纯平移场景也能看到过渡效果。
        if center_delta < 1e-6 and scale_delta < 1e-6:
            return

        self._cancel_view_anim()

        anim = QVariantAnimation(self)
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _step(progress):
            scale = current_scale + (desired_scale - current_scale) * progress
            cx = current_center.x() + (target_center.x() - current_center.x()) * progress
            cy = current_center.y() + (target_center.y() - current_center.y()) * progress
            self._apply_view_state(scale, QPointF(cx, cy))

        def _finish():
            self._apply_view_state(desired_scale, target_center)
            self._view_anim = None

        anim.valueChanged.connect(_step)
        anim.finished.connect(_finish)
        self._view_anim = anim
        anim.start()

    def _apply_view_state(self, scale, center_point):
        if not self._canvas:
            return
        self._canvas.resetTransform()
        self._canvas.scale(scale, scale)
        self._canvas.centerOn(center_point)

    def _cancel_view_anim(self):
        if self._view_anim:
            self._view_anim.stop()
            self._view_anim = None

    def lock_interactions(self):
        if not self._locked:
            self._locked = True
            self.interactionLocked.emit(True)

    def unlock_interactions(self):
        if self._locked:
            self._locked = False
            self.interactionLocked.emit(False)

    def _track_animation(self, animation, finalizer=None):
        """
        Keeps references so that animations are not garbage collected.
        Optionally runs a callback after completion.
        """
        if animation is None:
            return

        self.lock_interactions()
        self._running.append(animation)

        def _cleanup():
            if animation in self._running:
                self._running.remove(animation)
            if not self._running:
                self.unlock_interactions()
            if finalizer:
                finalizer()

        animation.finished.connect(_cleanup)
        animation.start()

    def ensure_visible(self, rect, xpad=20, ypad=20):
        if self._canvas:
            self._canvas.ensureVisible(rect, xpad, ypad)