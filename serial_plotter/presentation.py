"""Trade-fair presentation mode: cycles live plot with image/video slides."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


_VALID_KINDS = {"plot", "image", "video"}
_DEFAULT_DURATION_MS = 10_000


class PresentationConfigError(ValueError):
    """Raised when a presentation JSON config is malformed."""


@dataclass
class Slide:
    kind: str
    path: Optional[Path]
    duration_ms: int
    loop: bool = False


@dataclass
class PresentationConfig:
    default_duration_ms: int
    slides: list[Slide]
    base_dir: Path = field(default_factory=Path.cwd)

    @classmethod
    def from_json(cls, json_path: Path) -> "PresentationConfig":
        if not json_path.is_file():
            raise FileNotFoundError(json_path)

        try:
            raw = json.loads(json_path.read_text())
        except json.JSONDecodeError as e:
            raise PresentationConfigError(f"JSON parse error: {e}") from e

        if not isinstance(raw, dict):
            raise PresentationConfigError("top-level JSON must be an object")

        default_duration = raw.get("default_duration_ms", _DEFAULT_DURATION_MS)
        if not isinstance(default_duration, int) or default_duration <= 0:
            raise PresentationConfigError(
                "default_duration_ms must be a positive integer"
            )

        raw_slides = raw.get("slides")
        if not isinstance(raw_slides, list) or not raw_slides:
            raise PresentationConfigError("slides must be a non-empty list")

        base_dir = json_path.parent
        slides: list[Slide] = []
        for i, entry in enumerate(raw_slides):
            if not isinstance(entry, dict):
                raise PresentationConfigError(f"slide {i}: must be an object")

            kind = entry.get("type")
            if kind not in _VALID_KINDS:
                raise PresentationConfigError(
                    f"slide {i}: type must be one of {sorted(_VALID_KINDS)}"
                )

            duration = entry.get("duration_ms", default_duration)
            if not isinstance(duration, int) or duration <= 0:
                raise PresentationConfigError(
                    f"slide {i}: duration_ms must be a positive integer"
                )

            loop = entry.get("loop", False)
            if not isinstance(loop, bool):
                raise PresentationConfigError(f"slide {i}: loop must be a boolean")

            path: Optional[Path] = None
            if kind in ("image", "video"):
                raw_path = entry.get("path")
                if not isinstance(raw_path, str) or not raw_path:
                    raise PresentationConfigError(
                        f"slide {i}: {kind} slide requires non-empty 'path'"
                    )
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = (base_dir / resolved).resolve()
                if not resolved.is_file():
                    print(
                        f"[presentation] skipping slide {i}: "
                        f"{resolved} not found",
                        file=sys.stderr,
                    )
                    continue
                path = resolved

            slides.append(
                Slide(kind=kind, path=path, duration_ms=duration, loop=loop)
            )

        if not slides:
            raise PresentationConfigError(
                "no usable slides (all media paths missing?)"
            )

        return cls(
            default_duration_ms=default_duration,
            slides=slides,
            base_dir=base_dir,
        )


class _ImageSlideWidget(QWidget):
    """QLabel host that rescales its pixmap on resize, aspect-preserved."""

    def __init__(self, pixmap: QPixmap, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pixmap = pixmap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background-color: black;")
        layout.addWidget(self._label)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap.isNull():
            return
        target = self._label.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        self._label.setPixmap(
            self._pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._rescale()


class PresentationController:
    """Drives a QStackedWidget cycling through plot / image / video slides."""

    def __init__(self, config: PresentationConfig, plot_widget: QWidget):
        self._cfg = config
        self._plot = plot_widget

        self._stack = QStackedWidget()
        self._stack.addWidget(plot_widget)  # page 0

        self._timer = QTimer(self._stack)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._audio_out = QAudioOutput()
        self._audio_out.setMuted(True)
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(self._audio_out)
        self._media_player.mediaStatusChanged.connect(self._on_media_status)
        self._media_player.errorOccurred.connect(self._on_media_error)

        self._slide_pages: list[int] = []  # slide index -> stack page index
        self._current_slide: Optional[Slide] = None
        self._current = 0
        self._paused = False
        self._active = False

        self._pause_button: Optional[QPushButton] = None

        self._build_pages()

    def _build_pages(self) -> None:
        for slide in self._cfg.slides:
            if slide.kind == "plot":
                self._slide_pages.append(0)
            elif slide.kind == "image":
                pixmap = QPixmap(str(slide.path))
                page = _ImageSlideWidget(pixmap)
                self._slide_pages.append(self._stack.addWidget(page))
            elif slide.kind == "video":
                page = QWidget()
                layout = QVBoxLayout(page)
                layout.setContentsMargins(0, 0, 0, 0)
                video = QVideoWidget(page)
                layout.addWidget(video)
                page.setStyleSheet("background-color: black;")
                page.setProperty("video_widget_ptr", id(video))
                # Stash the QVideoWidget on the page for later lookup.
                page._video_widget = video  # type: ignore[attr-defined]
                self._slide_pages.append(self._stack.addWidget(page))

    def stack(self) -> QStackedWidget:
        return self._stack

    def build_controls(self, toggle_fullscreen_cb) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(4, 2, 4, 2)

        prev_btn = QPushButton("\u25C0  Prev")
        prev_btn.setFixedWidth(90)
        prev_btn.clicked.connect(self.prev)
        prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        pause_btn = QPushButton("Pause")
        pause_btn.setFixedWidth(90)
        pause_btn.clicked.connect(self.toggle_pause)
        pause_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pause_button = pause_btn

        next_btn = QPushButton("Next  \u25B6")
        next_btn.setFixedWidth(90)
        next_btn.clicked.connect(self.next)
        next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        fs_btn = QPushButton("Fullscreen")
        fs_btn.setFixedWidth(110)
        fs_btn.clicked.connect(toggle_fullscreen_cb)
        fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout.addStretch()
        layout.addWidget(prev_btn)
        layout.addWidget(self._pause_button)
        layout.addWidget(next_btn)
        layout.addWidget(fs_btn)
        layout.addStretch()
        return panel

    def _refresh_pause_label(self) -> None:
        if self._pause_button is None:
            return
        if self._active and not self._paused:
            self._pause_button.setText("Pause")
        else:
            self._pause_button.setText("Play")

    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        self._active = True
        self._paused = False
        self._current = 0
        self._show(0)
        self._refresh_pause_label()

    def stop(self) -> None:
        self._active = False
        self._paused = False
        self._timer.stop()
        self._media_player.stop()
        self._media_player.setSource(QUrl())
        self._current_slide = None
        self._stack.setCurrentIndex(0)
        self._refresh_pause_label()

    def toggle_pause(self) -> None:
        if not self._active:
            self.start()
            return
        if self._paused:
            self._paused = False
            if self._current_slide is not None:
                self._timer.start(self._current_slide.duration_ms)
        else:
            self._paused = True
            self._timer.stop()
        self._refresh_pause_label()

    def next(self) -> None:
        if not self._active:
            self.start()
            return
        self._current = (self._current + 1) % len(self._cfg.slides)
        self._show(self._current)

    def prev(self) -> None:
        if not self._active:
            self.start()
            return
        self._current = (self._current - 1) % len(self._cfg.slides)
        self._show(self._current)

    def handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Right:
            self.next()
            return True
        if key == Qt.Key.Key_Left:
            self.prev()
            return True
        if key == Qt.Key.Key_Space:
            self.toggle_pause()
            return True
        return False

    def cleanup(self) -> None:
        self._timer.stop()
        self._media_player.stop()
        self._media_player.setSource(QUrl())
        self._active = False

    def _advance(self) -> None:
        if not self._active or self._paused:
            return
        self.next()

    def _show(self, idx: int) -> None:
        self._timer.stop()
        self._media_player.stop()

        slide = self._cfg.slides[idx]
        self._current_slide = slide
        page_idx = self._slide_pages[idx]
        self._stack.setCurrentIndex(page_idx)

        if slide.kind == "video" and slide.path is not None:
            page = self._stack.widget(page_idx)
            video_widget = getattr(page, "_video_widget", None)
            if video_widget is not None:
                self._media_player.setVideoOutput(video_widget)
            self._media_player.setSource(QUrl.fromLocalFile(str(slide.path)))
            self._media_player.play()

        if not self._paused:
            self._timer.start(slide.duration_ms)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and self._current_slide is not None
            and self._current_slide.kind == "video"
            and self._current_slide.loop
        ):
            self._media_player.setPosition(0)
            self._media_player.play()

    def _on_media_error(
        self, error: QMediaPlayer.Error, error_string: str = ""
    ) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        print(
            f"[presentation] media error on slide {self._current}: {error_string}",
            file=sys.stderr,
        )
        if self._active and not self._paused:
            self._advance()
