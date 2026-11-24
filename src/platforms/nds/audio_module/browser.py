"""Search, audition and export entries in a Nintendo DS sound archive."""
from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from ..audio import export_sounds
from ..audio_archives import get_sdat_file, iter_swar_swavs, sdat_sound_symbols


class SoundArchiveDialog(QDialog):
    def __init__(self, parent, data: bytes, output: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Nintendo DS sounds")
        self.resize(580, 500)
        self.data = data
        self.output = output
        self.sounds = sdat_sound_symbols(data)
        self.preview_dir = tempfile.TemporaryDirectory(prefix="rae-sound-preview-")
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.previewing = False
        self.written: list[Path] = []
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.errorOccurred.connect(lambda _, message: self.status.setText(message))

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter sounds, e.g. SE_FLD")
        layout.addWidget(self.search)
        self.items = QListWidget()
        self.items.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.items)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.play = QPushButton("Play")
        stop = QPushButton("Stop")
        self.save = QPushButton("Export WAV")
        close = QPushButton("Close")
        for button in (self.play, stop, self.save, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.search.textChanged.connect(self.filter_items)
        self.items.itemDoubleClicked.connect(lambda _: self.start(True))
        self.items.itemSelectionChanged.connect(self.update_buttons)
        self.play.clicked.connect(lambda: self.start(True))
        stop.clicked.connect(self.player.stop)
        self.save.clicked.connect(lambda: self.start(False))
        close.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.setInterval(75)
        self.timer.timeout.connect(self.finish_export)
        self.filter_items("")

    def update_buttons(self):
        count = len(self.items.selectedItems())
        self.play.setEnabled(self.pending is None and count == 1)
        self.save.setEnabled(self.pending is None and count > 0)

    def filter_items(self, query):
        self.items.clear()
        terms = query.lower().split()
        for sound in self.sounds:
            name = f"{sound['name']}  ·  {sound['kind']} {sound['index']}"
            if sound["kind"] == "SSAR":
                name += f"  ·  {sound['archiveName']}"
            if all(term in name.lower() for term in terms):
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, sound)
                self.items.addItem(item)
        self.update_buttons()

    def choose_sample(self, sound):
        source = get_sdat_file(self.data, sound["fileId"])
        waves = iter_swar_swavs(source.data) if source else []
        if not waves:
            self.status.setText("No valid samples in this wave archive.")
            return None
        if len(waves) == 1:
            return {**sound, "sampleIndex": waves[0].index}

        self.items.clear()
        for entry in waves:
            item = QListWidgetItem(f"{sound['name']}  ·  sample {entry.index}")
            item.setData(Qt.ItemDataRole.UserRole, {**sound, "sampleIndex": entry.index})
            self.items.addItem(item)
        self.items.setCurrentRow(0)
        self.status.setText("Select a sample. Edit the filter to return to the sound list.")
        return None

    def start(self, preview: bool):
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.items.selectedItems()]
        if self.pending is not None or not selected or (preview and len(selected) != 1):
            return
        if preview and selected[0]["kind"] == "SWAR" and "sampleIndex" not in selected[0]:
            sound = self.choose_sample(selected[0])
            if sound is None:
                return
            selected = [sound]
        self.player.stop()
        self.player.setSource(QUrl())
        if preview:
            folder = Path(self.preview_dir.name)
        elif self.output:
            folder = self.output
        else:
            chosen = QFileDialog.getExistingDirectory(self, "Choose WAV export folder")
            if not chosen:
                return
            folder = Path(chosen)
        self.previewing = preview
        self.pending = self.worker.submit(export_sounds, self.data, selected, folder)
        self.status.setText("Rendering audio…")
        self.update_buttons()
        self.timer.start()

    def finish_export(self):
        if self.pending is None or not self.pending.done():
            return
        self.timer.stop()
        pending, self.pending = self.pending, None
        try:
            files = pending.result()
            if self.previewing:
                self.player.setSource(QUrl.fromLocalFile(str(files[0].resolve())))
                self.player.play()
                self.status.setText(files[0].stem)
            else:
                self.written.extend(files)
                self.status.setText(f"Exported {len(files)} WAV file(s) to {files[0].parent}")
        except Exception as exc:
            self.status.setText(str(exc))
        self.update_buttons()

    def done(self, result):
        if self.pending is not None:
            return
        self.player.stop()
        self.player.setSource(QUrl())
        self.worker.shutdown()
        self.preview_dir.cleanup()
        super().done(result)
        self.deleteLater()
