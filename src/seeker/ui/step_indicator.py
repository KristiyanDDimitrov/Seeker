"""A short sequence of steps as a row of status lamps joined by a
hairline: the onboarding wizard's progress.

A step behind you is lit (play), the step in front of you is a ring
(cue: it waits on you), and a step ahead stands by. A step skipped
stays standing by. The label beside each lamp changes weight with it,
so the current step never depends on telling the colours apart.
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QWidget

from seeker.ui import theme
from seeker.ui.plain_text import PlainLabel
from seeker.ui.status_lamp import (
    CUE_WAITING,
    PLAY,
    STANDBY,
    Lamp,
    StatusLamp,
)

# The shortest the hairline between two steps gets in a narrow window.
_CONNECTOR_MIN_WIDTH = 16


class StepIndicator(QWidget):
    def __init__(
            self,
            names: Sequence[str],
            parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._names = list(names)
        self._skipped: set[int] = set()
        self._current = 0
        self._lamps: list[StatusLamp] = []
        self._labels: list[PlainLabel] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_SM)
        for index, name in enumerate(self._names):
            if index:
                connector = QFrame()
                # QFrame#stepConnector in theme.py.
                connector.setObjectName("stepConnector")
                connector.setAttribute(
                    Qt.WidgetAttribute.WA_StyledBackground, True,
                )
                connector.setFixedHeight(1)
                connector.setMinimumWidth(_CONNECTOR_MIN_WIDTH)
                connector.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
                )
                layout.addWidget(connector)
            lamp = StatusLamp(STANDBY)
            label = PlainLabel(name)
            self._lamps.append(lamp)
            self._labels.append(label)
            layout.addWidget(lamp)
            layout.addWidget(label)

        self._render()

    def set_current(self, index: int) -> None:
        """Steps before `index` are done; `index` equal to the number
        of steps means every step is behind you."""
        self._current = index
        self._render()

    def mark_skipped(self, index: int) -> None:
        self._skipped.add(index)
        self._render()

    def lamps(self) -> list[Lamp]:
        return [lamp.lamp for lamp in self._lamps]

    def _state(self, index: int) -> str:
        if index in self._skipped:
            return "skipped"
        if index < self._current:
            return "done"
        if index == self._current:
            return "current"
        return "upcoming"

    def _render(self) -> None:
        lamp_for_state = {
            "done": PLAY,
            "current": CUE_WAITING,
            "upcoming": STANDBY,
            "skipped": STANDBY,
        }
        for index, (lamp, label) in enumerate(
                zip(self._lamps, self._labels, strict=True),
        ):
            state = self._state(index)
            lamp.set_lamp(lamp_for_state[state])
            # QLabel[stepState=...] in theme.py.
            theme.set_dynamic_property(label, "stepState", state)

        if self._current < len(self._names):
            self.setAccessibleName(
                f"Step {self._current + 1} of {len(self._names)}: "
                f"{self._names[self._current]}"
            )
            return
        skipped = [self._names[index] for index in sorted(self._skipped)]
        self.setAccessibleName(
            "Setup complete"
            + (f"; {', '.join(skipped)} skipped" if skipped else "")
        )
