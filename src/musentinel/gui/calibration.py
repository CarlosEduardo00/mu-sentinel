"""Tela de calibração: tira print da janela, desenha a região de cada campo,
mostra a leitura ao vivo, ensina valores e salva/exporta o perfil.

Uso: python -m musentinel.gui.calibration
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import paths, winapi
from ..core.capture import CaptureError, make_backend
from ..core.perception import glyphs
from ..core.perception.profile import FIELD_KINDS, FIELD_LABELS_PT, Profile, Roi, default_profile
from ..core.perception.reader import HudReader
from .qtutil import bgr_to_pixmap

FIELDS = list(FIELD_LABELS_PT)
LIVE_FIELDS = ("hp", "coords", "exp", "hunting_time", "map", "hunting_log_title")


class Canvas(QWidget):
    """Mostra o print escalado e deixa desenhar um retângulo com o mouse."""

    roi_drawn = Signal(object)  # Roi

    def __init__(self):
        super().__init__()
        self.image: np.ndarray | None = None
        self.pixmap = None
        self.rois: dict[str, Roi] = {}
        self.selected: str | None = None
        self._drag_start: QPoint | None = None
        self._drag_now: QPoint | None = None
        self.setMinimumSize(640, 480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_image(self, img: np.ndarray) -> None:
        self.image = img
        self.pixmap = bgr_to_pixmap(img)
        self.update()

    def _geom(self) -> tuple[float, int, int]:
        h, w = self.image.shape[:2]
        s = min(self.width() / w, self.height() / h)
        ox = int((self.width() - w * s) / 2)
        oy = int((self.height() - h * s) / 2)
        return s, ox, oy

    def to_image(self, p: QPoint) -> tuple[int, int]:
        s, ox, oy = self._geom()
        h, w = self.image.shape[:2]
        x = int(round((p.x() - ox) / s))
        y = int(round((p.y() - oy) / s))
        return max(0, min(w, x)), max(0, min(h, y))

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 30))
        if self.pixmap is None:
            p.setPen(Qt.GlobalColor.lightGray)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Escolha uma janela e clique em Capturar")
            return
        s, ox, oy = self._geom()
        h, w = self.image.shape[:2]
        p.drawPixmap(QRect(ox, oy, int(w * s), int(h * s)), self.pixmap)
        for name, r in self.rois.items():
            sel = name == self.selected
            p.setPen(QPen(QColor(255, 60, 60) if sel else QColor(255, 220, 0), 2 if sel else 1))
            p.drawRect(QRect(ox + int(r.x * s), oy + int(r.y * s), int(r.w * s), int(r.h * s)))
            p.drawText(ox + int(r.x * s), oy + int(r.y * s) - 2, name)
        if self._drag_start and self._drag_now:
            p.setPen(QPen(QColor(0, 200, 255), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRect(self._drag_start, self._drag_now).normalized())

    def mousePressEvent(self, e):  # noqa: N802
        if self.image is not None and self.selected and e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
            self._drag_now = self._drag_start

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag_start:
            self._drag_now = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if not self._drag_start:
            return
        x0, y0 = self.to_image(self._drag_start)
        x1, y1 = self.to_image(e.position().toPoint())
        self._drag_start = self._drag_now = None
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 >= 4 and y1 - y0 >= 4:
            self.roi_drawn.emit(Roi(x=x0, y=y0, w=x1 - x0, h=y1 - y0))
        self.update()


class CalibrationWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MU Sentinel — calibração")
        self.capture = make_backend("auto")
        self.profile: Profile = paths.load_or_default_profile()
        self.reader = HudReader(self.profile)
        self.frame: np.ndarray | None = None
        self.dirty = False

        central = QWidget()
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self.win_combo = QComboBox()
        self.win_combo.setMinimumWidth(260)
        top.addWidget(QLabel("Janela:"))
        top.addWidget(self.win_combo)
        for text, slot in (
            ("Atualizar lista", self.refresh_windows),
            ("Capturar", self.grab),
            ("Abrir print…", self.open_png),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
        self.live = QCheckBox("Ao vivo (1 s)")
        self.live.toggled.connect(self.toggle_live)
        top.addWidget(self.live)
        top.addStretch(1)
        self.size_label = QLabel()
        top.addWidget(self.size_label)
        root.addLayout(top)

        mid = QHBoxLayout()
        self.canvas = Canvas()
        self.canvas.roi_drawn.connect(self.on_roi)
        mid.addWidget(self.canvas, 3)

        side = QVBoxLayout()
        side.addWidget(QLabel("<b>1.</b> Escolha o campo e arraste um retângulo no print"))
        self.field_list = QListWidget()
        for f in FIELDS:
            self.field_list.addItem(f"{FIELD_LABELS_PT[f]}  [{f}]")
        self.field_list.currentRowChanged.connect(self.on_field)
        self.field_list.setMaximumHeight(170)
        side.addWidget(self.field_list)
        self.zoom = QLabel()
        self.zoom.setMinimumHeight(60)
        self.zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.zoom)

        side.addWidget(QLabel("<b>2.</b> Se a leitura estiver errada, digite o valor certo e ensine"))
        teach = QHBoxLayout()
        self.teach_edit = QLineEdit()
        self.teach_edit.setPlaceholderText("ex.: 805/811 · 212,32 · 00:45:03 · Aida")
        self.teach_edit.returnPressed.connect(self.teach)
        teach.addWidget(self.teach_edit)
        b = QPushButton("Ensinar")
        b.clicked.connect(self.teach)
        teach.addWidget(b)
        side.addLayout(teach)
        self.teach_status = QLabel()
        self.teach_status.setWordWrap(True)
        side.addWidget(self.teach_status)

        side.addWidget(QLabel("<b>Leitura atual</b>"))
        self.table = QTableWidget(len(LIVE_FIELDS), 4)
        self.table.setHorizontalHeaderLabels(["Campo", "Valor", "Confiança", "Situação"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for i, f in enumerate(LIVE_FIELDS):
            self.table.setItem(i, 0, QTableWidgetItem(f))
        side.addWidget(self.table)
        self.missing = QLabel()
        self.missing.setWordWrap(True)
        side.addWidget(self.missing)

        btns = QHBoxLayout()
        for text, slot in (
            ("Salvar perfil", self.save),
            ("Exportar…", self.export),
            ("Importar…", self.import_),
            ("Restaurar padrão", self.reset),
        ):
            bb = QPushButton(text)
            bb.clicked.connect(slot)
            btns.addWidget(bb)
        side.addLayout(btns)
        mid.addLayout(side, 2)
        root.addLayout(mid)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.grab)

        self.canvas.rois = self.profile.rois
        self.refresh_windows()
        self.field_list.setCurrentRow(0)
        self.update_missing()
        if not winapi.current_process_elevated() and any(w.elevated for w in winapi.list_windows()):
            self.statusBar().showMessage(
                "O jogo roda como administrador e este app não: a captura funciona (WGC), "
                "mas as ações das fases seguintes vão exigir rodar como administrador."
            )

    # ------------------------------------------------------------ janelas/captura
    def refresh_windows(self) -> None:
        self.win_combo.clear()
        for w in sorted(winapi.list_windows(), key=lambda w: w.pid):
            tag = " (minimizada)" if w.minimized else ""
            self.win_combo.addItem(f"PID {w.pid} · {w.client_size[0]}x{w.client_size[1]}{tag}", w.hwnd)
        if self.win_combo.count() == 0:
            self.win_combo.addItem("nenhuma janela do MU encontrada", None)

    def grab(self) -> None:
        hwnd = self.win_combo.currentData()
        if not hwnd:
            return
        try:
            f = self.capture.grab(hwnd)
        except CaptureError as e:
            self.statusBar().showMessage(f"Não capturou: {e}", 5000)
            return
        self.set_frame(f.image, f"capturado via {f.backend}")

    def open_png(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Abrir print", str(paths.captures_dir()), "PNG (*.png)")
        if fn:
            img = cv2.imdecode(np.fromfile(fn, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self.live.setChecked(False)
                self.set_frame(img, Path(fn).name)

    def set_frame(self, img: np.ndarray, source: str) -> None:
        self.frame = img
        h, w = img.shape[:2]
        if (w, h) != tuple(self.profile.client_size):
            self._ask_switch_profile(w, h)
        self.size_label.setText(f"{w}x{h} · perfil {self.profile.name} · {source}")
        self.canvas.set_image(img)
        self.refresh_readings()
        self.on_field(self.field_list.currentRow())

    def _ask_switch_profile(self, w: int, h: int) -> bool:
        r = QMessageBox.question(
            self,
            "Outra resolução",
            f"Este print tem {w}x{h}, mas o perfil aberto é {self.profile.client_size[0]}x"
            f"{self.profile.client_size[1]}.\nAbrir/criar o perfil {w}x{h}?",
        )
        if r != QMessageBox.StandardButton.Yes:
            return False
        self.profile = paths.load_or_default_profile(w, h)
        self.reader = HudReader(self.profile)
        self.canvas.rois = self.profile.rois
        self.update_missing()
        return True

    def toggle_live(self, on: bool) -> None:
        if on:
            self.timer.start()
        else:
            self.timer.stop()

    # ------------------------------------------------------------ campos
    def current_field(self) -> str:
        return FIELDS[max(0, self.field_list.currentRow())]

    def on_field(self, row: int) -> None:
        if row < 0:
            return
        f = FIELDS[row]
        self.canvas.selected = f
        self.canvas.update()
        roi = self.profile.rois.get(f)
        if self.frame is not None and roi is not None and roi.fits(self.frame.shape[1::-1]):
            c = roi.crop(self.frame)
            if c.size:
                scale = max(1, min(6, 360 // max(1, c.shape[1])))
                self.zoom.setPixmap(bgr_to_pixmap(cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)))
                return
        self.zoom.clear()

    def on_roi(self, roi: Roi) -> None:
        f = self.current_field()
        self.profile.rois[f] = roi
        if f == "hunting_log_title":  # a referência antiga era de outra região
            self.profile.refs.pop("hunting_log_title", None)
        self.dirty = True
        self.canvas.rois = self.profile.rois
        self.refresh_readings()
        self.on_field(self.field_list.currentRow())

    def teach(self) -> None:
        if self.frame is None:
            return
        f = self.current_field()
        roi = self.profile.rois.get(f)
        if roi is None:
            self.teach_status.setText("Desenhe a região deste campo primeiro.")
            return
        val = self.teach_edit.text().strip()
        crop = roi.crop(self.frame)
        kind = FIELD_KINDS.get(f)
        ok = False
        if kind == "glyph" and val:
            font = self.profile.font(f)
            ok = glyphs.learn(font, crop, val)
            if ok:
                self.profile.store_font(f, font)
        elif f == "map" and val:
            ok = self.profile.learn_map(val, crop)
            if ok and val not in self.reader.maps:
                self.reader.maps.append(val)
        elif f == "hunting_log_title":
            self.profile.set_ref_image(f, crop)
            ok = True
        else:
            self.teach_status.setText("Este campo é lido por OCR e não precisa de ensino.")
            return
        self.teach_status.setText("Aprendido ✔" if ok else "Não consegui separar os caracteres. Confira a região.")
        if ok:
            self.dirty = True
            self.teach_edit.clear()
        self.refresh_readings()
        self.update_missing()

    def refresh_readings(self) -> None:
        if self.frame is None:
            return
        hud = self.reader.read(self.frame, LIVE_FIELDS)
        for i, f in enumerate(LIVE_FIELDS):
            r = hud.fields[f]
            val = "" if r.value is None else str(r.value)
            if f == "hunting_log_title":
                val = "aberto" if r.value else "fechado"
            sit = {"ok": "ok", "absent": "ausente", "unreadable": "ilegível"}[r.status]
            for j, t in enumerate((val, f"{r.confidence:.2f}", sit + (f" · {r.raw}" if r.raw and not r.ok else ""))):
                self.table.setItem(i, j + 1, QTableWidgetItem(t))
        self.statusBar().showMessage(f"Leitura em {hud.elapsed_ms:.0f} ms", 3000)

    def update_missing(self) -> None:
        parts = []
        for f in ("hp", "coords", "exp", "hunting_time"):
            m = self.profile.missing_chars(f)
            if m:
                parts.append(f"{f}: {' '.join(sorted(m))}")
        maps = sorted(self.profile.map_refs())
        txt = "Caracteres ainda não aprendidos — " + ("; ".join(parts) if parts else "nenhum ✔")
        txt += f"<br>Mapas aprendidos: {', '.join(maps) if maps else 'nenhum (usa OCR)'}"
        self.missing.setText(txt)

    # ------------------------------------------------------------ arquivo
    def save(self) -> None:
        p = paths.profile_path(*self.profile.client_size)
        self.profile.save(p)
        self.dirty = False
        self.statusBar().showMessage(f"Perfil salvo em {p}", 5000)

    def export(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(
            self, "Exportar perfil", f"perfil_{self.profile.name}.json", "Perfil (*.json)"
        )
        if fn:
            self.profile.save(Path(fn))
            self.statusBar().showMessage(f"Exportado para {fn}", 5000)

    def import_(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Importar perfil", "", "Perfil (*.json)")
        if not fn:
            return
        try:
            prof = Profile.load(Path(fn))
        except Exception as e:  # arquivo inválido
            QMessageBox.warning(self, "Importar", f"Arquivo inválido: {e}")
            return
        self.profile = prof
        self.reader = HudReader(prof)
        self.canvas.rois = prof.rois
        self.dirty = True
        self.update_missing()
        self.refresh_readings()
        self.canvas.update()
        self.statusBar().showMessage(f"Perfil {prof.name} importado. Clique em Salvar para usar.", 8000)

    def reset(self) -> None:
        w, h = self.profile.client_size
        d = default_profile(w, h)
        if d is None:
            QMessageBox.information(self, "Restaurar", f"Não há regiões de fábrica para {w}x{h}.")
            return
        if QMessageBox.question(self, "Restaurar", f"Voltar as regiões para o padrão {w}x{h}? (as fontes aprendidas ficam)") \
                != QMessageBox.StandardButton.Yes:
            return
        self.profile.rois = d.rois
        self.canvas.rois = self.profile.rois
        self.dirty = True
        self.refresh_readings()
        self.canvas.update()

    def closeEvent(self, e):  # noqa: N802
        if self.dirty:
            r = QMessageBox.question(
                self,
                "Sair",
                "Salvar o perfil antes de sair?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if r == QMessageBox.StandardButton.Cancel:
                e.ignore()
                return
            if r == QMessageBox.StandardButton.Yes:
                self.save()
        self.timer.stop()
        self.capture.close()
        super().closeEvent(e)


def main() -> int:
    winapi.enable_dpi_awareness()
    app = QApplication(sys.argv[:1])
    from . import theme

    theme.apply(app)
    w = CalibrationWindow()
    w.resize(1500, 900)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
