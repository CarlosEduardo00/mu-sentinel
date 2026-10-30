"""Painel de configuração do Telegram (usado nas Configurações e no assistente)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import secrets
from ..core.config import TELEGRAM_TOKEN_KEY, Config, TelegramChat
from ..core.notifiers.telegram import BOTFATHER_URL, TelegramApi, TelegramError, send_test

TEST_TEXT = "[TESTE] MU Sentinel\nSe você recebeu esta mensagem, os alertas vão chegar neste Telegram."

HELP = f"""
<b>Como ativar (grátis, uns 2 minutos):</b>
<ol>
<li>No Telegram, abra o <a href="{BOTFATHER_URL}">@BotFather</a> e mande <code>/newbot</code>.
Escolha um nome (ex.: <i>MU Alertas</i>) e um usuário que termine em <code>bot</code>.</li>
<li>Ele responde com um <b>token</b> (algo como <code>123456789:AA…</code>). Cole abaixo e clique em <b>Verificar</b>.</li>
<li>Abra o link do seu bot (aparece depois de verificar) e toque em <b>Iniciar</b>.</li>
<li>Clique em <b>Buscar conversas</b>, deixe marcado quem recebe e clique em <b>Testar</b>.</li>
</ol>
Outra pessoa quer receber os alertas <i>deste</i> PC? Ela abre o mesmo link do bot, toca em Iniciar e você
busca as conversas de novo. Cada amigo, no PC dele, cria o próprio bot.
"""

COMMANDS_HELP = ("Pedidos pelo celular (botões no bot ou digitando): /status, /print 2, /inventario, /personagem, "
                 "/cacada, /loja, /ok (alerta visto), /pausar 60, /retomar. Os painéis precisam "
                 "estar abertos no jogo: o app só olha a tela, não aperta teclas.")


class _Bridge(QObject):
    done = Signal(object, object)  # (resultado, erro)


def run_async(fn, callback) -> None:
    """Roda fn() numa thread e chama callback(resultado, erro) na thread da GUI."""
    bridge = _Bridge()
    bridge.done.connect(callback, Qt.ConnectionType.QueuedConnection)

    def work():
        try:
            bridge.done.emit(fn(), None)
        except TelegramError as exc:
            bridge.done.emit(None, exc.description)
        except Exception as exc:  # nunca mostra a mensagem crua (pode conter a URL com o token)
            bridge.done.emit(None, f"erro inesperado ({type(exc).__name__})")

    run_async._keep = getattr(run_async, "_keep", []) + [bridge]  # mantém vivo até o sinal chegar
    threading.Thread(target=work, name="telegram-gui", daemon=True).start()


class TelegramPanel(QWidget):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        tg = cfg.notifiers.telegram
        self.bot_username = tg.bot_username
        self.chats = [c.model_copy() for c in tg.chats]
        v = QVBoxLayout(self)
        self.enabled = QCheckBox("Enviar alertas pelo Telegram")
        self.enabled.setChecked(tg.enabled)
        v.addWidget(self.enabled)
        help_lbl = QLabel(HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(help_lbl)

        row = QHBoxLayout()
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        has = secrets.has_secret(TELEGRAM_TOKEN_KEY)
        self.token.setPlaceholderText("token já cadastrado (cole outro para trocar)" if has else "token do @BotFather")
        row.addWidget(QLabel("Token do bot:"))
        row.addWidget(self.token, 1)
        self.verify_btn = QPushButton("Verificar")
        self.verify_btn.clicked.connect(self.verify)
        row.addWidget(self.verify_btn)
        v.addLayout(row)
        self.bot_lbl = QLabel()
        self.bot_lbl.setOpenExternalLinks(True)
        self.bot_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.bot_lbl.setWordWrap(True)
        v.addWidget(self.bot_lbl)
        self._show_bot()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Quem recebe", "ID da conversa", "Recebe"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(110)
        v.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Buscar conversas", self.find), ("Remover", self.remove), ("Testar selecionada", self.test)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.images = QCheckBox("Mandar o print da janela junto nos alertas críticos")
        self.images.setChecked(tg.send_images)
        v.addWidget(self.images)
        self.commands = QCheckBox("Aceitar pedidos pelo Telegram (só das conversas da lista)")
        self.commands.setChecked(tg.commands)
        self.commands.setToolTip(COMMANDS_HELP)
        v.addWidget(self.commands)
        cmd_lbl = QLabel(COMMANDS_HELP)
        cmd_lbl.setWordWrap(True)
        cmd_lbl.setStyleSheet("color:#888;")
        v.addWidget(cmd_lbl)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        self._fill()

    # ------------------------------------------------------------------
    def _show_bot(self) -> None:
        if self.bot_username:
            url = f"https://t.me/{self.bot_username}"
            self.bot_lbl.setText(f"✔ Bot <b>@{self.bot_username}</b> — link para tocar em Iniciar: "
                                 f"<a href='{url}'>{url}</a>")
        elif secrets.has_secret(TELEGRAM_TOKEN_KEY):
            self.bot_lbl.setText("Token cadastrado. Clique em Verificar para ver o link do bot.")
        else:
            self.bot_lbl.setText("")

    def _fill(self) -> None:
        self.table.setRowCount(len(self.chats))
        for i, c in enumerate(self.chats):
            self.table.setItem(i, 0, QTableWidgetItem(c.name or "—"))
            self.table.setItem(i, 1, QTableWidgetItem(str(c.chat_id)))
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setCheckState(Qt.CheckState.Checked if c.enabled else Qt.CheckState.Unchecked)
            self.table.setItem(i, 2, it)

    def _sync_checks(self) -> None:
        for i, c in enumerate(self.chats):
            it = self.table.item(i, 2)
            if it is not None:
                c.enabled = it.checkState() == Qt.CheckState.Checked

    def _current_token(self) -> str | None:
        return self.token.text().strip() or secrets.get_secret(TELEGRAM_TOKEN_KEY)

    def verify(self) -> None:
        token = self._current_token()
        if not token:
            self.msg.setText("Cole o token que o @BotFather mandou.")
            return
        self.verify_btn.setEnabled(False)
        self.msg.setText("Verificando…")

        def done(me, err):
            self.verify_btn.setEnabled(True)
            if err:
                self.msg.setText("✖ " + err)
                return
            try:
                secrets.set_secret(TELEGRAM_TOKEN_KEY, token)
            except Exception as exc:
                self.msg.setText(f"✖ não consegui guardar o token no Gerenciador de Credenciais ({type(exc).__name__})")
                return
            self.token.clear()
            self.token.setPlaceholderText("token já cadastrado (cole outro para trocar)")
            self.bot_username = me.get("username", "")
            self.enabled.setChecked(True)
            self._show_bot()
            self.msg.setText("✔ Token válido e guardado. Agora toque em Iniciar no bot e clique em Buscar conversas.")

        run_async(lambda: TelegramApi(token).get_me(), done)

    def find(self) -> None:
        token = self._current_token()
        if not token:
            self.msg.setText("Cadastre e verifique o token primeiro.")
            return
        self.msg.setText("Buscando…")

        def done(found, err):
            if err:
                self.msg.setText("✖ " + err)
                return
            self._sync_checks()
            known = {c.chat_id for c in self.chats}
            new = [TelegramChat(nome=name, id=cid) for cid, name in found if cid not in known]
            self.chats += new
            self._fill()
            if new:
                self.msg.setText(f"✔ {len(new)} conversa(s) nova(s). Clique em Testar.")
            elif found:
                self.msg.setText("Nenhuma conversa nova (as que tocaram em Iniciar já estão na lista).")
            else:
                self.msg.setText("Ninguém tocou em Iniciar no bot nas últimas 24 h. Abra o link do bot, "
                                 "toque em Iniciar e busque de novo.")

        run_async(lambda: TelegramApi(token).find_chats(), done)

    def _selected(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else (0 if len(self.chats) == 1 else None)

    def remove(self) -> None:
        i = self._selected()
        if i is not None:
            self._sync_checks()
            self.chats.pop(i)
            self._fill()

    def test(self) -> None:
        i = self._selected()
        token = self._current_token()
        if i is None or not token:
            self.msg.setText("Verifique o token e selecione uma conversa na lista.")
            return
        c = self.chats[i]
        self.msg.setText(f"Enviando teste para {c.name or c.chat_id}…")
        run_async(lambda: send_test(token, c.chat_id, TEST_TEXT),
                  lambda res, err: self.msg.setText(("✖ " + err) if err else (("✔ " if res[0] else "✖ ") + res[1])))

    # ------------------------------------------------------------------
    def apply_to(self, cfg: Config) -> None:
        self._sync_checks()
        tg = cfg.notifiers.telegram
        tg.enabled = self.enabled.isChecked()
        tg.bot_username = self.bot_username
        tg.chats = self.chats
        tg.send_images = self.images.isChecked()
        tg.commands = self.commands.isChecked()

    def configured(self) -> bool:
        return secrets.has_secret(TELEGRAM_TOKEN_KEY) and any(c.enabled for c in self.chats)
