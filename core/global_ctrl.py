from PyQt5.QtCore import QObject, pyqtSignal


class GlobalController(QObject):
    """
    Holds global playback speed and emits changes so that every animation
    can adjust its duration consistently.
    """

    speedChanged = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self._speed = 1.0  # multiplier: 1.0× by default

    @property
    def speed(self) -> float:
        return self._speed

    def set_speed(self, value: float):
        """Clamp and broadcast speed multiplier (0.5× – 3×)."""
        value = max(0.5, min(3.0, value))
        if abs(value - self._speed) > 1e-3:
            self._speed = value
            self.speedChanged.emit(self._speed)

    def scale_duration(self, base_ms: int) -> int:
        """
        Convert a base duration (ms) into the actual playback duration,
        treating the slider value as 'speed multiplier'. Higher speed → shorter duration.
        """
        if self._speed <= 0:
            return base_ms
        return max(1, int(base_ms / self._speed))