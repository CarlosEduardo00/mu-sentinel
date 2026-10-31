"""Configuração do app: Pydantic + YAML, com versão de schema e migração.

As chaves do YAML ficam em português (é o arquivo que o usuário edita);
os atributos no código ficam em inglês (via alias).
Segredos (chave do CallMeBot etc.) NUNCA ficam aqui: vão para o keyring (ver secrets.py).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import paths

SCHEMA_VERSION = 1
RISK_TEXT = ("A política operacional da Webzen proíbe macros e programas não oficiais e prevê banimento "
             "permanente, inclusive de todas as contas ligadas à mesma pessoa. Os níveis 1 a 4 enviam teclas "
             "ao jogo. Use por sua conta e risco.")
LEVEL_NAMES = ["Observador", "Assistido", "Reativo", "Rotinas", "Recuperação"]
DEFAULT_CITIES = ["Lorencia", "Devias", "Noria", "Elbeland"]


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", validate_assignment=True)


def normalize_phone(phone: str) -> str:
    """'+55 (11) 99999-9999' → '5511999999999' (só dígitos, com DDI)."""
    return re.sub(r"\D", "", phone or "")


SHOP_WORD = "loja"


def is_shop_name(name: str) -> bool:
    """'Loja', 'loja 2', 'Loja do Elf' → True."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.search(rf"\b{SHOP_WORD}\b", plain) is not None


def mask_phone(phone: str) -> str:
    """Telefone mascarado para log/tela: '+55•••••••9999'."""
    d = normalize_phone(phone)
    if len(d) <= 4:
        return "•" * len(d)
    return f"+{d[:2]}{'•' * (len(d) - 6)}{d[-4:]}"


class WhatsAppRecipient(_Model):
    """Um número de WhatsApp que recebe os alertas (cada um com a própria chave do CallMeBot)."""

    name: str = Field("", alias="nome")
    phone: str = Field(..., alias="telefone")
    enabled: bool = Field(True, alias="ativo")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        d = normalize_phone(v)
        if not 10 <= len(d) <= 15:
            raise ValueError("telefone deve ter DDI + DDD + número (10 a 15 dígitos)")
        return d

    @property
    def secret_key(self) -> str:
        return f"callmebot:{self.phone}"


class CallMeBotConfig(_Model):
    enabled: bool = Field(False, alias="ativo")
    recipients: list[WhatsAppRecipient] = Field(default_factory=list, alias="destinatarios")
    min_interval_s: float = Field(5.0, alias="intervalo_min_s", ge=1)


class TelegramChat(_Model):
    """Uma conversa do Telegram que recebe os alertas (quem tocou em Iniciar no bot)."""

    name: str = Field("", alias="nome")
    chat_id: int = Field(..., alias="id")
    enabled: bool = Field(True, alias="ativo")


TELEGRAM_TOKEN_KEY = "telegram:token"


class TelegramConfig(_Model):
    """Bot do Telegram. O token fica no Gerenciador de Credenciais (chave TELEGRAM_TOKEN_KEY)."""

    enabled: bool = Field(False, alias="ativo")
    bot_username: str = Field("", alias="bot")
    chats: list[TelegramChat] = Field(default_factory=list, alias="conversas")
    min_interval_s: float = Field(1.0, alias="intervalo_min_s", ge=0.5)
    send_images: bool = Field(True, alias="enviar_print")
    # pedidos pelo Telegram (/status, /inventario, /ok...), só das conversas da lista
    commands: bool = Field(True, alias="aceitar_comandos")


class PanelsConfig(_Model):
    """Painéis que o usuário deixa abertos no jogo (C, I, Instant Hunting Log, Gremory Case na Loja)."""

    enabled: bool = Field(True, alias="acompanhar")
    warn_closed: bool = Field(True, alias="avisar_quando_fechar")
    interval_s: float = Field(30, alias="intervalo_s", ge=10, le=600)
    shop_interval_s: float = Field(10, alias="intervalo_loja_s", ge=5, le=120)


class WindowsNotifyConfig(_Model):
    enabled: bool = Field(True, alias="ativo")


