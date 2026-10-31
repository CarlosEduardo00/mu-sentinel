"""Painel principal: um card por slot, barra superior, log de eventos e bandeja."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import paths
from ..core.config import LEVEL_NAMES, RISK_TEXT, Config
from ..core.engine import Engine, SlotSnapshot
from ..core.events import Event, EventBus
from ..core.notifiers.base import NotifierStatus
from ..core.state_machine import CRITICAL, State
from .qtutil import bgr_to_pixmap


STATE_COLOR = {
    State.CACANDO: "#2e9d47",
    State.ONLINE: "#4a7bb7",
    State.PARADO: "#d18b00",
    State.ILEGIVEL: "#7a7a7a",
    State.MORTO: "#c62828",
    State.DESCONECTADO: "#c62828",
    State.TRAVADO: "#c62828",
    State.FECHADO: "#8e1b1b",
}
THUMB_W, THUMB_H = 280, 210
CARD_MIN_W = 640
SEV_COLOR = {"critico": "#c62828", "aviso": "#d18b00", "info": "#555555"}


def app_icon(color: str = "#c62828") -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 26, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "M")
    p.end()
    return QIcon(pm)


def fmt_big(v: float) -> str:
    if v >= 1e9:
        return f"{v / 1e9:.1f} B".replace(".", ",")
    if v >= 1e6:
        return f"{v / 1e6:.1f} M".replace(".", ",")
    if v >= 1e3:
        return f"{v / 1e3:.0f} mil"
    return f"{v:.0f}"


def fmt_dur(s: float) -> str:
    s = int(max(0, s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


class Bridge(QObject):
    """Leva o que o core publica (em outras threads) para a thread do Qt."""

    snapshots = Signal(object)
    event = Signal(object)
    notify = Signal(str)


class TrayNotifier:
    """Notificação do Windows (balão da bandeja). Canal local: não sai do PC."""

    name = "Notificação do Windows"
    supports_images = False
    supports_inbound = False
    external = False

    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge

    def send(self, text: str, image: bytes | None = None) -> None:
        self.bridge.notify.emit(text)

    def start_inbound(self, on_message) -> None:
        return None

    def status(self) -> NotifierStatus:
        return NotifierStatus(QSystemTrayIcon.isSystemTrayAvailable(), "bandeja do Windows")

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
class SlotCard(QFrame):
    def __init__(self, win: MainWindow, slot: int):
        super().__init__()
        self.win = win
        self.slot = slot
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(self)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#111; color:#888;")
        self.thumb.setText("sem imagem")
        h.addWidget(self.thumb)
        v = QVBoxLayout()
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-size:15px; font-weight:bold;")
        top.addWidget(self.title)
        rn = QToolButton()
        rn.setText("✎")
        rn.setToolTip("Renomear slot")
        rn.clicked.connect(self._rename)
        top.addWidget(rn)
        top.addStretch()
        v.addLayout(top)
        self.state = QLabel()
        self.state.setStyleSheet("font-size:14px; font-weight:bold; color:white; padding:3px 8px; border-radius:4px;")
        self.state.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        v.addWidget(self.state)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setMinimumWidth(300)
        v.addWidget(self.info)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#888;")
        v.addWidget(self.note)
        v.addStretch()
        btns = QHBoxLayout()
        self.b_print = QPushButton("Print")
        self.b_print.setToolTip("Salva um print da janela (não envia nada ao jogo)")
        self.b_print.clicked.connect(lambda: self.win.save_print(self.slot))
        self.b_ack = QPushButton("OK, vi o alerta")
        self.b_ack.clicked.connect(lambda: self.win.engine.ack(self.slot))
        self.b_forget = QPushButton("Remover slot")
        self.b_forget.setToolTip("O client foi fechado de propósito: para de monitorar este slot")
        self.b_forget.clicked.connect(self._forget)
        self.b_cal = QPushButton("Calibrar")
        self.b_cal.setToolTip("Lê o HUD e os painéis desta janela com o OCR completo e ensina o leitor "
                              "(HP, EXP, mapa, tempo de caça). Use depois de mudar resolução ou layout.")
        self.b_cal.clicked.connect(lambda: self.win.calibrate_slots([self.slot]))
        for b in (self.b_print, self.b_cal, self.b_ack, self.b_forget):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)
        h.addLayout(v, 1)

    def update_from(self, s: SlotSnapshot, active_alert: bool) -> None:
        title = f"Slot {s.slot}" if s.name == f"Slot {s.slot}" else f"Slot {s.slot} · {s.name}"
        self.title.setText(title + ("  🏪" if s.shop else ""))
        color = STATE_COLOR.get(s.state, "#555")
        self.state.setStyleSheet(f"font-size:14px; font-weight:bold; color:white; padding:3px 8px;"
                                 f" border-radius:4px; background:{color};")
        self.state.setText(f"{s.state.value}  ·  há {fmt_dur(time.time() - s.since)}")
        hp = "—"
        if s.hp:
            hp = f"{s.hp[0]}/{s.hp[1]} ({100 * s.hp[0] / s.hp[1]:.0f}%)" if s.hp[1] else f"{s.hp[0]}/{s.hp[1]}"
        where = s.map or "—"
        if s.coords:
            where += f"  {s.coords[0]},{s.coords[1]}"
        exph = "—"
        if s.exp_per_h is not None:
            exph = f"{fmt_big(s.exp_per_h)}/h ({s.exp_pct_per_h:.1f}%/h)".replace(".", ",", 1)
        ht = "—" if s.hunting_time is None else time.strftime("%H:%M:%S", time.gmtime(s.hunting_time))
        conn = {True: "conectado", False: "<b style='color:#c62828'>sem conexão</b>", None: "—"}[s.connected]
        short = {"personagem": "C", "inventario": "I", "caca": "Caçada", "loja": "Gremory"}
        panels_text = ", ".join(short[k] for k in s.panels) or "—"
        if s.shop_status and "loja" in s.panels:
            cnt, cap, sold = s.shop_status
            panels_text += f" · Gremory <b>{cnt}/{cap}</b>" + (
                f" · última venda {time.strftime('%H:%M', time.localtime(sold))}" if sold else "")
        if s.shop and "loja" not in s.panels:
            panels_text += " <b style='color:#b26a00'>(abra o Gremory Case)</b>"
        self.info.setText(
            f"<table cellspacing=2>"
            f"<tr><td>HP</td><td><b>{hp}</b></td></tr>"
            f"<tr><td>Mapa</td><td>{where}</td></tr>"
            f"<tr><td>EXP/h</td><td>{exph}</td></tr>"
            f"<tr><td>Hunting Time</td><td>{ht}</td></tr>"
            f"<tr><td>Servidor</td><td>{conn}</td></tr>"
            f"<tr><td>Último evento</td><td>{s.last_event or '—'}</td></tr>"
            f"<tr><td>Painéis</td><td>{panels_text}</td></tr>"
            f"</table>")
        self.note.setText(s.note)
        if s.thumb is not None:
            pm = bgr_to_pixmap(s.thumb).scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
            self.thumb.setPixmap(pm)
        self.b_ack.setVisible(active_alert)
        self.b_forget.setVisible(s.state == State.FECHADO)
        self.b_print.setEnabled(s.thumb is not None)
        self.b_cal.setEnabled(s.thumb is not None and not self.win.calibrating)

    def _rename(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        cur = self.win.cfg.slot_name(self.slot)
        name, ok = QInputDialog.getText(self, "Renomear", f"Nome do slot {self.slot}:", text=cur)
        if ok and name.strip():
            cfg = self.win.cfg.model_copy(deep=True)
            cfg.slot(self.slot).name = name.strip()
            self.win.apply_config(cfg)

    def _forget(self) -> None:
        if QMessageBox.question(self, "Remover slot", f"Parar de monitorar o slot {self.slot}?") \
                == QMessageBox.StandardButton.Yes:
            self.win.engine.forget_slot(self.slot)
            self.win.remove_card(self.slot)


# ---------------------------------------------------------------------------
class EventsTab(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.f_slot = QComboBox()
        self.f_slot.addItem("Todos os slots", None)
        for n in range(1, 9):
            self.f_slot.addItem(f"Slot {n}", n)
        self.f_sev = QComboBox()
        for label, val in (("Todas", None), ("Crítico", "critico"), ("Aviso", "aviso"), ("Info", "info")):
            self.f_sev.addItem(label, val)
        self.f_text = QLineEdit()
        self.f_text.setPlaceholderText("buscar texto…")
        exp = QPushButton("Exportar CSV…")
        exp.clicked.connect(self._export)
        for w in (QLabel("Filtro:"), self.f_slot, self.f_sev, self.f_text):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(exp)
        v.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Data/hora", "Slot", "Tipo", "Severidade", "Mensagem"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        v.addWidget(self.table)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.reload)
        for w in (self.f_slot, self.f_sev):
            w.currentIndexChanged.connect(lambda *_: self.reload())
        self.f_text.textChanged.connect(lambda *_: self._timer.start(300))

    def filters(self) -> dict:
        return {"slot": self.f_slot.currentData(), "severity": self.f_sev.currentData(),
                "text": self.f_text.text().strip() or None}

    def schedule(self) -> None:
        if self.isVisible():
            self._timer.start(800)

    def reload(self) -> None:
        store = self.win.bus.store
        if store is None:
            return
        evs = store.query(limit=1000, **self.filters())
        self.table.setRowCount(len(evs))
        for i, e in enumerate(evs):
            vals = (time.strftime("%d/%m %H:%M:%S", time.localtime(e.ts)), str(e.slot or ""), e.kind,
                    e.severity, e.message)
            for j, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if j == 3:
                    it.setForeground(QColor(SEV_COLOR.get(e.severity, "#555")))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

    def showEvent(self, e):  # noqa: N802
        self.reload()
        super().showEvent(e)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar eventos", str(Path.home() / "eventos_musentinel.csv"),
                                              "CSV (*.csv)")
        if path:
            n = self.win.bus.store.export_csv(Path(path), **self.filters())
            QMessageBox.information(self, "Exportar", f"{n} eventos exportados.")


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, bus: EventBus, start_hidden: bool = False):
        super().__init__()
        self.cfg = cfg
        self.bus = bus
        self.bridge = Bridge()
        self.tray_notifier = TrayNotifier(self.bridge)
        self.engine = Engine(cfg, bus, [self.tray_notifier])
        self.cards: dict[int, SlotCard] = {}
        self.calibrating = False
        self._quitting = False
        self._tray_hint_shown = False

        self.setWindowTitle("MU Sentinel")
        self.setWindowIcon(app_icon())
        self.resize(1360, 820)
        self._build_menu()
        self._build_toolbar()

        central = QWidget()
        cv = QVBoxLayout(central)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.setOpenExternalLinks(False)
        self.banner.linkActivated.connect(self._banner_link)
        self.banner.setStyleSheet("background:#fff4d6; color:#5a4300; padding:6px; border:1px solid #e6c56a;")
        self.banner.setText("")
        self.banner.hide()
        cv.addWidget(self.banner)
        self.tabs = QTabWidget()
        cv.addWidget(self.tabs)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        self.empty = QLabel("Procurando janelas do MU… (título “MU”, processo main.exe)\n"
                            "Abra o jogo; ele aparece aqui sozinho.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color:#888; font-size:14px; padding:40px;")
        pv.addWidget(self.empty)
        self.grid = QGridLayout()
        pv.addLayout(self.grid)
        pv.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self.tabs.addTab(scroll, "Painel")
        self.events_tab = EventsTab(self)
        self.tabs.addTab(self.events_tab, "Eventos")
        self.setCentralWidget(central)

        self._build_tray()
        self.bridge.snapshots.connect(self.on_snapshots)
        self.bridge.event.connect(self.on_event)
        self.bridge.notify.connect(self.on_notify)
        bus.subscribe("snapshots", self.bridge.snapshots.emit)
        bus.subscribe("event", self.bridge.event.emit)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh_status)
        self._tick.start(1000)
        self.engine.start()
        self.refresh_status()
        self._build_footer()
        if not start_hidden:
            self.show()
        self._pending_notes = self._new_version_notes()
        if self._pending_notes:
            if start_hidden:  # aberto minimizado (início com o Windows): avisa na bandeja
                self.tray.showMessage("MU Sentinel atualizado", f"Versão {__version__}: abra o app para ver as "
                                      "novidades.", QSystemTrayIcon.MessageIcon.Information, 8000)
            else:
                QTimer.singleShot(800, self.show_whats_new)

    # ------------------------------------------------------------------ versão e novidades
    def _build_footer(self) -> None:
        v = QLabel(f"MU Sentinel v{__version__} · <a href='novidades'>novidades</a>")
        v.setTextFormat(Qt.TextFormat.RichText)
        v.setStyleSheet("color:#888; padding:0 6px;")
        v.setToolTip("Versão instalada. Clique em 'novidades' para ver o que mudou.")
        v.linkActivated.connect(lambda _: self.show_whats_new(all_versions=True))
        self.statusBar().addPermanentWidget(v)
        self.version_label = v

    def _new_version_notes(self) -> str:
        """Novidades desde a última versão que o usuário viu (só para quem já usava o app)."""
        from ..core import changelog

        last = self.cfg.last_seen_version
        if last == __version__ or not self.cfg.wizard_done:
            return ""
        if last and not changelog.is_newer(__version__, last):
            return ""
        try:
            return changelog.notes_since(last, __version__)
        except Exception:
            return ""

    def show_whats_new(self, all_versions: bool = False) -> None:
        from ..core import changelog

        notes = self._pending_notes if not all_versions else ""
        if not notes:
            p = changelog.changelog_path()
            notes = p.read_text(encoding="utf-8") if p.exists() else "Sem arquivo de novidades."
        box = QMessageBox(self)
        box.setWindowTitle(f"Novidades — MU Sentinel {__version__}")
        box.setTextFormat(Qt.TextFormat.MarkdownText)
        box.setText(notes)
        box.exec()
        self._pending_notes = ""
        if self.cfg.last_seen_version != __version__:
            cfg = self.cfg.model_copy(deep=True)
            cfg.last_seen_version = __version__
            self.apply_config(cfg)

    # ------------------------------------------------------------------ construção
    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Arquivo")
        for text, fn in (("Configurações…", self.open_settings), ("Assistente de configuração…", self.open_wizard),
                         ("Calibrar todas as janelas agora", lambda: self.calibrate_slots(None)),
                         ("Calibração manual…", self.open_calibration),
                         ("Abrir pasta de dados", lambda: os.startfile(paths.data_dir()))):
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        q = QAction("Sair", self)
        q.triggered.connect(self.quit)
        m.addAction(q)
        h = self.menuBar().addMenu("A&juda")
        a = QAction("Sobre e aviso de risco", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Principal")
        tb.setMovable(False)
        self.level_lbl = QLabel()
        self.level_lbl.setStyleSheet("font-weight:bold; padding:0 8px;")
        self.level_lbl.setToolTip("Nível 0 · Observador: só monitora e avisa; nenhuma tecla é enviada ao jogo.\n"
                                  "Os níveis 1 a 4 estão desativados: o MU Sentinel nunca envia teclas ao jogo.")
        tb.addWidget(self.level_lbl)
        tb.addSeparator()
        self.pause_btn = QToolButton()
        self.pause_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.pause_btn.clicked.connect(self.toggle_pause)
        pm = QMenu(self)
        for label, mins in (("Pausar 30 min", 30), ("Pausar 1 h", 60), ("Pausar 2 h", 120), ("Pausar até retomar", None)):
            a = pm.addAction(label)
            a.triggered.connect(lambda _=False, m=mins: self.engine.pause_alerts(m))
        self.pause_btn.setMenu(pm)
        tb.addWidget(self.pause_btn)
        self.ack_btn = QPushButton()
        self.ack_btn.clicked.connect(lambda: self.engine.ack())
        tb.addWidget(self.ack_btn)
        test = QPushButton("Enviar alerta de teste")
        test.clicked.connect(self.send_test)
        tb.addWidget(test)
        tb.addSeparator()
        self.notif_lbl = QLabel()
        self.notif_lbl.setTextFormat(Qt.TextFormat.RichText)
        tb.addWidget(self.notif_lbl)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.uptime_lbl = QLabel()
        self.uptime_lbl.setStyleSheet("color:#777; padding:0 8px;")
        tb.addWidget(self.uptime_lbl)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("MU Sentinel")
        menu = QMenu()
        menu.addAction("Abrir").triggered.connect(self.show_normal)
        self.tray_pause = menu.addAction("Pausar alertas por 1 h")
        self.tray_pause.triggered.connect(self.toggle_pause_tray)
        menu.addSeparator()
        menu.addAction("Sair").triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal()
                                    if r in (QSystemTrayIcon.ActivationReason.Trigger,
                                             QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()

    # ------------------------------------------------------------------ atualizações
    def on_snapshots(self, snaps: list[SlotSnapshot]) -> None:
        self._last_snaps = snaps
        self._update_tray_icon(snaps)
        if not self.isVisible() or self.isMinimized():
            return  # escondido na bandeja/minimizado: não redesenha miniaturas à toa (economiza CPU)
        self._render(snaps)

    def _render(self, snaps: list[SlotSnapshot]) -> None:
        active = {k[0] for k in self.engine.alerts.active}
        for s in snaps:
            card = self.cards.get(s.slot)
            if card is None:
                card = self.cards[s.slot] = SlotCard(self, s.slot)
                self._relayout()
            card.update_from(s, s.slot in active)
        self.empty.setVisible(not self.cards)

    def _update_tray_icon(self, snaps: list[SlotSnapshot]) -> None:
        worst = "#2e9d47"
        if any(s.state in CRITICAL for s in snaps):
            worst = "#c62828"
        elif any(s.state in (State.PARADO, State.ILEGIVEL) for s in snaps):
            worst = "#d18b00"
        if getattr(self, "_icon_color", None) != worst:
            self._icon_color = worst
            self.tray.setIcon(app_icon(worst))

    def _relayout(self) -> None:
        cols = max(1, (self.width() - 40) // CARD_MIN_W)
        if cols == getattr(self, "_cols", None) and len(self.cards) == getattr(self, "_ncards", None):
            return
        self._cols, self._ncards = cols, len(self.cards)
        for card in self.cards.values():
            self.grid.removeWidget(card)
        for i, (n, card) in enumerate(sorted(self.cards.items())):
            self.grid.addWidget(card, i // cols, i % cols)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if getattr(self, "_last_snaps", None):
            self._render(self._last_snaps)  # voltou da bandeja: mostra o estado mais recente na hora
        if getattr(self, "_pending_notes", ""):
            QTimer.singleShot(500, self.show_whats_new)  # atualizado com o app minimizado

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.WindowStateChange and not self.isMinimized() \
                and getattr(self, "_last_snaps", None):
            self._render(self._last_snaps)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.cards:
            self._relayout()

    def remove_card(self, slot: int) -> None:
        card = self.cards.pop(slot, None)
        if card:
            self.grid.removeWidget(card)
            card.deleteLater()
            self._relayout()

    def on_event(self, ev: Event) -> None:
        self.events_tab.schedule()
        if ev.severity == "critico" and ev.kind == "alerta":
            self.statusBar().showMessage(f"{time.strftime('%H:%M')} slot {ev.slot}: {ev.message}", 30000)

    def on_notify(self, text: str) -> None:
        lines = text.splitlines()
        title = lines[0] if lines else "MU Sentinel"
        body = "\n".join(lines[1:]) or title
        icon = QSystemTrayIcon.MessageIcon.Critical if "CRÍTICO" in title else (
            QSystemTrayIcon.MessageIcon.Warning if "AVISO" in title else QSystemTrayIcon.MessageIcon.Information)
        self.tray.showMessage(title, body, icon, 15000)

    def refresh_status(self) -> None:
        self.level_lbl.setText(f"Nível {self.cfg.level} · {LEVEL_NAMES[self.cfg.level]} 🔒")
        a = self.engine.alerts
        if a.paused:
            until = a.paused_until
            txt = "Retomar alertas" + ("" if until == float("inf") else f" (pausado até {time.strftime('%H:%M', time.localtime(until))})")
            self.pause_btn.setText(txt)
            self.tray_pause.setText("Retomar alertas")
        else:
            self.pause_btn.setText("Pausar alertas")
            self.tray_pause.setText("Pausar alertas por 1 h")
        n = len(a.active)
        self.ack_btn.setText(f"OK, vi os alertas ({n})" if n else "Nenhum alerta ativo")
        self.ack_btn.setEnabled(bool(n))
        parts = []
        for name, ok, detail in self.engine.notifier_status():
            color = "#2e9d47" if ok else "#c62828"
            parts.append(f"<span style='color:{color}'>●</span> {name}: {detail}")
        self.notif_lbl.setText("&nbsp;&nbsp;".join(parts))
        up = fmt_dur(time.time() - self.engine.started_at)
        health = "monitor ok" if self.engine.alive() else "<b>monitor parado!</b>"
        self.uptime_lbl.setText(f"aberto há {up} · ciclo {self.engine.cycle_ms:.0f} ms · {health}")
        self._update_banner()

    def _update_banner(self) -> None:
        msgs = []
        cm, tg = self.cfg.notifiers.callmebot, self.cfg.notifiers.telegram
        if not (cm.enabled and cm.recipients) and not (tg.enabled and tg.chats):
            msgs.append("Nenhum canal no celular configurado: os alertas só aparecem neste PC. "
                        "<a href='telegram'>Configurar o Telegram</a> · <a href='whatsapp'>Configurar o WhatsApp</a>")
        if self.engine.protection_blocked:
            msgs.append(f"<b>Monitoramento limitado em {self.engine.protection_blocked} janela(s):</b> o anti-cheat do "
                        "jogo (GameGuard) não deixa este programa ver de qual processo elas são. O MU Sentinel não "
                        "contorna isso: segue pela imagem (morte, caça parada, travamento, janela fechada), mas não "
                        "checa a conexão com o servidor. Queda da internet deste PC continua sendo detectada.")
        if self.engine.internet.ok is False:
            msgs.append("<b>Sem internet</b>: os alertas pelo WhatsApp ficam na fila até a conexão voltar.")
        for w in self.engine.power_warnings:
            msgs.append(w + " <a href='energia'>Abrir opções de energia</a>")
        if self.engine.alerts.paused:
            msgs.append("<b>Alertas pausados.</b>")
        html = "<br>".join(msgs).replace("<a ", "<a style='color:#0b57d0; font-weight:bold' ")
        if html != getattr(self, "_banner_html", None):
            self._banner_html = html
            self.banner.setText(html)
            self.banner.setVisible(bool(html))

    def _banner_link(self, link: str) -> None:
        if link in ("whatsapp", "telegram"):
            self.open_settings(tab=link)
        elif link == "energia":
            os.startfile("ms-settings:powersleep")

    # ------------------------------------------------------------------ ações
    def toggle_pause(self) -> None:
        if self.engine.alerts.paused:
            self.engine.resume_alerts()
        else:
            self.engine.pause_alerts(60)
        self.refresh_status()

    def toggle_pause_tray(self) -> None:
        self.toggle_pause()

    def send_test(self) -> None:
        self.engine.send_test()
        self.statusBar().showMessage("Alerta de teste enviado para todos os canais ativos.", 8000)

    def save_print(self, slot: int) -> None:
        p = self.engine.save_print(slot)
        if p:
            self.statusBar().showMessage(f"Print salvo: {p}", 10000)
            os.startfile(p)

    def open_settings(self, tab: str | None = None) -> None:
        from .settings_dialog import SettingsDialog

        d = SettingsDialog(self.cfg, self, tab=tab if isinstance(tab, str) else None)
        if d.exec():
            self.apply_config(d.result_config())

    def open_wizard(self) -> None:
        from .wizard import SetupWizard

        w = SetupWizard(self.cfg, self, discovery=self.engine.discovery)
        if w.exec():
            self.apply_config(w.result_config())
            self.engine.reload_profiles()

    def apply_config(self, cfg: Config) -> None:
        try:
            cfg.save()
        except OSError as exc:
            QMessageBox.critical(self, "Configurações", f"Não consegui salvar o config.yaml: {exc}")
            return
        self.cfg = cfg
        self.engine.apply_config(cfg)
        self.refresh_status()

    def calibrate_slots(self, slots: list[int] | None) -> None:
        """Calibração automática (OCR completo da tela) de uma ou de todas as janelas, sem travar a tela."""
        if self.calibrating:
            return
        nums = slots if slots is not None else sorted(self.engine.slots)
        if not nums:
            QMessageBox.information(self, "Calibrar", "Nenhuma janela do MU aberta agora.")
            return
        self.calibrating = True
        for c in self.cards.values():
            c.b_cal.setEnabled(False)
        self.statusBar().showMessage("Calibrando… (lendo a tela inteira de cada janela, leva alguns segundos)")
        from .telegram_panel import run_async

        def work():
            return [(n, self.engine.calibrate_slot(n)) for n in nums]

        def done(results, err):
            self.calibrating = False
            for c in self.cards.values():
                c.b_cal.setEnabled(True)
            self.statusBar().clearMessage()
            if err:
                QMessageBox.warning(self, "Calibrar", f"A calibração falhou: {err}")
                return
            parts = []
            for n, res in results:
                body = "sem imagem da janela (minimizada?)" if res is None else (res.summary() or "nada lido")
                parts.append(f"<b>Slot {n} · {self.cfg.slot_name(n)}</b><br>" + body.replace("\n", "<br>"))
            QMessageBox.information(self, "Calibração automática", "<br><br>".join(parts)
                                    + "<br><br>Dica: calibrar de novo com outros números na tela (ex.: depois de "
                                      "tomar dano ou subir EXP) ensina dígitos que ainda faltam.")

        run_async(work, done)

    def open_calibration(self) -> None:
        from .calibration import CalibrationWindow

        self._calib = CalibrationWindow()
        self._calib.destroyed.connect(lambda *_: self.engine.reload_profiles())
        self._calib.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._calib.show()

    def about(self) -> None:
        from .. import __version__

        QMessageBox.about(self, "MU Sentinel",
                          f"<b>MU Sentinel {__version__}</b><br>Monitor de janelas do MU Online com alertas.<br><br>"
                          f"<b>Aviso de risco:</b> {RISK_TEXT}<br><br>"
                          "Nível 0 (Observador) só lê a imagem das janelas e informações do Windows; "
                          "não envia teclas, não lê memória e não mexe nos arquivos do jogo.")

    def show_normal(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):  # noqa: N802
        if self._quitting:
            e.accept()
            return
        e.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage("MU Sentinel continua rodando",
                                  "O monitor segue ativo na bandeja. Para sair: botão direito no ícone → Sair.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)

    def quit(self) -> None:
        if QMessageBox.question(self, "Sair", "Sair do MU Sentinel? O monitoramento e os alertas param.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._quitting = True
        self.engine.stop()
        self.tray.hide()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
