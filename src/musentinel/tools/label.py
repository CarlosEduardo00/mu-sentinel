"""Rotulador de prints: confirma/corrige a leitura de cada campo e monta a suíte de testes.

Uso:
    python -m musentinel.tools.label [--pasta <prints>]

Convenções no texto de cada campo:
    valor exato do HUD (ex.: 805/811)
    ?  = ilegível (menu por cima, loading…)
    -  = ausente (ex.: painel Instant Hunting Log fechado)

Enter salva e vai para o próximo. O print vai para tests/fixtures/screens/<cena>/
e o perfil de calibração aprende com ele na hora.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import paths
from ..core.perception.dataset import SCENES, UNREADABLE, Sample
from ..core.perception.fields import PARSERS
from ..core.perception.profile import FIELD_LABELS_PT
from ..core.perception.reader import HudReader
from ..core.perception.training import learn_sample
from ..gui.qtutil import bgr_to_pixmap

FIELDS = ("hp", "coords", "exp", "hunting_time", "map")
ABSENT = "-"


def guess_scene(values: dict[str, str], cities: set[str]) -> str:
    hp = values.get("hp", "")
    if hp.startswith("0/"):
        return "morto"
    if values.get("map", "").lower() in cities:
        return "cidade"
    if UNREADABLE in values.values():
        return "menu_aberto"
    return "cacando"


class Labeler(QMainWindow):
    def __init__(self, files: list[Path], fixtures: Path):
        super().__init__()
        self.setWindowTitle("MU Sentinel — rotulador de prints")
        self.files = files
        self.idx = 0
        self.fixtures = fixtures
        self.profile = paths.load_or_default_profile()
        self.reader = HudReader(self.profile)
        self.cities = {"lorencia", "devias", "noria", "elbeland"}
        self.image: np.ndarray | None = None
        self.done = 0

        central = QWidget()
        root = QHBoxLayout(central)
        self.view = QLabel()
        self.view.setMinimumSize(800, 600)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.view, 3)

        side = QVBoxLayout()
        self.info = QLabel()
        self.info.setWordWrap(True)
        side.addWidget(self.info)
        form = QFormLayout()
        self.scene = QComboBox()
        for k, v in SCENES.items():
            self.scene.addItem(v, k)
        form.addRow("Cena", self.scene)
        self.edits: dict[str, QLineEdit] = {}
        self.crops: dict[str, QLabel] = {}
        for f in FIELDS:
            row = QVBoxLayout()
            crop = QLabel()
            crop.setMinimumHeight(40)
            e = QLineEdit()
            e.returnPressed.connect(self.save_next)
            row.addWidget(crop)
            row.addWidget(e)
            w = QWidget()
            w.setLayout(row)
            form.addRow(FIELD_LABELS_PT[f], w)
            self.edits[f] = e
            self.crops[f] = crop
        side.addLayout(form)
        side.addWidget(QLabel("Valor exato do HUD · ? = ilegível · - = ausente (painel fechado)"))
        btns = QHBoxLayout()
        for text, slot in (
            ("◀ Anterior", self.prev),
            ("Pular", self.skip),
            ("Descartar", self.discard),
            ("Salvar e próximo (Enter)", self.save_next),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        side.addLayout(btns)
        side.addStretch(1)
        root.addLayout(side, 2)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+Right"), self, self.skip)
        QShortcut(QKeySequence("Ctrl+Left"), self, self.prev)
        QShortcut(QKeySequence("Ctrl+Delete"), self, self.discard)
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        if self.idx >= len(self.files):
            QMessageBox.information(self, "Fim", f"Acabaram os prints. {self.done} rotulados nesta sessão.")
            self.close()
            return
        p = self.files[self.idx]
        img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self.idx += 1
            return self.load()
        self.image = img
        h, w = img.shape[:2]
        size_ok = (w, h) == tuple(self.profile.client_size)
        self.info.setText(
            f"<b>{p.name}</b><br>{self.idx + 1}/{len(self.files)} · rotulados nesta sessão: {self.done}"
            + ("" if size_ok else f"<br><span style='color:red'>Tamanho {w}x{h} ≠ perfil {self.profile.client_size}</span>")
        )
        hud = self.reader.read(img, FIELDS) if size_ok else None
        values = {}
        for f in FIELDS:
            r = hud.fields[f] if hud else None
            if r is None:
                v = UNREADABLE
            elif r.ok:
                v = r.raw if f != "map" else str(r.value)
            elif r.status == "absent":
                v = ABSENT
            elif f in PARSERS and r.raw and PARSERS[f](r.raw, 1.0).ok:
                v = r.raw  # leitura com pouca confiança mas bem formada: só conferir
            else:
                v = UNREADABLE
            values[f] = v
            self.edits[f].setText(v)
            roi = self.profile.rois.get(f)
            if roi is not None and size_ok:
                c = roi.crop(img)
                self.crops[f].setPixmap(bgr_to_pixmap(cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)))
        self.scene.setCurrentIndex(max(0, self.scene.findData(guess_scene(values, self.cities))))
        self.draw()
        self.edits["hp"].setFocus()
        self.edits["hp"].selectAll()

    def draw(self) -> None:
        pm = bgr_to_pixmap(self.image)
        painter = QPainter(pm)
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
        for f in FIELDS:
            r = self.profile.rois.get(f)
            if r:
                painter.drawRect(r.x, r.y, r.w, r.h)
        painter.end()
        self.view.setPixmap(
            pm.scaled(self.view.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.image is not None:
            self.draw()

    # ------------------------------------------------------------------
    def expected(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for f, e in self.edits.items():
            t = e.text().strip()
            if t == ABSENT:
                out[f] = None
            elif t == "" or t == UNREADABLE:
                out[f] = UNREADABLE
            else:
                out[f] = t.replace(" ", "") if f != "map" else t
        return out

    def save_next(self) -> None:
        if self.image is None:
            return
        src = self.files[self.idx]
        scene = self.scene.currentData()
        dst_dir = self.fixtures / scene
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        shutil.move(str(src), dst)
        self.files[self.idx] = dst
        exp = self.expected()
        Sample(dst, scene, exp).save()
        learn_sample(self.profile, self.reader, self.image, exp)
        self.profile.save(paths.profile_path(*self.profile.client_size))
        self.done += 1
        self.idx += 1
        self.load()

    def skip(self) -> None:
        self.idx += 1
        self.load()

    def prev(self) -> None:
        self.idx = max(0, self.idx - 1)
        self.load()

    def discard(self) -> None:
        src = self.files[self.idx]
        d = src.parent / "_descartados"
        d.mkdir(exist_ok=True)
        shutil.move(str(src), d / src.name)
        del self.files[self.idx]
        self.load()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rotula prints do MU para a suíte de testes.")
    ap.add_argument("--pasta", type=Path, default=paths.captures_dir())
    ap.add_argument("--suite", type=Path, default=paths.fixtures_dir())
    a = ap.parse_args(argv)
    files = sorted(
        p for p in a.pasta.rglob("*.png") if "_descartados" not in p.parts and not p.with_suffix(".json").exists()
    )
    app = QApplication(sys.argv[:1])
    if not files:
        QMessageBox.information(None, "Rotulador", f"Nenhum print sem rótulo em {a.pasta}")
        return 0
    w = Labeler(files, a.suite)
    w.resize(1500, 900)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
