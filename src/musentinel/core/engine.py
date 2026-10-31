"""Motor do monitor: 1 thread que percorre todos os slots a cada ciclo (padrão 2 s).

Para cada slot: saúde (processo, janela, conexão), captura, leitura do HUD,
máquina de estados → sinais → alertas. Publica um retrato de cada slot para a GUI.
O core não importa Qt.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import health, paths, power, winapi
from .alerts import Alert, AlertManager
from .capture import CaptureError, WindowGoneError, WindowMinimizedError, make_backend
from .config import Config
from .discovery import Discovery, default_store
from .events import EventBus
from .notifiers import CallMeBotNotifier
from .notifiers.telegram import TelegramCommandListener, TelegramNotifier
from .panels import PanelEvent, PanelService
from .perception import autocal
from .perception import panels as P
from .perception.autocal import hunting_time_roi
from .perception.reader import DEFAULT_FIELDS
from .remote import BOT_COMMANDS, HELP, KEYBOARD, TARGETS_FILE, RemoteCommands, parse
from .state_machine import CRITICAL, Observation, SlotTracker, State

log = logging.getLogger(__name__)
THUMB_W = 320
AUTOCAL_BAD_CYCLES = 15  # HP/EXP ilegível por ~30 s seguidos → calibra a janela sozinho
AUTOCAL_EVERY_S = 600  # no máximo 1 calibração automática a cada 10 min por janela
SHOP_COUNTS_FILE = "loja_contagem.json"  # última contagem do Gremory Case de cada janela
PROTECTION_TITLE = "MONITORAMENTO LIMITADO PELO ANTI-CHEAT"
PROTECTION_NOTE = ("o anti-cheat do jogo (GameGuard) não deixa o MU Sentinel ver de qual processo são as "
                   "janelas do MU; o app segue pela imagem da janela, mas sem checar a conexão com o servidor "
                   "(queda da internet deste PC continua sendo detectada)")


@dataclass
class SlotSnapshot:
    slot: int
    name: str
    state: State
    since: float
    alive: bool
    pid: int | None
    size: tuple[int, int] | None
    hp: tuple[int, int] | None = None
    exp: tuple[int, int] | None = None
    coords: tuple[int, int] | None = None
    map: str | None = None
    exp_per_h: float | None = None
    exp_pct_per_h: float | None = None
    hunting_time: int | None = None
    note: str = ""
    last_event: str = ""
    level_cap: int = 0
    connected: bool | None = None
    shop: bool = False
    panels: list[str] = field(default_factory=list)  # painéis vistos abertos (ver perception.panels.KINDS)
    shop_status: tuple[int, int, float | None] | None = None  # Gremory Case: (itens, capacidade, última venda)
    thumb: np.ndarray | None = field(default=None, repr=False)


class _Slot:
    def __init__(self, n: int, cfg: Config) -> None:
        self.n = n
        self.tracker = SlotTracker(n, cfg)
        self.conn = health.ConnectionTracker()
        self.pid: int | None = None
        self.hwnd: int | None = None
        self.size: tuple[int, int] | None = None
        self.frame: np.ndarray | None = None
        self.thumb: np.ndarray | None = None
        self.last_event = ""
        self.critical_sent = False
        self.connected: bool | None = None
        self.hud_bad = 0  # ciclos seguidos com HP/EXP ilegível
        self.autocal_due = False
        self.autocal_at = 0.0


class Engine:
    def __init__(self, config: Config, bus: EventBus, local_notifiers: list | None = None) -> None:
        self.cfg = config
        self.bus = bus
        self.local_notifiers = list(local_notifiers or [])
        self.callmebot: CallMeBotNotifier | None = None
        self.telegram: TelegramNotifier | None = None
        self.listener: TelegramCommandListener | None = None
        self.alerts = AlertManager(config, [], level=lambda: self.cfg.level, on_sent=self._on_sent)
        self.panels = PanelService(store=paths.data_dir() / SHOP_COUNTS_FILE)
        self.remote = RemoteCommands(self, store=paths.data_dir() / TARGETS_FILE)
        self._panels_thread: threading.Thread | None = None
        self._build_notifiers()
        self.discovery = Discovery(config.monitor.window_title, config.monitor.process_name, store=default_store())
        self.internet = health.InternetProbe()
        self.slots: dict[int, _Slot] = {}
        self._readers: dict[tuple[int, int], object | None] = {}
        self._ocr = None
        self._capture = None
        self._lock = threading.RLock()
        self._cal_lock = threading.Lock()  # uma calibração por vez
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.time()
        self.last_cycle = 0.0
        self.cycle_ms = 0.0
        self.cycle_ms_max = 0.0  # ciclo mais lento depois do aquecimento
        self._cycles = 0
        self.outage_active = False
        self.power_warnings: list[str] = []
        self.elevated_game = False
        self._awake: tuple[bool, bool] | None = None
        self._read_errors: set[tuple[str, str]] = set()
        self._errors_alerted: set[str] = set()
        self.protection_blocked = 0  # janelas do jogo escondidas pelo anti-cheat

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        self.power_warnings = power.power_warnings()
        self.internet.start()
        self._thread = threading.Thread(target=self._run, name="monitor", daemon=True)
        self._thread.start()
        self._panels_thread = threading.Thread(target=self._panels_run, name="paineis", daemon=True)
        self._panels_thread.start()
        self.bus.emit("info", "monitor iniciado (nível 0 · Observador)")

    def stop(self) -> None:
        self._stop.set()
        self.internet.stop()
        if self._thread:
            self._thread.join(timeout=10)
        if self.listener:
            self.listener.close()
        for n in self._all_notifiers():
            try:
                n.close()
            except Exception:
                pass
        self.bus.emit("info", "monitor parado")

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive()) and time.time() - self.last_cycle < 30

    def _run(self) -> None:
        winapi.enable_dpi_awareness()
        self._capture = make_backend("auto")
        try:
            while not self._stop.is_set():
                t0 = time.time()
                try:
                    self.cycle()
                except Exception as exc:  # o monitor nunca morre por um erro de ciclo
                    log.exception("erro no ciclo do monitor")
                    what = f"{type(exc).__name__}: {exc}"[:160]
                    self.bus.emit("erro", f"erro interno no monitor: {what}", severity="aviso")
                    if what not in self._errors_alerted:  # cada erro diferente vai ao celular 1 vez só
                        self._errors_alerted.add(what)
                        self.alerts.submit(Alert(None, "ERRO", "aviso", "ERRO INTERNO",
                                                 detail=f"{type(exc).__name__} (detalhes no log; o monitor "
                                                        "continua e não avisa de novo este mesmo erro)"))
                        self.alerts.flush()
                self.last_cycle = time.time()
                self.cycle_ms = (self.last_cycle - t0) * 1000
                self._cycles += 1
                if self._cycles > 3:  # os primeiros carregam o OCR
                    self.cycle_ms_max = max(self.cycle_ms_max, self.cycle_ms)
                self._stop.wait(max(0.05, self.cfg.monitor.interval_s - (time.time() - t0)))
        finally:
            power.release_awake()
            if self._capture:
                self._capture.close()

    # ------------------------------------------------------------------ painéis (thread própria)
    PANEL_LIVE = (State.ONLINE, State.CACANDO, State.PARADO)
    PANEL_FIRST_S = 15.0  # primeira checagem de painéis depois de achar a janela
    PANEL_STAGGER_S = 5.0  # e um slot de cada vez

    def _panels_run(self) -> None:
        next_due: dict[int, float] = {}
        while not self._stop.wait(2.0):
            try:
                self.panels_tick(next_due)
            except Exception:
                log.exception("erro na checagem dos painéis")

    def _want_autocal(self, s: _Slot, now: float) -> None:
        if now - s.autocal_at >= AUTOCAL_EVERY_S:
            s.autocal_due = True

    def calibrate_slot(self, n: int, auto: bool = False) -> autocal.CalResult | None:
        """Calibra o perfil do tamanho desta janela com o OCR completo da tela (leva alguns segundos).

        Roda fora da thread do monitor (thread dos painéis ou da tela). None = sem imagem da janela.
        """
        img = self.frame_copy(n)
        if img is None:
            return None
        h, w = img.shape[:2]
        with self._cal_lock:
            existed = paths.has_profile(w, h)
            prof = paths.load_or_default_profile(w, h)
            hits, boxes = P.scan(img, self.panels.ocr)
            self.panels.adopt(n, hits)
            prof, res = autocal.calibrate(img, self.panels.ocr, prof, boxes=boxes, caca=hits.get("caca"))
            res.created = res.created or not existed
            if res.created or res.learned or res.moved:
                prof.notes = (prof.notes + "\n" if prof.notes else "") + \
                    f"calibração {'automática' if auto else 'pedida'} {datetime.now():%Y-%m-%d %H:%M} (slot {n})"
                prof.save(paths.profile_path(w, h))
                self.reload_profiles()
        with self._lock:
            s = self.slots.get(n)
            if s:
                s.hud_bad = 0
                s.autocal_at = time.time()
        self.bus.emit("info", f"calibração {'automática' if auto else ''} da janela: "
                      + (res.summary().replace("\n", " · ") or "nada lido"), slot=n)
        return res

    def _run_due_autocal(self) -> None:
        with self._lock:
            due = [n for n, s in self.slots.items() if s.autocal_due]
            for n in due:
                self.slots[n].autocal_due = False
                self.slots[n].autocal_at = time.time()
        for n in due:
            try:
                self.calibrate_slot(n, auto=True)
            except Exception:
                log.exception("calibração automática do slot %s falhou", n)

    def panels_tick(self, next_due: dict[int, float], now: float | None = None) -> None:
        self._run_due_autocal()
        cfg = self.cfg
        if not cfg.panels.enabled:
            return
        now = time.time() if now is None else now
        with self._lock:
            due = []
            for n, s in self.slots.items():
                if n not in next_due:  # slot novo: começa depois de o monitor assentar, um slot por vez
                    next_due[n] = now + self.PANEL_FIRST_S + self.PANEL_STAGGER_S * len(next_due)
                if s.frame is None or now < next_due[n]:
                    continue
                shop = cfg.is_shop(n)
                gremory = shop or "loja" in self.panels.open_panels(n)  # vendas: checa mais vezes
                next_due[n] = now + (cfg.panels.shop_interval_s if gremory else cfg.panels.interval_s)
                due.append((n, s.frame.copy(), s.tracker.view.state in self.PANEL_LIVE, shop, cfg.slot_name(n)))
        if not due:
            return
        user_active = health.user_idle_s() < cfg.thresholds.city_grace_s
        for n, img, live, shop, name in due:
            for ev in self.panels.check(n, img, live=live, user_active=user_active, is_shop=shop, shop_key=name):
                self._panel_event(n, ev)

    def _panel_event(self, n: int, ev: PanelEvent) -> None:
        with self._lock:
            s = self.slots.get(n)
            header = self._header(s) if s else f"Slot {n}"
        if ev.kind == "reabriu":
            self.bus.emit("info", ev.detail, slot=n)
            return
        if ev.kind == "fechou":
            if not self.cfg.panels.warn_closed:
                self.bus.emit("info", ev.detail, slot=n)
                return
            title, key = "PAINEL FECHADO", f"PAINEL_{ev.panel}"
        elif ev.kind == "venda":
            title, key = "VENDA NA LOJA", f"VENDA_{time.time():.0f}"
        else:  # "aba"
            title, key = "GREMORY CASE NA ABA ERRADA", "LOJA_ABA"
        self.bus.emit("alerta", f"{title}: {ev.detail}", slot=n, severity="aviso", kind_code=key)
        self.alerts.submit(Alert(n, key, "aviso", title, header, ev.detail, image=ev.image))
        if s:
            s.last_event = f"{time.strftime('%H:%M')} {title}"

    def frame_copy(self, slot: int) -> np.ndarray | None:
        with self._lock:
            s = self.slots.get(slot)
            return None if s is None or s.frame is None else s.frame.copy()

    def _on_remote(self, text: str, chat_id: int = 0) -> list[tuple]:
        cmd = parse(text)
        if cmd is None:
            return [("Não entendi esse pedido.\n\n" + HELP, None)]
        self.bus.emit("info", f"pedido pelo Telegram: {cmd.name}" + (f" {cmd.slot}" if cmd.slot else ""))
        return [(r.text, r.image, r.buttons) for r in self.remote.handle(cmd, chat_id)]

    def _on_button(self, data: str, chat_id: int) -> tuple[str, tuple | None]:
        toast, reply = self.remote.on_button(data, chat_id)
        if toast:
            self.bus.emit("info", f"Telegram: pedidos agora respondem de {self.remote.target_name(chat_id)}")
        return toast, (reply.text, reply.buttons) if reply else None

    # ------------------------------------------------------------------ um ciclo
    def cycle(self) -> None:
        with self._lock:
            cfg = self.cfg
            now = time.time()
            awake = (cfg.monitor.keep_awake, cfg.monitor.keep_display_on)
            if awake != self._awake:  # vale para esta thread (a do monitor)
                power.keep_awake(*awake)
                self._awake = awake
            bindings = self.discovery.refresh()
            for msg in self.discovery.events:
                self.bus.emit("info", msg, severity="aviso")
            self._check_protection(self.discovery.hidden)
            conns = health.tcp_by_pid()
            user_active = health.user_idle_s() < cfg.thresholds.city_grace_s
            internet_down = self.internet.ok is False

            disconnected_now: list[tuple[_Slot, object]] = []
            pending: list[tuple[_Slot, object]] = []
            for n in sorted(set(bindings) | set(self.slots)):
                b = bindings.get(n)
                s = self.slots.get(n)
                if s is None:
                    if b is None:
                        continue  # slot lembrado de outra execução, sem janela: ignora
                    s = self.slots[n] = _Slot(n, cfg)
                    cfg.slot(n)
                    self.bus.emit("info", f"janela encontrada (PID {b.pid})", slot=n)
                obs = self._observe(s, b, now, conns, user_active, internet_down)
                before = s.tracker.view.state
                signals = s.tracker.update(obs)
                after = s.tracker.view.state
                if after != before:
                    s.last_event = f"{time.strftime('%H:%M')} {before.value} → {after.value}"
                    self.bus.emit("estado", f"{before.value} → {after.value}", slot=n,
                                  severity="critico" if after in CRITICAL else "info",
                                  state=after.value, previous=before.value)
                for sig in signals:
                    if sig.kind == "DESCONECTADO":
                        disconnected_now.append((s, sig))
                    else:
                        pending.append((s, sig))

            self._handle_disconnects(disconnected_now, internet_down)
            for s, sig in pending:
                self._handle_signal(s, sig)
            if self.outage_active and not any(
                    x.tracker.view.state == State.DESCONECTADO for x in self.slots.values()) and not internet_down:
                self.outage_active = False
                self.alerts.resolve(None, {"QUEDA_GERAL"})
                self.alerts.submit(Alert(None, "QUEDA_GERAL_OK", "info", "CONEXÃO VOLTOU",
                                         detail="nenhum slot desconectado agora"))
            self.alerts.flush()
            self.bus.publish("snapshots", self.snapshots())

    def _observe(self, s: _Slot, b, now, conns, user_active, internet_down) -> Observation:
        if b is None:
            if s.pid == 0:
                # dono desconhecido: só dá para saber se a janela ainda existe
                if s.hwnd and winapi.is_window(s.hwnd):
                    return Observation(ts=now, capture_ok=False, connected=s.connected,
                                       note="a janela do jogo existe, mas não está acessível agora")
                return Observation(ts=now, process_alive=False, capture_ok=False, note="a janela do jogo fechou")
            if s.pid and health.process_alive(s.pid, self.cfg.monitor.process_name or None):
                return Observation(ts=now, capture_ok=False, connected=s.connected,
                                   note="janela do jogo sumiu, mas o processo continua aberto")
            return Observation(ts=now, process_alive=False, capture_ok=False, note="janela fechada")
        if s.hwnd == b.hwnd and s.pid != b.pid and 0 in (s.pid, b.pid):
            # mesma janela; o anti-cheat passou a esconder (ou mostrar) o processo dono
            s.pid = b.pid
            s.conn.reset()
        elif s.pid != b.pid or s.hwnd != b.hwnd:
            if s.pid is not None:
                self.bus.emit("info", "client reaberto" + (f" (PID {s.pid} → {b.pid})" if s.pid and b.pid else ""),
                              slot=s.n)
            s.tracker.reset_process()
            s.conn.reset()
            s.pid, s.hwnd = b.pid, b.hwnd
        if b.info is not None and b.info.elevated and not winapi.current_process_elevated():
            self.elevated_game = True
        if b.pid:
            alive = health.process_alive(b.pid, self.cfg.monitor.process_name or None)
        else:
            alive = winapi.is_window(b.hwnd)  # modo limitado: a janela existir é o que dá para checar
        hung = health.window_hung(b.hwnd) if alive else False
        o = Observation(ts=now, process_alive=alive, hung=hung, user_active=user_active)
        try:
            frame = self._capture.grab(b.hwnd)
        except WindowMinimizedError:
            o.capture_ok, o.note = False, "janela minimizada (minimizada não renderiza)"
            frame = None
        except WindowGoneError:
            o.capture_ok, o.note = False, "janela sumiu"
            frame = None
        except CaptureError as exc:
            o.capture_ok, o.note = False, f"captura falhou: {exc}"
            frame = None
        if frame is not None:
            img = frame.image
            s.frame = img
            s.size = frame.size
            h, w = img.shape[:2]
            s.thumb = cv2.resize(img, (THUMB_W, int(h * THUMB_W / w)), interpolation=cv2.INTER_AREA)
            reader = self._reader_for(frame.size)
            if reader is None:
                o.note = f"sem perfil para {w}x{h}: calibrando automaticamente"
                self._want_autocal(s, now)
            else:
                ht_hit = self.panels.hit(s.n, "caca")  # janela de caça desta janela, onde quer que esteja
                fields = DEFAULT_FIELDS if ht_hit is None else tuple(f for f in DEFAULT_FIELDS if f != "hunting_time")
                r = reader.read(img, fields)
                for fname, fr in r.fields.items():
                    if fr.raw.startswith("erro:") and (fname, fr.raw) not in self._read_errors:
                        self._read_errors.add((fname, fr.raw))  # registra cada erro diferente uma vez
                        log.error("falha ao ler %s (slot %s): %s", fname, s.n, fr.raw)
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("slot %s leitura: %s", s.n, {k: (v.status, v.raw[:24], round(v.confidence, 2))
                                                           for k, v in r.fields.items()})
                o.hp = r.value("hp")
                o.exp = r.value("exp")
                o.coords = r.value("coords")
                o.map = r.value("map")
                if ht_hit is not None:
                    fr = reader.read_field_at(img, "hunting_time", hunting_time_roi(ht_hit, frame.size))
                    o.hunting_time = fr.value if fr.ok else None
                else:
                    o.hunting_time = r.value("hunting_time")
                if o.hp is None and o.exp is None:
                    o.note = "HUD ilegível (menu, loading ou janela por cima)"
                bad = any(r.fields[f].status == "unreadable" for f in ("hp", "exp") if f in r.fields)
                s.hud_bad = s.hud_bad + 1 if bad else 0
                if s.hud_bad >= AUTOCAL_BAD_CYCLES:
                    self._want_autocal(s, now)
        if o.note != getattr(s, "_last_note", ""):
            s._last_note = o.note
            if o.note:
                log.info("slot %s: %s", s.n, o.note)
        online_evidence = o.hp is not None and o.hp[0] > 0
        connected = s.conn.update(conns.get(b.pid, set()), online_evidence) if b.pid else None
        if internet_down and (s.conn.reference or not b.pid):
            connected = False
        o.connected = connected
        s.connected = connected
        return o

    def _reader_for(self, size: tuple[int, int]):
        if size in self._readers:
            return self._readers[size]
        from .perception.reader import HudReader

        w, h = size
        reader = None
        if paths.has_profile(w, h):
            from .perception.ocr import OcrEngine

            if self._ocr is None:
                self._ocr = OcrEngine()
            prof = paths.load_or_default_profile(w, h)
            log.info("perfil %dx%d carregado (%s); dígitos que faltam: %s", w, h,
                     "do usuário" if paths.profile_path(w, h).exists() else
                     "semente" if paths.seed_profile_path(w, h).exists() else "de fábrica",
                     {f: "".join(sorted(prof.missing_chars(f))) for f in ("hp", "coords", "exp", "hunting_time")})
            reader = HudReader(prof, ocr=self._ocr)
        self._readers[size] = reader
        return reader

    def reload_profiles(self) -> None:
        with self._lock:
            self._readers.clear()

    def _check_protection(self, hidden: int) -> None:
        if hidden and not self.protection_blocked:
            self.bus.emit("alerta", f"{PROTECTION_TITLE}: {hidden} janela(s) sem processo visível", severity="aviso")
            self.alerts.submit(Alert(None, "BLOQUEIO_ANTICHEAT", "aviso", PROTECTION_TITLE,
                                     detail=f"{hidden} janela(s) · {PROTECTION_NOTE}"))
        elif not hidden and self.protection_blocked:
            self.bus.emit("info", "o anti-cheat voltou a deixar o MU Sentinel ver os processos do jogo")
        self.protection_blocked = hidden

    # ------------------------------------------------------------------ sinais → alertas
    def _header(self, s: _Slot) -> str:
        v = s.tracker.view
        where = ""
        m = v.map if s.tracker.view.state != State.MORTO else (v.last_hunting_map or v.map)
        if m:
            where = f" ({m}" + (f" {v.coords[0]},{v.coords[1]}" if v.coords else "") + ")"
        return f'Slot {s.n} "{self.cfg.slot_name(s.n)}"{where}'

    def _handle_signal(self, s: _Slot, sig) -> None:
        self.bus.emit("alerta" if sig.severity != "info" else "estado", f"{sig.title}: {sig.detail}",
                      slot=s.n, severity=sig.severity, kind_code=sig.kind)
        s.last_event = f"{time.strftime('%H:%M')} {sig.title}"
        if sig.kind == "RESOLVIDO":
            self.alerts.resolve(s.n)
            if not s.critical_sent:
                return
            s.critical_sent = False
        image = self._jpeg(s) if sig.severity == "critico" else None
        ok = self.alerts.submit(Alert(s.n, sig.kind, sig.severity, sig.title, self._header(s), sig.detail,
                                      image=image))
        if ok and sig.severity == "critico":
            s.critical_sent = True

    def _handle_disconnects(self, items, internet_down: bool) -> None:
        if not items:
            return
        if len(items) >= 2 or internet_down:
            for s, sig in items:
                self.bus.emit("alerta", f"{sig.title}: {sig.detail}", slot=s.n, severity="critico")
                s.critical_sent = True
            inet = internet_down or not health.internet_ok()
            names = ", ".join(f"{s.n} \"{self.cfg.slot_name(s.n)}\"" for s, _ in items)
            total = len(self.slots)
            title = "TODOS OS SLOTS CAÍRAM" if len(items) >= total else f"{len(items)} SLOTS CAÍRAM"
            cause = "internet deste PC fora do ar" if inet else "internet ok: provável queda do servidor"
            self.outage_active = True
            self.alerts.submit(Alert(None, "QUEDA_GERAL", "critico", title, f"slots {names}", cause))
            return
        s, sig = items[0]
        self._handle_signal(s, sig)

    @staticmethod
    def _jpeg(s: _Slot) -> bytes | None:
        if s.frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", s.frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    def _on_sent(self, how: str, a: Alert) -> None:
        if how == "silencioso":
            log.info("horário silencioso: %s não saiu nos canais externos", a.title)

    # ------------------------------------------------------------------ notificadores
    def _all_notifiers(self) -> list:
        return self.local_notifiers + [n for n in (self.callmebot, self.telegram) if n]

    def _build_notifiers(self) -> None:
        for n in (self.callmebot, self.telegram, self.listener):
            if n:
                n.close()
        self.callmebot = self.telegram = self.listener = None
        cm = self.cfg.notifiers.callmebot
        if cm.enabled and any(r.enabled for r in cm.recipients):
            self.callmebot = CallMeBotNotifier(cm.recipients, cm.min_interval_s)
        tg = self.cfg.notifiers.telegram
        if tg.enabled and any(c.enabled for c in tg.chats):
            self.telegram = TelegramNotifier(tg.chats, tg.min_interval_s, tg.send_images)
        if tg.enabled and tg.commands and tg.chats:
            # pedidos pelo celular: só das conversas cadastradas no app
            self.listener = TelegramCommandListener({c.chat_id for c in tg.chats}, self._on_remote,
                                                    KEYBOARD, BOT_COMMANDS, on_button=self._on_button)
            if self.telegram:
                self.telegram.supports_inbound = True  # dá para responder /ok (para os lembretes, se ligados)
        local = self.local_notifiers if self.cfg.notifiers.windows.enabled else []
        self.alerts.set_notifiers(local + [n for n in (self.callmebot, self.telegram) if n])

    def notifier_status(self) -> list[tuple[str, bool, str]]:
        out = []
        if self.cfg.notifiers.windows.enabled:
            for n in self.local_notifiers:
                st = n.status()
                out.append((n.name, st.ok, st.detail))
        tg = self.cfg.notifiers.telegram
        if self.telegram:
            st = self.telegram.status()
            out.append((self.telegram.name, st.ok, st.detail))
            if self.listener and not self.listener.status.ok:
                out.append(("Telegram (pedidos)", False, self.listener.status.detail))
        elif tg.enabled:
            out.append(("Telegram", False, "nenhuma conversa marcada"))
        cm = self.cfg.notifiers.callmebot
        if self.callmebot:
            st = self.callmebot.status()
            out.append((self.callmebot.name, st.ok, st.detail))
        elif cm.enabled:
            out.append(("WhatsApp (CallMeBot)", False, "nenhum número ativo"))
        elif not tg.enabled:
            out.append(("Celular", False, "nenhum canal configurado"))
        return out

    def apply_config(self, cfg: Config) -> None:
        with self._lock:
            old = self.cfg
            self.cfg = cfg
            self.alerts.cfg = cfg
            for s in self.slots.values():
                s.tracker.cfg = cfg
            self.discovery.title = cfg.monitor.window_title
            self.discovery.process = cfg.monitor.process_name
            if old.notifiers.model_dump() != cfg.notifiers.model_dump() or (self.callmebot is None
                                                                           and self.telegram is None):
                self._build_notifiers()
        self.bus.emit("info", "configuração aplicada")

    def rebuild_notifiers(self) -> None:
        """Depois de trocar uma chave no keyring."""
        with self._lock:
            self._build_notifiers()

    # ------------------------------------------------------------------ comandos da GUI
    def snapshots(self) -> list[SlotSnapshot]:
        out = []
        with self._lock:
            for n, s in sorted(self.slots.items()):
                v = s.tracker.view
                out.append(SlotSnapshot(
                    slot=n, name=self.cfg.slot_name(n), state=v.state, since=v.since,
                    alive=v.state != State.FECHADO, pid=s.pid, size=s.size, hp=v.hp, exp=v.exp,
                    coords=v.coords, map=v.map, exp_per_h=v.exp_per_h, exp_pct_per_h=v.exp_pct_per_h,
                    hunting_time=v.hunting_time, note=v.note, last_event=s.last_event,
                    level_cap=self.cfg.slot(n).level_cap, connected=s.connected,
                    shop=self.cfg.is_shop(n), panels=self.panels.open_panels(n),
                    shop_status=self.panels.shop_status(n),
                    thumb=None if s.thumb is None else s.thumb.copy()))
        return out

    def save_print(self, slot: int) -> Path | None:
        with self._lock:
            s = self.slots.get(slot)
            img = None if s is None or s.frame is None else s.frame.copy()
        if img is None:
            return None
        d = paths.captures_dir() / "prints"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"slot{slot}_{datetime.now():%Y%m%d_%H%M%S}.png"
        cv2.imencode(".png", img)[1].tofile(str(p))
        self.bus.emit("info", f"print salvo em {p.name}", slot=slot)
        return p

    def forget_slot(self, slot: int) -> None:
        with self._lock:
            self.slots.pop(slot, None)
            self.discovery.forget(slot)
            self.alerts.resolve(slot)
        self.panels.forget(slot)

    def ack(self, slot: int | None = None) -> int:
        n = self.alerts.ack(slot)
        if n:
            self.bus.emit("info", f"{n} alerta(s) reconhecido(s)", slot=slot)
        return n

    def pause_alerts(self, minutes: float | None) -> None:
        self.alerts.pause(minutes)
        self.bus.emit("info", "alertas pausados" + (f" por {minutes:g} min" if minutes else " até retomar"))

    def resume_alerts(self) -> None:
        self.alerts.resume()
        self.bus.emit("info", "alertas retomados")

    def send_test(self) -> None:
        self.alerts.submit(Alert(None, f"TESTE_{time.time()}", "info", "TESTE",
                                 detail="mensagem de teste do MU Sentinel"))
        self.alerts.flush()
