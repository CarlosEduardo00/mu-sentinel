"""Assistente de primeira execução.

1. Detectar os clients abertos e nomear cada slot (com miniatura)
2. Perfil de resolução: usar o de fábrica, calibrar ou importar de um colega
3. WhatsApp: cadastrar o(s) número(s) e mandar mensagem de teste
4. Nível de risco (padrão 0) com o aviso
5. Iniciar com o Windows
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QRadioButton, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from ..core import autostart, paths, secrets, winapi
from ..core.config import LEVEL_NAMES, RISK_TEXT, Config, is_shop_name, mask_phone
from ..core.discovery import Discovery, default_store
from .qtutil import bgr_to_pixmap
from .settings_dialog import CALLMEBOT_HELP, RecipientDialog, run_test, shop_hint_label


class SlotsPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("1. Janelas do jogo")
        self.setSubTitle("Abra os clients do MU que você quer monitorar (até 4) e dê um nome a cada slot. "
                         "O nome aparece nos alertas.")
        v = QVBoxLayout(self)
        v.addWidget(shop_hint_label())
        self.grid = QGridLayout()
        v.addLayout(self.grid)
        self.empty = QLabel("Nenhuma janela do MU encontrada. Abra o jogo e clique em Procurar de novo.\n"
                            "(Dá para seguir sem janelas: elas aparecem no painel quando abrirem.)")
        self.empty.setStyleSheet("color:#888;")
        v.addWidget(self.empty)
        b = QPushButton("Procurar de novo")
        b.clicked.connect(self.scan)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch()
        self.names: dict[int, QLineEdit] = {}

    def initializePage(self):  # noqa: N802
        self.scan()

    def scan(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.names.clear()
        bindings = self.wiz.discovery.refresh()
        self.wiz.sizes = set()
        cap = None
        try:
            from ..core.capture import make_backend

            cap = make_backend("auto")
        except Exception:
            pass
        for i, (slot, b) in enumerate(sorted(bindings.items())):
            thumb = QLabel()
            thumb.setFixedSize(200, 150)
            thumb.setStyleSheet("background:#111; color:#888;")
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setText("minimizada" if b.info and b.info.minimized else "sem imagem")
            if cap and b.info and not b.info.minimized:
                try:
                    f = cap.grab(b.hwnd)
                    self.wiz.sizes.add(f.size)
                    thumb.setPixmap(bgr_to_pixmap(f.image).scaled(200, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                                  Qt.TransformationMode.SmoothTransformation))
                except Exception:
                    pass
            if b.info:
                self.wiz.sizes.add(tuple(b.info.client_size))
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.addWidget(thumb)
            name = QLineEdit(self.wiz.cfg.slot_name(slot))
            bv.addWidget(QLabel(f"Slot {slot}"))
            bv.addWidget(name)
            tag = QLabel()
            tag.setStyleSheet("color:#b26a00;")

            def show_tag(text, tag=tag):
                tag.setText("🏪 Loja: acompanha o Gremory Case (Personal Shop)" if is_shop_name(text) else "")

            name.textChanged.connect(show_tag)
            show_tag(name.text())
            bv.addWidget(tag)
            self.names[slot] = name
            self.grid.addWidget(box, i // 2, i % 2)
        if cap:
            cap.close()
        self.empty.setVisible(not bindings)

    def validatePage(self) -> bool:  # noqa: N802
        for slot, ed in self.names.items():
            self.wiz.cfg.slot(slot).name = ed.text().strip() or f"Slot {slot}"
        return True


class ProfilePage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("2. Perfil de resolução")
        self.setSubTitle("O app lê o HUD por regiões calibradas para o tamanho real da janela. "
                         "Colegas com a mesma resolução podem trocar o perfil (.json, sem segredos).")
        v = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.status)
        row = QHBoxLayout()
        for text, fn in (("Abrir calibração…", self.calibrate), ("Importar perfil…", self.import_profile),
                         ("Exportar meu perfil…", self.export_profile)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()

    def initializePage(self):  # noqa: N802
        self.refresh()

    def refresh(self) -> None:
        lines = []
        for w, h in sorted(self.wiz.sizes) or []:
            if paths.profile_path(w, h).exists():
                st = "<b style='color:#2e9d47'>calibrado neste PC</b>"
            elif paths.seed_profile_path(w, h).exists():
                st = "<b style='color:#2e9d47'>pronto (veio com o app)</b>"
            elif paths.has_profile(w, h):
                st = "<b style='color:#d18b00'>só as regiões de fábrica: rode a calibração e ensine os números</b>"
            else:
                st = "<b style='color:#c62828'>sem perfil: calibre ou importe de um colega</b>"
            lines.append(f"Janela de <b>{w}x{h}</b> pixels reais: {st}")
        if not lines:
            lines.append("Nenhuma janela aberta agora. Perfis que já vêm com o app: 800x600 e 1280x960.")
        lines.append("<br><small>800x600 = client em 800x600 com a escala do Windows em 100%; "
                     "1280x960 = mesmo client com a escala em 125%.</small>")
        self.status.setText("<br>".join(lines))

    def calibrate(self) -> None:
        from .calibration import CalibrationWindow

        self._calib = CalibrationWindow()
        self._calib.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._calib.destroyed.connect(lambda *_: self.refresh())
        self._calib.show()

    def import_profile(self) -> None:
        from ..core.perception.profile import Profile

        path, _ = QFileDialog.getOpenFileName(self, "Importar perfil", str(Path.home()), "Perfil (*.json)")
        if not path:
            return
        try:
            prof = Profile.load(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Importar", f"Arquivo inválido: {exc}")
            return
        w, h = prof.client_size
        dest = paths.profile_path(w, h)
        if dest.exists() and QMessageBox.question(self, "Importar", f"Substituir o perfil {w}x{h} deste PC?") \
                != QMessageBox.StandardButton.Yes:
            return
        prof.save(dest)
        self.wiz.sizes.add((w, h))
        self.refresh()
        QMessageBox.information(self, "Importar", f"Perfil {w}x{h} importado.")

    def export_profile(self) -> None:
        sizes = sorted(self.wiz.sizes) or [(800, 600)]
        w, h = sizes[0]
        prof = paths.load_or_default_profile(w, h)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar perfil", str(Path.home() / f"perfil_mu_{w}x{h}.json"),
                                              "Perfil (*.json)")
        if path:
            prof.save(Path(path))
            QMessageBox.information(self, "Exportar", "Perfil exportado (não contém senhas nem chaves).")


class WhatsAppPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("3. Alertas no celular")
        self.setSubTitle("Escolha por onde os alertas chegam no celular: Telegram (recomendado) ou WhatsApp "
                         "pelo CallMeBot. Dá para usar os dois.")
        from PySide6.QtWidgets import QTabWidget

        from .telegram_panel import TelegramPanel

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        self.tg_panel = TelegramPanel(wiz.cfg)
        tabs.addTab(self.tg_panel, "Telegram")
        wa = QWidget()
        tabs.addTab(wa, "WhatsApp (CallMeBot)")
        v = QVBoxLayout(wa)
        help_lbl = QLabel(CALLMEBOT_HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(help_lbl)
        self.list = QListWidget()
        v.addWidget(self.list)
        row = QHBoxLayout()
        for text, fn in (("Adicionar número…", self.add), ("Remover", self.remove), ("Testar selecionado", self.test)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        outer.addWidget(QLabel("Dá para pular agora e cadastrar depois em Configurações. "
                               "A notificação do Windows funciona sempre."))

    def initializePage(self):  # noqa: N802
        self.fill()

    def validatePage(self) -> bool:  # noqa: N802
        self.tg_panel.apply_to(self.wiz.cfg)
        return True

    def fill(self) -> None:
        self.list.clear()
        for r in self.wiz.cfg.notifiers.callmebot.recipients:
            key = "chave ok" if secrets.has_secret(r.secret_key) else "SEM CHAVE"
            self.list.addItem(f"{r.name or 'sem nome'} · {mask_phone(r.phone)} · {key}")

    def add(self) -> None:
        d = RecipientDialog(self)
        if d.exec() and d.result_recipient:
            cm = self.wiz.cfg.notifiers.callmebot
            r = d.result_recipient
            cm.recipients = [x for x in cm.recipients if x.phone != r.phone] + [r]
            cm.enabled = True
            self.fill()

    def remove(self) -> None:
        i = self.list.currentRow()
        cm = self.wiz.cfg.notifiers.callmebot
        if 0 <= i < len(cm.recipients):
            r = cm.recipients[i]
            cm.recipients = [x for j, x in enumerate(cm.recipients) if j != i]
            secrets.delete_secret(r.secret_key)
            self.fill()

    def test(self) -> None:
        i = self.list.currentRow()
        rs = self.wiz.cfg.notifiers.callmebot.recipients
        if not rs:
            self.msg.setText("Adicione um número primeiro.")
            return
        r = rs[i if 0 <= i < len(rs) else 0]
        self.msg.setText("Enviando…")
        run_test(r, None, lambda ok, m: self.msg.setText(("✔ " if ok else "✖ ") + m))


class LevelPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("4. Nível de risco")
        self.setSubTitle("Quanto o app pode agir sozinho nas janelas do jogo.")
        v = QVBoxLayout(self)
        warn = QLabel(f"<b>Aviso:</b> {RISK_TEXT}")
        warn.setWordWrap(True)
        warn.setStyleSheet("background:#fff4d6; color:#5a4300; padding:8px; border:1px solid #e6c56a;")
        v.addWidget(warn)
        self.group = QButtonGroup(self)
        desc = ["só monitora, alerta e tira print — nenhuma tecla vai para o jogo",
                "ações só quando você manda (WhatsApp ou botão)",
                "religa o Helper quando para; poção com HP baixo",
                "buff/ação a cada N minutos",
                "após morte volta ao spot; client fechado: reabre e para no login"]
        for n, d in enumerate(desc):
            rb = QRadioButton(f"Nível {n} · {LEVEL_NAMES[n]}: {d}")
            if n > 0:
                rb.setEnabled(False)
                rb.setToolTip("Desativado: o MU Sentinel não envia teclas ao jogo.")
            self.group.addButton(rb, n)
            v.addWidget(rb)
        self.group.button(0).setChecked(True)
        note = QLabel("Os níveis 1 a 4 estão desativados: o MU Sentinel só observa e avisa, "
                      "nunca envia teclas ao jogo.")
        note.setStyleSheet("color:#888;")
        v.addWidget(note)
        v.addStretch()

    def validatePage(self) -> bool:  # noqa: N802
        self.wiz.cfg.level = 0
        return True


class StartupPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("5. Iniciar com o Windows")
        v = QVBoxLayout(self)
        self.auto = QCheckBox("Abrir o MU Sentinel quando eu entrar no Windows (minimizado na bandeja)")
        self.auto.setChecked(True)
        v.addWidget(self.auto)
        info = QLabel("Usa a lista de inicialização do seu usuário (não precisa de administrador). "
                      "Dá para mudar depois em Configurações → Monitor.\n\n"
                      "Dica: deixe o PC sem suspender enquanto os personagens caçam. "
                      "Se suspender, o jogo e os alertas param juntos.")
        info.setWordWrap(True)
        v.addWidget(info)
        v.addStretch()

    def initializePage(self):  # noqa: N802
        self.auto.setChecked(autostart.is_enabled() or not self.wiz.cfg.wizard_done)

    def validatePage(self) -> bool:  # noqa: N802
        try:
            autostart.set_enabled(self.auto.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Iniciar com o Windows", f"Não consegui alterar: {exc}")
        return True


class SetupWizard(QWizard):
    def __init__(self, cfg: Config, parent=None, discovery: Discovery | None = None):
        super().__init__(parent)
        winapi.enable_dpi_awareness()
        self.setWindowTitle("Assistente — MU Sentinel")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(820, 640)
        self.cfg = cfg.model_copy(deep=True)
        self.discovery = discovery or Discovery(cfg.monitor.window_title, cfg.monitor.process_name,
                                                store=default_store())
        self.sizes: set[tuple[int, int]] = set()
        for page in (SlotsPage(self), ProfilePage(self), WhatsAppPage(self), LevelPage(self), StartupPage(self)):
            self.addPage(page)
        self.setButtonText(QWizard.WizardButton.NextButton, "Avançar >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Voltar")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Concluir")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")

    def accept(self) -> None:
        from .. import __version__

        if not self.cfg.wizard_done:  # instalação nova: as novidades começam a contar desta versão
            self.cfg.last_seen_version = __version__
        self.cfg.wizard_done = True
        super().accept()

    def result_config(self) -> Config:
        return self.cfg
