"""Tela de Configurações: WhatsApp (destinatários), monitor, limiares, alertas, cidades e slots.

Cada destinatário do WhatsApp tem número e chave do CallMeBot próprios: quem recebe o
app de um colega cadastra o próprio número aqui. As chaves vão para o Gerenciador de
Credenciais do Windows, nunca para o config.yaml.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from ..core import secrets
from ..core.config import Config, WhatsAppRecipient, mask_phone, normalize_phone
from ..core.notifiers.callmebot import SETUP_URL, CallMeBotNotifier

TEST_TEXT = "[TESTE] MU Sentinel\nSe você recebeu esta mensagem, os alertas vão chegar neste WhatsApp."

CALLMEBOT_HELP = f"""
<b>Como ativar o WhatsApp de cada pessoa (grátis, uma vez por número):</b>
<ol>
<li>No celular que vai <b>receber</b> os alertas, salve o contato do bot do CallMeBot.
O número do bot muda de tempos em tempos: <b>confira o número atual no site oficial</b>:<br>
<a href="{SETUP_URL}">{SETUP_URL}</a></li>
<li>Mande para esse contato, pelo WhatsApp, a mensagem: <code>I allow callmebot to send me messages</code></li>
<li>O bot responde com a sua <b>apikey</b> (um número). Clique em <b>Adicionar</b> abaixo e cadastre
seu telefone (com DDI e DDD, ex.: +55 11 99999-0000) e essa chave.</li>
<li>Clique em <b>Testar</b>. A mensagem chega em alguns segundos.</li>
</ol>
Para um amigo receber também: ele faz os passos 1–3 no celular dele e você adiciona o número e a chave dele.
"""


class _TestBridge(QObject):
    done = Signal(bool, str)


def run_test(recipient: WhatsAppRecipient, apikey: str | None, callback) -> None:
    """Envia a mensagem de teste numa thread e chama callback(ok, texto) na thread da GUI."""
    bridge = _TestBridge()
    bridge.done.connect(callback, Qt.ConnectionType.QueuedConnection)

    def work():
        n = CallMeBotNotifier([recipient], start=False)
        ok, msg = n.send_now(recipient, TEST_TEXT, apikey)
        bridge.done.emit(ok, msg)

    run_test._keep = bridge  # mantém vivo até o sinal chegar
    threading.Thread(target=work, name="teste-whatsapp", daemon=True).start()


class RecipientDialog(QDialog):
    def __init__(self, parent=None, recipient: WhatsAppRecipient | None = None):
        super().__init__(parent)
        self.setWindowTitle("Número do WhatsApp")
        self.original = recipient
        f = QFormLayout(self)
        self.name = QLineEdit(recipient.name if recipient else "")
        self.name.setPlaceholderText("ex.: Eu, João…")
        self.phone = QLineEdit(f"+{recipient.phone}" if recipient else "")
        self.phone.setPlaceholderText("+55 11 99999-0000")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        has = recipient is not None and secrets.has_secret(recipient.secret_key)
        self.key.setPlaceholderText("chave já cadastrada (deixe em branco para manter)" if has else "apikey que o bot mandou")
        self.enabled = QCheckBox("Receber alertas")
        self.enabled.setChecked(recipient.enabled if recipient else True)
        f.addRow("Nome:", self.name)
        f.addRow("Telefone (com DDI):", self.phone)
        f.addRow("Chave do CallMeBot:", self.key)
        f.addRow("", self.enabled)
        self.test_btn = QPushButton("Testar agora")
        self.test_btn.clicked.connect(self._test)
        self.test_msg = QLabel("")
        self.test_msg.setWordWrap(True)
        f.addRow(self.test_btn, self.test_msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.result_recipient: WhatsAppRecipient | None = None

    def _build(self) -> WhatsAppRecipient | None:
        try:
            return WhatsAppRecipient(nome=self.name.text().strip(), telefone=self.phone.text(),
                                     ativo=self.enabled.isChecked())
        except Exception:
            QMessageBox.warning(self, "Telefone", "Telefone inválido: use DDI + DDD + número, ex.: +55 11 99999-0000.")
            return None

    def _key_value(self, r: WhatsAppRecipient) -> str | None:
        k = self.key.text().strip()
        if k:
            return k
        if self.original and normalize_phone(self.original.phone) == r.phone:
            return secrets.get_secret(self.original.secret_key)
        return secrets.get_secret(r.secret_key)

    def _test(self) -> None:
        r = self._build()
        if r is None:
            return
        key = self._key_value(r)
        if not key:
            self.test_msg.setText("Informe a chave do CallMeBot.")
            return
        self.test_btn.setEnabled(False)
        self.test_msg.setText("Enviando…")
        run_test(r, key, self._tested)

    def _tested(self, ok: bool, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_msg.setText(("✔ " if ok else "✖ ") + msg)

    def _accept(self) -> None:
        r = self._build()
        if r is None:
            return
        key = self._key_value(r)
        if not key:
            QMessageBox.warning(self, "Chave", "Informe a chave (apikey) que o CallMeBot mandou para este número.")
            return
        try:
            secrets.set_secret(r.secret_key, key)
        except Exception as exc:
            QMessageBox.critical(self, "Chave", f"Não consegui guardar a chave no Gerenciador de Credenciais: "
                                                f"{type(exc).__name__}")
            return
        if self.original and self.original.phone != r.phone:
            secrets.delete_secret(self.original.secret_key)
        self.result_recipient = r
        self.accept()


def _spin(v: float, lo: float, hi: float, step: float = 1, decimals: int = 0, suffix: str = ""):
    w = QDoubleSpinBox() if decimals else QSpinBox()
    if decimals:
        w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setValue(v if decimals else int(v))
    if suffix:
        w.setSuffix(suffix)
    return w


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None, tab: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Configurações — MU Sentinel")
        self.resize(720, 560)
        self.cfg = cfg.model_copy(deep=True)
        self.recipients = [r.model_copy() for r in self.cfg.notifiers.callmebot.recipients]
        self.removed: list[WhatsAppRecipient] = []
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._tab_whatsapp(), "WhatsApp")
        self.tabs.addTab(self._tab_monitor(), "Monitor")
        self.tabs.addTab(self._tab_thresholds(), "Limiares")
        self.tabs.addTab(self._tab_alerts(), "Alertas")
        self.tabs.addTab(self._tab_cities(), "Cidades")
        self.tabs.addTab(self._tab_slots(), "Slots")
        if tab == "whatsapp":
            self.tabs.setCurrentIndex(0)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ------------------------------------------------------------------ WhatsApp
    def _tab_whatsapp(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.cm_enabled = QCheckBox("Enviar alertas pelo WhatsApp (CallMeBot)")
        self.cm_enabled.setChecked(self.cfg.notifiers.callmebot.enabled)
        v.addWidget(self.cm_enabled)
        help_lbl = QLabel(CALLMEBOT_HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(help_lbl)
        self.rtable = QTableWidget(0, 4)
        self.rtable.setHorizontalHeaderLabels(["Nome", "Telefone", "Chave", "Recebe"])
        self.rtable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rtable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rtable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rtable.doubleClicked.connect(lambda *_: self._edit_recipient())
        v.addWidget(self.rtable)
        row = QHBoxLayout()
        for text, fn in (("Adicionar", self._add_recipient), ("Editar", self._edit_recipient),
                         ("Remover", self._remove_recipient), ("Testar selecionado", self._test_recipient)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.rtest_msg = QLabel("")
        self.rtest_msg.setWordWrap(True)
        v.addWidget(self.rtest_msg)
        self.win_enabled = QCheckBox("Mostrar notificação do Windows (canal local, sempre disponível)")
        self.win_enabled.setChecked(self.cfg.notifiers.windows.enabled)
        v.addWidget(self.win_enabled)
        self.cm_interval = _spin(self.cfg.notifiers.callmebot.min_interval_s, 1, 120, 1, 1, " s")
        f = QFormLayout()
        f.addRow("Intervalo mínimo entre mensagens:", self.cm_interval)
        v.addLayout(f)
        self._fill_recipients()
        return w

    def _fill_recipients(self) -> None:
        self.rtable.setRowCount(len(self.recipients))
        for i, r in enumerate(self.recipients):
            has = secrets.has_secret(r.secret_key)
            for j, txt in enumerate((r.name or "—", mask_phone(r.phone), "cadastrada" if has else "FALTA",
                                     "sim" if r.enabled else "não")):
                it = QTableWidgetItem(txt)
                if j == 2 and not has:
                    it.setForeground(Qt.GlobalColor.red)
                self.rtable.setItem(i, j, it)

    def _selected(self) -> int | None:
        rows = self.rtable.selectionModel().selectedRows()
        return rows[0].row() if rows else (0 if len(self.recipients) == 1 else None)

    def _add_recipient(self) -> None:
        d = RecipientDialog(self)
        if d.exec() and d.result_recipient:
            r = d.result_recipient
            self.recipients = [x for x in self.recipients if x.phone != r.phone] + [r]
            self.cm_enabled.setChecked(True)
            self._fill_recipients()

    def _edit_recipient(self) -> None:
        i = self._selected()
        if i is None:
            return
        d = RecipientDialog(self, self.recipients[i])
        if d.exec() and d.result_recipient:
            self.recipients[i] = d.result_recipient
            self._fill_recipients()

    def _remove_recipient(self) -> None:
        i = self._selected()
        if i is None:
            return
        r = self.recipients[i]
        if QMessageBox.question(self, "Remover", f"Remover {r.name or mask_phone(r.phone)}?") \
                == QMessageBox.StandardButton.Yes:
            self.removed.append(self.recipients.pop(i))
            self._fill_recipients()

    def _test_recipient(self) -> None:
        i = self._selected()
        if i is None:
            self.rtest_msg.setText("Selecione um número na tabela.")
            return
        r = self.recipients[i]
        self.rtest_msg.setText(f"Enviando teste para {r.name or mask_phone(r.phone)}…")
        run_test(r, None, lambda ok, msg: self.rtest_msg.setText(("✔ " if ok else "✖ ") + msg))

    # ------------------------------------------------------------------ demais abas
    def _tab_monitor(self) -> QWidget:
        m = self.cfg.monitor
        w = QWidget()
        f = QFormLayout(w)
        self.m_title = QLineEdit(m.window_title)
        self.m_proc = QLineEdit(m.process_name)
        self.m_interval = _spin(m.interval_s, 0.5, 30, 0.5, 1, " s")
        self.m_confirm = _spin(m.confirm_cycles, 1, 10)
        self.m_awake = QCheckBox("Impedir o PC de suspender enquanto o app roda")
        self.m_awake.setChecked(m.keep_awake)
        self.m_display = QCheckBox("Manter a tela ligada (necessário em notebooks com Modern Standby)")
        self.m_display.setChecked(m.keep_display_on)
        f.addRow("Título da janela do jogo:", self.m_title)
        f.addRow("Processo do jogo:", self.m_proc)
        f.addRow("Ciclo do monitor:", self.m_interval)
        f.addRow("Ciclos iguais para confirmar estado:", self.m_confirm)
        f.addRow(self.m_awake)
        f.addRow(self.m_display)
        from ..core import autostart

        self.m_autostart = QCheckBox("Iniciar com o Windows (minimizado na bandeja)")
        self.m_autostart.setChecked(autostart.is_enabled())
        f.addRow(self.m_autostart)
        return w

    def _tab_thresholds(self) -> QWidget:
        t = self.cfg.thresholds
        w = QWidget()
        f = QFormLayout(w)
        self.t_hp = _spin(t.hp_low_pct, 0, 100, 5, 0, " %")
        self.t_hp0 = _spin(t.death_hp_reads, 1, 10)
        self.t_exp = _spin(t.exp_stall_min, 0.5, 120, 0.5, 1, " min")
        self.t_helper = _spin(t.helper_stall_s, 5, 600, 5, 0, " s")
        self.t_hung = _spin(t.hung_s, 2, 300, 1, 0, " s")
        self.t_frozen = _spin(t.frozen_s, 5, 600, 5, 0, " s")
        self.t_unread = _spin(t.unreadable_warn_min, 0.5, 60, 0.5, 1, " min")
        self.t_city = _spin(t.city_grace_s, 0, 600, 5, 0, " s")
        f.addRow("Aviso de HP baixo abaixo de:", self.t_hp)
        f.addRow("Leituras de HP 0 para morte:", self.t_hp0)
        f.addRow("Caça parada (sem EXP) após:", self.t_exp)
        f.addRow("Helper parado (Hunting Time) após:", self.t_helper)
        f.addRow("Janela sem responder por:", self.t_hung)
        f.addRow("Imagem congelada por:", self.t_frozen)
        f.addRow("Avisar HUD ilegível após:", self.t_unread)
        f.addRow("Ida à cidade conta como manual se você\nmexeu no PC nos últimos:", self.t_city)
        return w

    def _tab_alerts(self) -> QWidget:
        a = self.cfg.alerts
        w = QWidget()
        f = QFormLayout(w)
        self.a_repeat = _spin(a.critical_repeat_min, 1, 120, 1, 0, " min")
        self.a_max = _spin(a.max_repeats_no_reply, 0, 20)
        self.a_cool = _spin(a.cooldown_min, 0, 120, 1, 0, " min")
        self.q_on = QCheckBox("Ativar horário silencioso (WhatsApp)")
        self.q_on.setChecked(a.quiet.enabled)
        self.q_start = QTimeEdit(QTime.fromString(a.quiet.start, "HH:mm"))
        self.q_end = QTimeEdit(QTime.fromString(a.quiet.end, "HH:mm"))
        for q in (self.q_start, self.q_end):
            q.setDisplayFormat("HH:mm")
        self.q_crit = QCheckBox("Deixar alertas críticos passarem no horário silencioso")
        self.q_crit.setChecked(a.quiet.allow_critical)
        f.addRow("Repetir alerta crítico a cada:", self.a_repeat)
        f.addRow("Máximo de repetições (sem resposta):", self.a_max)
        f.addRow("Mesmo alerta do mesmo slot no máximo 1× a cada:", self.a_cool)
        f.addRow(self.q_on)
        f.addRow("Início:", self.q_start)
        f.addRow("Fim:", self.q_end)
        f.addRow(self.q_crit)
        return w

    def _tab_cities(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Cidades (uma por linha). Sair do spot para uma cidade sem você mexer no PC conta como morte."))
        self.cities = QPlainTextEdit("\n".join(self.cfg.cities))
        v.addWidget(self.cities)
        return w

    def _tab_slots(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Nome de cada slot (aparece nos alertas). O teto de nível vale a partir da Fase 3."))
        slots = sorted(self.cfg.slots.items())
        self.stable = QTableWidget(len(slots), 3)
        self.stable.setHorizontalHeaderLabels(["Slot", "Nome", "Teto de nível"])
        self.stable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, (n, s) in enumerate(slots):
            it = QTableWidgetItem(str(n))
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.stable.setItem(i, 0, it)
            self.stable.setItem(i, 1, QTableWidgetItem(s.name))
            sp = _spin(s.level_cap, 0, 4)
            self.stable.setCellWidget(i, 2, sp)
        v.addWidget(self.stable)
        return w

    # ------------------------------------------------------------------
    def _accept(self) -> None:
        c = self.cfg
        try:
            c.notifiers.callmebot.enabled = self.cm_enabled.isChecked()
            c.notifiers.callmebot.recipients = self.recipients
            c.notifiers.callmebot.min_interval_s = self.cm_interval.value()
            c.notifiers.windows.enabled = self.win_enabled.isChecked()
            c.monitor.window_title = self.m_title.text().strip() or "MU"
            c.monitor.process_name = self.m_proc.text().strip()
            c.monitor.interval_s = self.m_interval.value()
            c.monitor.confirm_cycles = self.m_confirm.value()
            c.monitor.keep_awake = self.m_awake.isChecked()
            c.monitor.keep_display_on = self.m_display.isChecked()
            t = c.thresholds
            t.hp_low_pct, t.death_hp_reads = self.t_hp.value(), self.t_hp0.value()
            t.exp_stall_min, t.helper_stall_s = self.t_exp.value(), self.t_helper.value()
            t.hung_s, t.frozen_s = self.t_hung.value(), self.t_frozen.value()
            t.unreadable_warn_min, t.city_grace_s = self.t_unread.value(), self.t_city.value()
            a = c.alerts
            a.critical_repeat_min, a.max_repeats_no_reply = self.a_repeat.value(), self.a_max.value()
            a.cooldown_min = self.a_cool.value()
            a.quiet.enabled = self.q_on.isChecked()
            a.quiet.start = self.q_start.time().toString("HH:mm")
            a.quiet.end = self.q_end.time().toString("HH:mm")
            a.quiet.allow_critical = self.q_crit.isChecked()
            c.cities = [x.strip() for x in self.cities.toPlainText().splitlines() if x.strip()]
            for i in range(self.stable.rowCount()):
                n = int(self.stable.item(i, 0).text())
                s = c.slot(n)
                s.name = self.stable.item(i, 1).text().strip() or f"Slot {n}"
                s.level_cap = self.stable.cellWidget(i, 2).value()
            Config.model_validate(c.model_dump(by_alias=True))
        except Exception as exc:
            QMessageBox.warning(self, "Configurações", f"Valor inválido: {exc}")
            return
        if c.notifiers.callmebot.enabled and not any(secrets.has_secret(r.secret_key) for r in self.recipients):
            QMessageBox.information(self, "WhatsApp", "Nenhum número tem chave cadastrada: os alertas pelo "
                                                      "WhatsApp não vão sair até você cadastrar.")
        from ..core import autostart

        try:
            if self.m_autostart.isChecked() != autostart.is_enabled() or self.m_autostart.isChecked():
                autostart.set_enabled(self.m_autostart.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Iniciar com o Windows", f"Não consegui alterar: {exc}")
        keep = {r.phone for r in self.recipients}
        for r in self.removed:
            if r.phone not in keep:
                secrets.delete_secret(r.secret_key)
        self.accept()

    def result_config(self) -> Config:
        return self.cfg
