"""Painel principal: resumo no topo, um quadro por janela do jogo, histórico de eventos e ícone na bandeja."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import paths
from ..core.config import RISK_TEXT, Config
from ..core.engine import Engine, SlotSnapshot
from ..core.events import Event, EventBus
from ..core.notifiers.base import NotifierStatus
from ..core.perception.panels import fmt_big
from ..core.state_machine import State
from . import icons, theme
from .qtutil import bgr_to_pixmap
from .summary import display_name, summarize

STATE_COLOR = {
    State.CACANDO: theme.GREEN,
    State.ONLINE: theme.BLUE,
    State.PARADO: theme.AMBER,
    State.ILEGIVEL: theme.GRAY,
    State.MORTO: theme.RED,
    State.DESCONECTADO: theme.RED,
    State.TRAVADO: theme.RED,
    State.FECHADO: "#a32424",
}
STATUS_COLOR = {"ok": theme.GREEN, "atencao": theme.AMBER, "critico": theme.RED, "pausado": theme.GRAY}
THUMB_W, THUMB_H = 280, 210
CARD_MIN_W = 660
SEV_COLOR = {"critico": theme.RED, "aviso": theme.AMBER, "info": theme.GRAY}
SEV_TEXT = {"critico": "Crítico", "aviso": "Aviso", "info": "Info"}
PANEL_NAME = {"personagem": "Personagem (C)", "inventario": "Inventário (I)", "caca": "Caçada", "loja": "Gremory Case"}
MANUAL_URL = "https://github.com/CarlosEduardo00/mu-sentinel#readme"


def app_icon(status: str | None = None):
    return icons.app_icon(status)


def fmt_int(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def fmt_dur(s: float) -> str:
    s = int(max(0, s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def hp_color(pct: float) -> str:
    return theme.GREEN if pct > 50 else theme.AMBER if pct > 30 else theme.RED


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


def _label(obj: str, text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(obj)
    return lbl


# ---------------------------------------------------------------------------
class SlotCard(QFrame):
    """Quadro de uma janela do jogo: imagem, estado, HP, onde está, EXP/h, painéis e botões."""

    ROWS = ("hp", "where", "exph", "ht", "conn", "panels", "shop", "last")
    ROW_LABEL = {"hp": "HP", "where": "Onde", "exph": "EXP/h", "ht": "Hunting Time", "conn": "Servidor",
                 "panels": "Painéis abertos", "shop": "Loja", "last": "Último evento"}

    def __init__(self, win: MainWindow, slot: int):
        super().__init__()
        self.win = win
        self.slot = slot
        self._alert: bool | None = None
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(1, 1, 10, 1)
        outer.setSpacing(0)
        self.stripe = QFrame()
        self.stripe.setFixedWidth(5)
        outer.addWidget(self.stripe)
        h = QHBoxLayout()
        h.setContentsMargins(10, 10, 0, 10)
        h.setSpacing(14)
        outer.addLayout(h, 1)

        self.thumb = _label("thumb", "sem imagem")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)

        v = QVBoxLayout()
        v.setSpacing(6)
        top = QHBoxLayout()
        self.title = _label("cardTitle")
        top.addWidget(self.title)
        self.sub = _label("cardSub")
        top.addWidget(self.sub)
        rn = QToolButton()
        rn.setText("✎")
        rn.setAutoRaise(True)
        rn.setToolTip("Mudar o nome desta janela")
        rn.clicked.connect(self._rename)
        top.addWidget(rn)
        top.addStretch()
        v.addLayout(top)
        self.state = QLabel()
        self.state.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        v.addWidget(self.state)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self.row_widgets: dict[str, tuple[QLabel, QWidget]] = {}
        for i, key in enumerate(self.ROWS):
            name = _label("rowLabel", self.ROW_LABEL[key])
            if key == "hp":
                val = QWidget()
                hl = QHBoxLayout(val)
                hl.setContentsMargins(0, 0, 0, 0)
                self.hp_bar = QProgressBar()
                self.hp_bar.setTextVisible(False)
                self.hp_bar.setFixedSize(150, 10)
                self.hp_bar.setRange(0, 1000)
                hl.addWidget(self.hp_bar)
                self.hp_text = QLabel()
                hl.addWidget(self.hp_text)
                hl.addStretch()
            else:
                val = QLabel()
                val.setTextFormat(Qt.TextFormat.RichText)
                val.setWordWrap(True)
            grid.addWidget(name, i, 0)
            grid.addWidget(val, i, 1)
            self.row_widgets[key] = (name, val)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.note = _label("muted")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        v.addStretch()

        btns = QHBoxLayout()
        self.b_ack = QPushButton("✔ OK, vi o alerta")
        self.b_ack.setToolTip("Para de lembrar este alerta (o monitor continua de olho)")
        self.b_ack.clicked.connect(lambda: self.win.engine.ack(self.slot))
        self.b_print = QPushButton("📷 Print")
        self.b_print.setToolTip("Salva um print desta janela e abre a imagem (não envia nada ao jogo)")
        self.b_print.clicked.connect(lambda: self.win.save_print(self.slot))
        self.b_cal = QPushButton("🎯 Calibrar")
        self.b_cal.setToolTip("Ensina o app a ler esta janela (HP, EXP, mapa, tempo de caça).\n"
                              "Use se algum número aparecer errado ou depois de mudar a resolução do jogo.")
        self.b_cal.clicked.connect(lambda: self.win.calibrate_slots([self.slot]))
        self.b_forget = QPushButton("Parar de vigiar")
        self.b_forget.setToolTip("O jogo foi fechado de propósito: tira esta janela da lista")
        self.b_forget.clicked.connect(self._forget)
        for b in (self.b_ack, self.b_print, self.b_cal, self.b_forget):
            btns.addWidget(b)
        btns.addStretch()
        v.addLayout(btns)
        h.addLayout(v, 1)

    def _set_row(self, key: str, text: str | None) -> None:
        name, val = self.row_widgets[key]
        show = bool(text)
        if show and key != "hp":
            val.setText(text)
        name.setVisible(show)
        val.setVisible(show)

    def update_from(self, s: SlotSnapshot, active_alert: bool) -> None:
        c = theme.colors()
        nice = display_name(s.slot, s.name)
        self.title.setText(nice + ("  🏪" if s.shop else ""))
        self.sub.setText(f"janela {s.slot}" if nice != f"Janela {s.slot}" else "")
        color = STATE_COLOR.get(s.state, theme.GRAY)
        self.stripe.setStyleSheet(f"background:{color}; border-top-left-radius:9px; border-bottom-left-radius:9px;")
        self.state.setStyleSheet(f"font-size:14px; font-weight:bold; color:white; padding:3px 10px;"
                                 f" border-radius:10px; background:{color};")
        self.state.setText(f"{s.state.value}  ·  há {fmt_dur(time.time() - s.since)}")
        if self._alert != active_alert:
            self._alert = active_alert
            self.setProperty("alerta", active_alert)
            self.style().unpolish(self)
            self.style().polish(self)

        if s.hp:
            cur, mx = s.hp
            pct = 100 * cur / mx if mx else 0
            self.hp_bar.setValue(int(10 * max(0, min(100, pct))))
            self.hp_bar.setStyleSheet(
                f"QProgressBar {{ background:{c['track']}; border:none; border-radius:5px; }}"
                f"QProgressBar::chunk {{ background:{hp_color(pct)}; border-radius:5px; }}")
            self.hp_text.setText(f"<b>{fmt_int(cur)} / {fmt_int(mx)}</b>  ({pct:.0f}%)" if mx else fmt_int(cur))
            self._set_row("hp", "x")
        else:
            self._set_row("hp", None)

        where = s.map or ""
        if where and s.coords:
            where += f"  <span style='color:{c['muted']}'>{s.coords[0]},{s.coords[1]}</span>"
        self._set_row("where", where)
        exph = None
        if s.exp_per_h is not None:
            exph = f"<b>{fmt_big(s.exp_per_h)}</b>"
            if s.exp_pct_per_h is not None:
                exph += f"  ({s.exp_pct_per_h:.1f}%/h)".replace(".", ",")
        self._set_row("exph", exph)
        self._set_row("ht", None if s.hunting_time is None else time.strftime("%H:%M:%S", time.gmtime(s.hunting_time)))
        conn = {True: f"<span style='color:{theme.GREEN}'>●</span> conectado",
                False: f"<b style='color:{theme.RED}'>● sem conexão</b>", None: None}[s.connected]
        self._set_row("conn", conn)
        self._set_row("panels", ", ".join(PANEL_NAME.get(k, k) for k in s.panels if k != "loja") or None)
        shop = None
        if s.shop:
            if "loja" in s.panels and s.shop_status:
                cnt, cap, sold = s.shop_status
                shop = f"<b>{cnt}/{cap}</b> itens"
                if sold:
                    shop += f" · última venda {time.strftime('%H:%M', time.localtime(sold))}"
            elif "loja" in s.panels:
                shop = "Gremory Case aberto"
            else:
                shop = f"<b style='color:{theme.AMBER}'>abra o Gremory Case (aba Personal Shop)</b>"
        self._set_row("shop", shop)
        self._set_row("last", s.last_event or None)
        self.note.setText(s.note)
        self.note.setVisible(bool(s.note))

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

        cur = display_name(self.slot, self.win.cfg.slot_name(self.slot))
        name, ok = QInputDialog.getText(self, "Mudar o nome", f"Nome da janela {self.slot} (aparece nos alertas):",
                                        text=cur)
        if ok and name.strip():
            cfg = self.win.cfg.model_copy(deep=True)
            cfg.slot(self.slot).name = name.strip()
            self.win.apply_config(cfg)

    def _forget(self) -> None:
        nice = display_name(self.slot, self.win.cfg.slot_name(self.slot))
        if QMessageBox.question(self, "Parar de vigiar", f"Tirar “{nice}” da lista e parar de vigiar esta janela?") \
                == QMessageBox.StandardButton.Yes:
            self.win.engine.forget_slot(self.slot)
            self.win.remove_card(self.slot)


# ---------------------------------------------------------------------------
class EmptyState(QWidget):
    """O que aparece enquanto nenhuma janela do jogo foi encontrada."""

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 60, 20, 40)
        v.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QPixmap.fromImage(icons.draw_brand(96)))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(logo)
        for obj, text in (("emptyTitle", "Procurando o MU Online…"),
                          ("emptyText", "Abra o jogo em modo janela: ele aparece aqui sozinho em alguns segundos."),
                          ("muted", "O MU Sentinel procura janelas com o título “MU” do processo main.exe.")):
            lbl = _label(obj, text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            v.addWidget(lbl)


# ---------------------------------------------------------------------------
class EventsTab(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.f_slot = QComboBox()
        self.f_slot.addItem("Todas as janelas", None)
        for n in range(1, 9):
            self.f_slot.addItem(f"Janela {n}", n)
        self.f_sev = QComboBox()
        for label, val in (("Todos os tipos", None), ("Só críticos", "critico"), ("Só avisos", "aviso"),
                           ("Só informações", "info")):
            self.f_sev.addItem(label, val)
        self.f_text = QLineEdit()
        self.f_text.setPlaceholderText("🔍 buscar…")
        self.f_text.setClearButtonEnabled(True)
        exp = QPushButton("Exportar CSV…")
        exp.setToolTip("Salva a lista (com o filtro atual) numa planilha")
        exp.clicked.connect(self._export)
        for w in (QLabel("Mostrar:"), self.f_slot, self.f_sev, self.f_text):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(exp)
        v.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Quando", "Janela", "Gravidade", "O que aconteceu"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
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
            who = display_name(e.slot, self.win.cfg.slot_name(e.slot)) if e.slot else ""
            vals = (time.strftime("%d/%m %H:%M:%S", time.localtime(e.ts)), who,
                    SEV_TEXT.get(e.severity, e.severity), e.message)
            for j, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if j == 2:
                    it.setForeground(QColor(SEV_COLOR.get(e.severity, theme.GRAY)))
                it.setToolTip(f"tipo: {e.kind}" if j == 3 else "")
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

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
        self._last_snaps: list[SlotSnapshot] = []
        self._status: tuple | None = None

        self.setWindowTitle("MU Sentinel")
        self.setWindowIcon(icons.app_icon())
        self.resize(1360, 820)
        self._build_menu()
        self._build_toolbar()

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(10, 6, 10, 4)
        self.banner = _label("banner")
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.setOpenExternalLinks(False)
        self.banner.linkActivated.connect(self._banner_link)
        self.banner.hide()
        cv.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        cv.addWidget(self.tabs)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(4, 8, 4, 8)
        self.empty = EmptyState()
        pv.addWidget(self.empty)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        pv.addLayout(self.grid)
        pv.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        self.tabs.addTab(scroll, "Janelas do jogo")
        self.events_tab = EventsTab(self)
        self.tabs.addTab(self.events_tab, "Histórico")
        self.setCentralWidget(central)

        self._build_tray()
        self.bridge.snapshots.connect(self.on_snapshots)
        self.bridge.event.connect(self.on_event)
        self.bridge.notify.connect(self.on_notify)
        bus.subscribe("snapshots", self.bridge.snapshots.emit)
        bus.subscribe("event", self.bridge.event.emit)

        self._build_footer()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh_status)
        self._tick.start(1000)
        self.engine.start()
        self.refresh_status()
        from .update_dialog import UpdateController

        self.updates = UpdateController(self)
        self.updates.start()
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
        sb = self.statusBar()
        self.channels_lbl = QLabel()
        self.channels_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.channels_lbl.setContentsMargins(6, 0, 6, 0)
        sb.addWidget(self.channels_lbl)
        # mensagem passageira (print salvo, alerta…) ocupa o lugar dos canais enquanto aparece
        sb.messageChanged.connect(lambda msg: self.channels_lbl.setVisible(not msg))
        self.health_lbl = QLabel()
        self.health_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.health_lbl.setContentsMargins(6, 0, 6, 0)
        up = QLabel()
        up.setTextFormat(Qt.TextFormat.RichText)
        up.setContentsMargins(6, 0, 6, 0)
        up.setToolTip("Versão nova publicada no GitHub. Clique para ver as novidades e atualizar.")
        up.linkActivated.connect(lambda _: self.updates.offer())
        up.hide()
        safe = _label("muted", "🔒 só observa a tela")
        safe.setContentsMargins(6, 0, 6, 0)
        safe.setToolTip("O MU Sentinel só lê a imagem das janelas e informações do Windows.\n"
                        "Nunca aperta teclas, não lê a memória do jogo e não pede a sua senha.")
        v = _label("muted", f"v{__version__} · <a href='novidades'>novidades</a>")
        v.setTextFormat(Qt.TextFormat.RichText)
        v.setContentsMargins(6, 0, 6, 0)
        v.setToolTip("Versão instalada. Clique em 'novidades' para ver o que mudou.")
        v.linkActivated.connect(lambda _: self.show_whats_new(all_versions=True))
        for w in (self.health_lbl, up, safe, v):
            sb.addPermanentWidget(w)
        self.version_label = v
        self.update_label = up

    def set_update_link(self, version: str | None) -> None:
        if version:
            self.update_label.setText(f"<a href='atualizar' style='color:{theme.colors()['link']}; "
                                      f"font-weight:bold'>⬇ atualização {version} disponível</a>")
        self.update_label.setVisible(bool(version))

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
        for text, fn, key in (("Configurações…", self.open_settings, "Ctrl+,"),
                              ("Assistente de configuração…", self.open_wizard, None),
                              ("Abrir pasta de dados", lambda: os.startfile(paths.data_dir()), None)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if key:
                a.setShortcut(key)
            m.addAction(a)
        m.addSeparator()
        q = QAction("Sair do MU Sentinel", self)
        q.triggered.connect(self.quit)
        m.addAction(q)
        c = self.menuBar().addMenu("&Leitura")
        for text, fn in (("Calibrar todas as janelas agora", lambda: self.calibrate_slots(None)),
                         ("Calibração manual (avançado)…", self.open_calibration)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            c.addAction(a)
        h = self.menuBar().addMenu("A&juda")
        for text, fn in (("Manual de uso (abre no navegador)", lambda: QDesktopServices.openUrl(QUrl(MANUAL_URL))),
                         ("Novidades de cada versão", lambda: self.show_whats_new(all_versions=True)),
                         ("Procurar atualizações…", lambda: self.updates.check(manual=True)),
                         ("Sobre e aviso de risco", self.about)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            h.addAction(a)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Principal")
        tb.setMovable(False)
        tb.setStyleSheet("QToolBar { spacing: 6px; padding: 4px 6px; }")
        self.summary_lbl = _label("summary")
        self.summary_lbl.setTextFormat(Qt.TextFormat.RichText)
        tb.addWidget(self.summary_lbl)
        self.ack_btn = QPushButton()
        self.ack_btn.setToolTip("Para de lembrar os alertas abertos (o monitor continua de olho)")
        self.ack_btn.clicked.connect(lambda: self.engine.ack())
        self.ack_action = tb.addWidget(self.ack_btn)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.pause_btn = QToolButton()
        self.pause_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.pause_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.pause_btn.setToolTip("Silencia os alertas por um tempo (o monitor continua de olho)")
        self.pause_btn.clicked.connect(self.toggle_pause)
        pm = QMenu(self)
        for label, mins in (("Pausar 30 min", 30), ("Pausar 1 h", 60), ("Pausar 2 h", 120),
                            ("Pausar até eu retomar", None)):
            a = pm.addAction(label)
            a.triggered.connect(lambda _=False, m=mins: self.engine.pause_alerts(m))
        self.pause_btn.setMenu(pm)
        tb.addWidget(self.pause_btn)
        test = QPushButton("🔔 Testar alertas")
        test.setToolTip("Manda uma mensagem de teste para o Telegram/WhatsApp e para o Windows")
        test.clicked.connect(self.send_test)
        tb.addWidget(test)
        sett = QPushButton("⚙ Configurações")
        sett.setToolTip("Telegram, WhatsApp, nomes das janelas, limites dos alertas… (Ctrl+,)")
        sett.clicked.connect(lambda: self.open_settings())
        tb.addWidget(sett)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip("MU Sentinel")
        menu = QMenu()
        self.tray_header = menu.addAction("MU Sentinel")
        self.tray_header.setEnabled(False)
        menu.addSeparator()
        f = menu.addAction("Abrir o MU Sentinel")
        f.triggered.connect(self.show_normal)
        bold = f.font()
        bold.setBold(True)
        f.setFont(bold)
        self.tray_pause = menu.addAction("Pausar alertas por 1 h")
        self.tray_pause.triggered.connect(self.toggle_pause_tray)
        menu.addAction("Testar alertas").triggered.connect(self.send_test)
        menu.addAction("Configurações…").triggered.connect(lambda: (self.show_normal(), self.open_settings()))
        menu.addSeparator()
        menu.addAction("Sair").triggered.connect(self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal()
                                    if r in (QSystemTrayIcon.ActivationReason.Trigger,
                                             QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()

    # ------------------------------------------------------------------ atualizações
    def on_snapshots(self, snaps: list[SlotSnapshot]) -> None:
        self._last_snaps = snaps
        self._update_status()
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

    def _update_status(self) -> None:
        """Frase do topo, ícone e dica da bandeja, e a bolinha vermelha no ícone da barra de tarefas."""
        a = self.engine.alerts
        paused = a.paused
        sm = summarize(self._last_snaps, paused, a.paused_until if paused else None)
        key = (sm.status, sm.text)
        if key == self._status:
            return
        self._status = key
        color = STATUS_COLOR.get(sm.status or "", theme.GRAY)
        self.summary_lbl.setText(f"<span style='color:{color}'>●</span>&nbsp;{sm.text}")
        self.tray.setIcon(icons.app_icon(sm.status))
        self.tray.setToolTip(f"MU Sentinel · {sm.text}"[:127])
        self.tray_header.setText(sm.text)
        self.setWindowIcon(icons.app_icon("critico" if sm.status == "critico" else None))

    def _relayout(self) -> None:
        cols = max(1, (self.width() - 40) // CARD_MIN_W)
        if cols == getattr(self, "_cols", None) and len(self.cards) == getattr(self, "_ncards", None):
            return
        self._cols, self._ncards = cols, len(self.cards)
        for card in self.cards.values():
            self.grid.removeWidget(card)
        for i, (n, card) in enumerate(sorted(self.cards.items())):
            self.grid.addWidget(card, i // cols, i % cols, Qt.AlignmentFlag.AlignTop)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self._last_snaps:
            self._render(self._last_snaps)  # voltou da bandeja: mostra o estado mais recente na hora
        if getattr(self, "_pending_notes", ""):
            QTimer.singleShot(500, self.show_whats_new)  # atualizado com o app minimizado
        if hasattr(self, "updates"):
            self.updates.on_window_shown()  # versão nova achada com o app na bandeja

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.WindowStateChange and not self.isMinimized() and self._last_snaps:
            self._render(self._last_snaps)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.cards:
            self._relayout()

    def remove_card(self, slot: int) -> None:
        card = self.cards.pop(slot, None)
        if card:
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
            self._relayout()
        self.empty.setVisible(not self.cards)

    def on_event(self, ev: Event) -> None:
        self.events_tab.schedule()
        if ev.severity == "critico" and ev.kind == "alerta":
            who = display_name(ev.slot, self.cfg.slot_name(ev.slot)) if ev.slot else "MU Sentinel"
            self.statusBar().showMessage(f"{time.strftime('%H:%M')} {who}: {ev.message}", 30000)

    def on_notify(self, text: str) -> None:
        lines = text.splitlines()
        title = lines[0] if lines else "MU Sentinel"
        body = "\n".join(lines[1:]) or title
        icon = QSystemTrayIcon.MessageIcon.Critical if "CRÍTICO" in title else (
            QSystemTrayIcon.MessageIcon.Warning if "AVISO" in title else QSystemTrayIcon.MessageIcon.Information)
        self.tray.showMessage(title, body, icon, 15000)

    def refresh_status(self) -> None:
        a = self.engine.alerts
        if a.paused:
            until = a.paused_until
            txt = "▶ Retomar alertas" + ("" if until == float("inf")
                                         else f" (pausados até {time.strftime('%H:%M', time.localtime(until))})")
            self.pause_btn.setText(txt)
            self.tray_pause.setText("Retomar alertas")
        else:
            self.pause_btn.setText("⏸ Pausar alertas")
            self.tray_pause.setText("Pausar alertas por 1 h")
        n = len(a.active)
        self.ack_btn.setText(f"✔ OK, vi {'o alerta' if n == 1 else f'os {n} alertas'}")
        self.ack_action.setVisible(bool(n))

        parts = []
        for name, ok, detail in self.engine.notifier_status():
            color = theme.GREEN if ok else theme.RED
            short = "Windows" if name == "Notificação do Windows" else name
            parts.append(f"<span style='color:{color}'>●</span> {short}"
                         + ("" if ok else f" <span style='color:{color}'>({detail})</span>"))
        self.channels_lbl.setText("Alertas vão para: " + " &nbsp; ".join(parts))
        self.channels_lbl.setToolTip("\n".join(f"{name}: {detail}" for name, _, detail
                                               in self.engine.notifier_status()))
        alive = self.engine.alive()
        up = fmt_dur(time.time() - self.engine.started_at)
        self.health_lbl.setText(f"<span style='color:{theme.GREEN}'>●</span> vigiando" if alive
                                else f"<b style='color:{theme.RED}'>● monitor parado!</b>")
        self.health_lbl.setToolTip(f"Aberto há {up} · cada leitura leva {self.engine.cycle_ms:.0f} ms")
        self._update_banner()
        self._update_status()

    def _update_banner(self) -> None:
        msgs = []
        cm, tg = self.cfg.notifiers.callmebot, self.cfg.notifiers.telegram
        if not (cm.enabled and cm.recipients) and not (tg.enabled and tg.chats):
            msgs.append("📱 <b>Os alertas ainda não chegam no celular</b>, só neste PC. "
                        "<a href='telegram'>Ligar o Telegram</a> (grátis, 2 minutos) · "
                        "<a href='whatsapp'>WhatsApp</a>")
        if self.engine.protection_blocked:
            msgs.append(f"<b>Monitoramento limitado em {self.engine.protection_blocked} janela(s):</b> o anti-cheat do "
                        "jogo (GameGuard) não deixa este programa ver de qual processo elas são. O MU Sentinel não "
                        "contorna isso: segue pela imagem (morte, caça parada, travamento, janela fechada), mas não "
                        "checa a conexão com o servidor. Queda da internet deste PC continua sendo detectada.")
        if self.engine.internet.ok is False:
            msgs.append("<b>Sem internet</b>: os alertas para o celular ficam na fila até a conexão voltar.")
        for w in self.engine.power_warnings:
            msgs.append(w + " <a href='energia'>Abrir opções de energia</a>")
        if self.engine.alerts.paused:
            msgs.append("⏸ <b>Alertas pausados.</b> <a href='retomar'>Retomar agora</a>")
        link = theme.colors()["link"]
        html = "<br>".join(msgs).replace("<a ", f"<a style='color:{link}; font-weight:bold' ")
        if html != getattr(self, "_banner_html", None):
            self._banner_html = html
            self.banner.setText(html)
            self.banner.setVisible(bool(html))

    def _banner_link(self, link: str) -> None:
        if link in ("whatsapp", "telegram"):
            self.open_settings(tab=link)
        elif link == "energia":
            os.startfile("ms-settings:powersleep")
        elif link == "retomar":
            self.engine.resume_alerts()
            self.refresh_status()

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
        self.statusBar().showMessage("Alerta de teste enviado para todos os canais ligados.", 8000)

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
                parts.append(f"<b>{display_name(n, self.cfg.slot_name(n))}</b><br>" + body.replace("\n", "<br>"))
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
        QMessageBox.about(self, "MU Sentinel",
                          f"<b>MU Sentinel {__version__}</b><br>Vigia as janelas do MU Online e avisa no celular."
                          f"<br><br><b>Aviso de risco:</b> {RISK_TEXT}<br><br>"
                          "O MU Sentinel só lê a imagem das janelas e informações do Windows: "
                          "não aperta teclas, não lê a memória e não mexe nos arquivos do jogo.")

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
            self.tray.showMessage("O MU Sentinel continua vigiando",
                                  "Ele fica aqui perto do relógio. Para sair: botão direito no ícone → Sair.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)

    def quit(self) -> None:
        if QMessageBox.question(self, "Sair", "Sair do MU Sentinel? O monitoramento e os alertas param.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.quit_now()

    def quit_now(self) -> None:
        """Fecha sem perguntar (usado também para concluir uma atualização)."""
        self._quitting = True
        self.engine.stop()
        self.tray.hide()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
