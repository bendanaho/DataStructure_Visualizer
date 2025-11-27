from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QGraphicsScene

from core.animation import AnimationToolkit


class BaseStructureView(QObject):
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

    def bind_canvas(self, view):
        """Attach the actual QGraphicsView when activated."""
        self._canvas = view
        if view:
            view.setScene(self.scene)

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