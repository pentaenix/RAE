from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox

from ....core.assets import Asset
from ....core.modules.types import PreviewContext, PreviewRoute
from ....core.qthread import launch_qthread
from ....install import project_root
from ..service import build_model_glb
from ..snap_courses import SNAP_COURSE_MAGIC
from ..snap_scene import build_snap_course_preview


class SwitchModelPreviewWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, descriptor: dict, output_dir: Path, *, temporary: TemporaryDirectory | None = None):
        super().__init__()
        self.descriptor = descriptor
        self.output_dir = output_dir
        self.temporary = temporary

    def run(self) -> None:
        try:
            build = build_snap_course_preview if self.descriptor.get("type") == "snap_course_preview" else build_model_glb
            glb = build(self.descriptor, self.output_dir / "preview.glb", progress=self.progress.emit)
            self.finished_ok.emit(str(glb))
        except Exception as exc:
            self.failed.emit(str(exc))


class SwitchModelModule:
    platform_id = "switch"

    def _descriptor(self, asset: Asset) -> dict:
        try:
            return json.loads(asset.data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def preview_route(self, asset: Asset) -> PreviewRoute | None:
        if asset.magic in {"TRMD", SNAP_COURSE_MAGIC}:
            return PreviewRoute.MODEL
        return None

    def preview(self, ctx: PreviewContext, asset: Asset) -> bool:
        if self.preview_route(asset) is None:
            return False
        descriptor = self._descriptor(asset)
        is_course = asset.magic == SNAP_COURSE_MAGIC
        expected_type = "snap_course_preview" if is_course else "trinity_file"
        if descriptor.get("type") != expected_type:
            return False
        window = ctx.window
        temporary = None
        if is_course:
            web_view = getattr(window.preview, "_web_view", None)
            if web_view is None or not web_view.is_available():
                window.preview.show_message("Snap course free camera requires the Qt WebEngine preview.")
                return True
            temporary = TemporaryDirectory(prefix="rae_snap_preview_")
            output_dir = Path(temporary.name)
        else:
            output_dir = project_root() / "exports" / "switch_model_previews" / asset.asset_id
            output_dir.mkdir(parents=True, exist_ok=True)
        worker = SwitchModelPreviewWorker(descriptor, output_dir, temporary=temporary)
        launch_qthread(window, "_switch_preview_worker", worker)
        if hasattr(window, "_update_status"):
            worker.progress.connect(window._update_status)
        if is_course:
            worker.finished_ok.connect(lambda glb: self._show_course(window, asset, glb, worker))
            worker.finished.connect(worker.deleteLater)
        else:
            worker.finished_ok.connect(lambda glb: self._show(window, asset, glb))
        worker.failed.connect(
            lambda message: QMessageBox.critical(window, "Switch model preview failed", message)
        )
        worker.start()
        return True

    def _show_course(self, window, asset: Asset, glb_path: str, worker: SwitchModelPreviewWorker) -> None:
        selected = window.selected_asset()
        if selected is None or selected.asset_id != asset.asset_id or selected.data != asset.data:
            return
        # Keep the temporary source alive for WebEngine's asynchronous reads.
        window._switch_course_preview_dir = worker.temporary
        worker.temporary = None
        self._show(window, asset, glb_path)

    def _show(self, window, asset: Asset, glb_path: str) -> None:
        path = Path(glb_path)
        if hasattr(window, "_update_status"):
            window._update_status(f"Switch model preview ready: {path.name}")
        if hasattr(window, "_load_model_preview_glb"):
            if asset.magic == SNAP_COURSE_MAGIC:
                window._load_model_preview_glb(
                    path, asset_id=asset.asset_id, fallback_textures=[], texture_by_name={}, texture_bind_order=[],
                )
            else:
                window._load_model_preview_glb(path, asset_id=asset.asset_id)
            if hasattr(window, "_update_preview_details"):
                window._update_preview_details(asset)
            return
        preview = getattr(window, "preview", None)
        if preview is not None and hasattr(preview, "load_glb"):
            preview.load_glb(path)

    def supports_model_inspector(self, asset: Asset) -> bool:
        return asset.magic == "TRMD"

    def home_package_stub_message(self, asset: Asset) -> str | None:
        return None
