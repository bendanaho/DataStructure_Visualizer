from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QVariantAnimation,
    Qt,
)
from PyQt5.QtGui import QColor


class AnimationToolkit:
    """
    Helper factory to standardize animation creation and ensure
    global speed scaling is applied everywhere.
    """

    def __init__(self, global_ctrl):
        self.global_ctrl = global_ctrl

    def _duration(self, base_ms):
        return self.global_ctrl.scale_duration(base_ms)

    def move_item(self, item, end_pos, duration=800, easing=QEasingCurve.InOutCubic):
        anim = QPropertyAnimation(item, b"pos")
        anim.setDuration(self._duration(duration))
        anim.setEndValue(end_pos)
        anim.setEasingCurve(easing)
        return anim

    def fade_item(self, item, start=0.0, end=1.0, duration=800):
        anim = QPropertyAnimation(item, b"opacity")
        anim.setDuration(self._duration(duration))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        return anim

    def scale_item(self, item, start=1.0, end=1.0, duration=600):
        anim = QPropertyAnimation(item, b"scale")
        anim.setDuration(self._duration(duration))
        anim.setStartValue(start)
        anim.setEndValue(end)
        return anim

    def flash_brush(self, setter, start_color, end_color, duration=400, loops=1):
        """
        setter: callable receiving QColor (e.g. node.setBrushColor).
        """
        total = self._duration(duration)
        anim = QVariantAnimation()
        anim.setDuration(total)
        anim.setStartValue(start_color)
        anim.setEndValue(end_color)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        def _update(value):
            if isinstance(value, QColor):
                setter(value)

        anim.valueChanged.connect(_update)

        if loops > 1:
            seq = QSequentialAnimationGroup()
            for _ in range(loops):
                seq.addAnimation(anim)
                reverse = QVariantAnimation()
                reverse.setDuration(total)
                reverse.setStartValue(end_color)
                reverse.setEndValue(start_color)
                reverse.setEasingCurve(QEasingCurve.InOutQuad)
                reverse.valueChanged.connect(_update)
                seq.addAnimation(reverse)
            return seq
        return anim

    def pause(self, duration=150):
        pause = QVariantAnimation()
        pause.setDuration(self._duration(duration))
        pause.setStartValue(0)
        pause.setEndValue(0)
        return pause

    @staticmethod
    def parallel(*animations):
        group = QParallelAnimationGroup()
        for anim in animations:
            if anim:
                group.addAnimation(anim)
        return group

    @staticmethod
    def sequential(*animations):
        group = QSequentialAnimationGroup()
        for anim in animations:
            if anim:
                group.addAnimation(anim)
        return group