class NotifiersConfig(_Model):
    callmebot: CallMeBotConfig = Field(default_factory=CallMeBotConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    windows: WindowsNotifyConfig = Field(default_factory=WindowsNotifyConfig)


class QuietHours(_Model):
    enabled: bool = Field(False, alias="ativo")
    start: str = Field("23:00", alias="inicio")
    end: str = Field("07:00", alias="fim")
    allow_critical: bool = Field(True, alias="deixar_criticos")

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("use o formato HH:MM")
        return v


class AlertsConfig(_Model):
    # lembrete do alerta crítico enquanto o problema continua (desligado: 1 mensagem por acontecimento)
    repeat_critical: bool = Field(False, alias="lembrete_critico")
    critical_repeat_min: float = Field(5, alias="repetir_critico_min", ge=1)
    max_repeats_no_reply: int = Field(3, alias="max_repeticoes_sem_resposta", ge=0)
    cooldown_min: float = Field(5, alias="intervalo_mesmo_alerta_min", ge=0)
    quiet: QuietHours = Field(default_factory=QuietHours, alias="horario_silencioso")


class MonitorConfig(_Model):
    interval_s: float = Field(2.0, alias="ciclo_s", ge=0.5, le=30)
    confirm_cycles: int = Field(2, alias="ciclos_confirmacao", ge=1, le=10)
    window_title: str = Field("MU", alias="titulo_janela")
    process_name: str = Field("main.exe", alias="processo")
    keep_awake: bool = Field(True, alias="manter_pc_acordado")
    keep_display_on: bool = Field(False, alias="manter_tela_ligada")


class Thresholds(_Model):
    hp_low_pct: float = Field(30, alias="hp_baixo_pct", ge=0, le=100)
    death_hp_reads: int = Field(2, alias="leituras_hp_zero", ge=1)
    exp_stall_min: float = Field(5, alias="exp_parada_min", gt=0)
    helper_stall_s: float = Field(30, alias="hunting_time_parado_s", gt=0)
    hung_s: float = Field(10, alias="janela_sem_responder_s", gt=0)
    frozen_s: float = Field(30, alias="quadro_congelado_s", gt=0)
    unreadable_warn_min: float = Field(2, alias="ilegivel_aviso_min", gt=0)
    city_grace_s: float = Field(60, alias="cidade_sem_comando_s", ge=0)


class SlotConfig(_Model):
    name: str = Field("", alias="nome")
    level_cap: int = Field(0, alias="teto_nivel", ge=0, le=4)


class Config(_Model):
    schema_version: int = Field(SCHEMA_VERSION, alias="versao")
    wizard_done: bool = Field(False, alias="assistente_concluido")
    last_seen_version: str = Field("", alias="novidades_vistas_ate")  # mostra as novidades uma vez por versão
    level: int = Field(0, alias="nivel", ge=0, le=4)
    cities: list[str] = Field(default_factory=lambda: list(DEFAULT_CITIES), alias="cidades")
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds, alias="limiares")
    alerts: AlertsConfig = Field(default_factory=AlertsConfig, alias="alertas")
    notifiers: NotifiersConfig = Field(default_factory=NotifiersConfig, alias="notificadores")
    panels: PanelsConfig = Field(default_factory=PanelsConfig, alias="paineis")
    slots: dict[int, SlotConfig] = Field(default_factory=dict)

    def slot(self, n: int) -> SlotConfig:
        if n not in self.slots:
            self.slots = {**self.slots, n: SlotConfig(name=f"Slot {n}")}
        return self.slots[n]

    def slot_name(self, n: int) -> str:
        s = self.slots.get(n)
        return (s.name if s and s.name else f"Slot {n}")

    def is_city(self, map_name: str | None) -> bool:
        return bool(map_name) and map_name.strip().lower() in {c.lower() for c in self.cities}

    def is_shop(self, n: int) -> bool:
        """Slot do personagem que vende: o nome tem "Loja" (acompanha o Gremory Case, sem alertas de caça)."""
        s = self.slots.get(n)
        return bool(s and is_shop_name(s.name))

    # ------------------------------------------------------------------
    def to_yaml(self) -> str:
        data = self.model_dump(by_alias=True, mode="json")
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            "# Configuração do MU Sentinel. Segredos NÃO ficam aqui (estão no Gerenciador de Credenciais do Windows).\n"
            + self.to_yaml(),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    @classmethod
    def from_yaml(cls, text: str) -> Config:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("config.yaml inválido: esperado um mapa no topo")
        return cls.model_validate(migrate(data))

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        if not path.exists():
            return cls()
        return cls.from_yaml(path.read_text(encoding="utf-8"))


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Atualiza configs de versões antigas. Versão mais nova que o app: erro claro."""
    v = int(data.get("versao", data.get("schema_version", 1)) or 1)
    if v > SCHEMA_VERSION:
        raise ValueError(
            f"config.yaml é da versão {v}, mas este app entende até a {SCHEMA_VERSION}. Atualize o app."
        )
    # (sem migrações ainda: versão 1 é a primeira)
    data["versao"] = SCHEMA_VERSION
    return data


def config_path() -> Path:
    return paths.data_dir() / "config.yaml"
