"""Painéis do jogo (C, I, Instant Hunting Log, Gremory Case) em prints reais 800x600,
o acompanhamento (painel fechado, venda na loja) e os pedidos pelo celular."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from musentinel.core import panels as panels_mod
from musentinel.core.config import Config, is_shop_name
from musentinel.core.panels import PanelEvent, PanelService
from musentinel.core.perception import panels as P
from musentinel.core.perception.ocr import OcrEngine
from musentinel.core.remote import RemoteCommands, parse
from musentinel.core.state_machine import Observation, SlotTracker, State

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "panels_800x600"


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


@pytest.fixture(scope="module")
def imgs():
    return {k: cv2.imread(str(FIX / f"{k}.png")) for k in ("c_i_cacada", "loja_gremory", "sem_paineis")}


@pytest.fixture(scope="module")
def scanned(imgs, ocr):
    return {k: P.scan(img, ocr) for k, img in imgs.items()}


# ---------------------------------------------------------------------- localizar e ler
def test_locates_panels_by_title(scanned):
    assert set(scanned["c_i_cacada"][0]) == {"personagem", "inventario", "caca"}
    # o botão "Event Inventory" do canto não é confundido com o inventário
    assert set(scanned["loja_gremory"][0]) == {"loja"}
    assert scanned["sem_paineis"][0] == {}


def test_reads_character(imgs, scanned):
    hits, boxes = scanned["c_i_cacada"]
    r = P.read("personagem", imgs["c_i_cacada"], hits["personagem"], None, boxes)
    assert r.fields["Classe"] == "Impact Crusader"
    assert r.data["level"] == 275 and r.data["ptsremaining"] == 12
    assert (r.data["strength"], r.data["agility"], r.data["stamina"], r.data["energy"]) == (905, 391, 20, 200)


def test_reads_inventory_grid_and_zen(imgs, scanned):
    hits, boxes = scanned["c_i_cacada"]
    r = P.read("inventario", imgs["c_i_cacada"], hits["inventario"], None, boxes)
    assert (r.data["used"], r.data["total"]) == (48, 64)
    assert r.data["zen"] == 186_734_144
    assert r.fields["Zen"] == "186.734.144"


def test_reads_hunting_log(imgs, scanned):
    hits, boxes = scanned["c_i_cacada"]
    r = P.read("caca", imgs["c_i_cacada"], hits["caca"], None, boxes)
    assert r.data["tempo_s"] == 25 * 60 + 29
    assert r.data["gainedexp"] == 2440 and r.data["monsterkills"] == pytest.approx(0.07)
    assert r.fields["EXP por hora (estimado)"] == "8,8 mi"


@pytest.fixture(scope="module")
def layout2(ocr):
    """Layout que o usuário arrumou: C, I e Instant Hunting Log lado a lado, em dois personagens."""
    out = {}
    for k in ("elf_c_i_cacada", "pipe_c_i_cacada"):
        img = cv2.imread(str(FIX / f"{k}.png"))
        hits, boxes = P.scan(img, ocr)
        out[k] = {kind: P.read(kind, img, hit, ocr, boxes) for kind, hit in hits.items()}
    return out


def test_layout2_elf_points_dash_and_big_items(layout2):
    r = layout2["elf_c_i_cacada"]
    assert set(r) == {"personagem", "inventario", "caca"}
    c = r["personagem"].data
    assert (c["level"], c["ptsremaining"], c["agility"], c["energy"]) == (204, 0, 788, 100)  # "-" = sem pontos
    inv = r["inventario"].data
    assert (inv["used"], inv["zen"]) == (21, 54_093_918)  # células cobertas só pelo fundo verde do item contam
    h = r["caca"].data
    assert (h["tempo_s"], h["gainedexp"], h["monsterkills"]) == (28 * 60 + 10, 253, pytest.approx(0.18))


def test_layout2_ocr_noise_in_labels_and_values(layout2):
    r = layout2["pipe_c_i_cacada"]
    c = r["personagem"].data
    assert (c["level"], c["ptsremaining"], c["agility"]) == (277, 6, 402)  # botão "+" lido como lixo antes do 402
    h = r["caca"].data
    assert h["gainedexp"] == 2153  # rótulo lido "Gained EXR per second"
    assert r["inventario"].data["used"] == 48


def test_1280x960_scale_measured_and_full_crop(ocr):
    """1024x768 no jogo com escala 125% do Windows: a interface fica ~1,5x maior que em 800x600.
    A escala vem da distância título → textos fixos; antes o recorte saía pequeno e cortado."""
    img = cv2.imread(str(FIX / "c_i_cacada_1280.png"))
    hits, boxes = P.scan(img, ocr)
    assert set(hits) == {"personagem", "inventario", "caca"}
    for h in hits.values():
        assert 1.4 < h.scale < 1.6
    inv = P.read("inventario", img, hits["inventario"], ocr, boxes)
    x0, y0, x1, y1 = hits["inventario"].rect
    assert x0 < 460 and x1 > 820 and y1 > 840  # pega do título até o Zen
    assert (inv.data["used"], inv.data["zen"]) == (40, 186_404_204)
    c = P.read("personagem", img, hits["personagem"], ocr, boxes).data
    assert (c["level"], c["ptsremaining"], c["agility"]) == (284, 48, 402)
    h = P.read("caca", img, hits["caca"], ocr, boxes).data
    assert (h["tempo_s"], h["gainedexp"]) == (27 * 60 + 46, 2848)

    shop = cv2.imread(str(FIX / "loja_gremory_1280.png"))
    sh, sb = P.scan(shop, ocr)
    r = P.read("loja", shop, sh["loja"], ocr, sb)
    assert (r.data["count"], r.data["cap"], r.data["aba_ok"]) == (0, 150, True)
    assert P.read_shop_counter(shop, sh["loja"], ocr) == (0, 150)


def test_reads_gremory_counter_and_tab(imgs, scanned, ocr):
    img = imgs["loja_gremory"]
    hits, boxes = scanned["loja_gremory"]
    r = P.read("loja", img, hits["loja"], None, boxes)
    assert (r.data["count"], r.data["cap"], r.data["aba_ok"]) == (0, 150, True)
    assert P.read_shop_counter(img, hits["loja"], ocr) == (0, 150)


def test_wrong_gremory_tab_detected(imgs, scanned):
    img = imgs["loja_gremory"].copy()
    hit = scanned["loja_gremory"][0]["loja"]
    y0, y1 = (int(hit.ref[1] + v) for v in P.SHOP_TABS_Y)
    sel = img[y0:y1, int(hit.ref[0] + 70):int(hit.ref[0] + 120)].reshape(-1, 3).mean(0)
    plain = img[y0:y1, int(hit.ref[0] - 120):int(hit.ref[0] - 70)].reshape(-1, 3).mean(0)
    # "seleciona" a primeira aba e apaga o destaque da Personal Shop
    img[y0:y1, int(hit.ref[0] - 127):int(hit.ref[0] - 67)] = sel.astype(np.uint8)
    img[y0:y1, int(hit.ref[0] + 66):int(hit.ref[0] + 126)] = plain.astype(np.uint8)
    assert P.shop_selected_tab(img, hit) == 0


def test_still_open_is_cheap_check(imgs, scanned):
    for k, hit in scanned["c_i_cacada"][0].items():
        assert P.still_open(imgs["c_i_cacada"], hit), k
        assert not P.still_open(imgs["sem_paineis"], hit), k


@pytest.mark.parametrize("text,value", [
    ("186.734.144", 186_734_144), ("2,444", 2444), ("2.440", 2440), ("0.07", 0.07), ("3", 3), ("压905", 905),
    ("", None), ("abc", None),
])
def test_parse_number(text, value):
    assert P.parse_number(text) == (pytest.approx(value) if value else value)


def test_formats():
    assert P.fmt_big(8_784_000) == "8,8 mi" and P.fmt_int(1234567) == "1.234.567"
    assert P.fmt_dec(0.07) == "0,07" and P.fmt_dec(3.0) == "3" and P.parse_hms("00:25:29") == 1529


# ---------------------------------------------------------------------- acompanhamento
@pytest.fixture
def service(scanned, imgs, ocr, monkeypatch):
    """Serviço com a varredura da tela inteira trocada pelo resultado já calculado do print mais parecido."""
    def fake_scan(img, _ocr, kinds=P.KINDS):
        key = min(imgs, key=lambda k: float(np.mean(cv2.absdiff(img, imgs[k]))))
        return scanned[key]

    monkeypatch.setattr(panels_mod.P, "scan", fake_scan)
    clock = {"t": 1000.0}
    svc = PanelService(ocr=ocr, clock=lambda: clock["t"])
    svc.clock = clock
    return svc


def _check(svc, img, n=1, **kw):
    out = []
    args = dict(live=True, user_active=False, is_shop=False)
    args.update(kw)
    for _ in range(n):
        svc.clock["t"] += 30
        out += svc.check(1, img, **args)
    return out


def test_panel_closed_warns_once_and_reopen(service, imgs):
    assert _check(service, imgs["c_i_cacada"], 2) == []
    assert service.open_panels(1) == ["personagem", "inventario", "caca"]
    ev = _check(service, imgs["sem_paineis"], 2)
    assert ev == []  # 2 checagens ainda não bastam
    ev = _check(service, imgs["sem_paineis"], 3)
    assert sorted(e.panel for e in ev) == ["caca", "inventario", "personagem"]
    assert all(e.kind == "fechou" and "fechou" in e.detail for e in ev)
    ev = _check(service, imgs["c_i_cacada"], 1)
    assert sorted((e.kind, e.panel) for e in ev) == [("reabriu", "caca"), ("reabriu", "inventario"),
                                                    ("reabriu", "personagem")]


def test_closed_by_user_at_pc_is_not_warned(service, imgs):
    _check(service, imgs["c_i_cacada"], 2)
    assert _check(service, imgs["sem_paineis"], 5, user_active=True) == []
    assert _check(service, imgs["sem_paineis"], 5) == []  # fechou de propósito: deixou de ser esperado


def test_dead_or_disconnected_does_not_count(service, imgs):
    _check(service, imgs["c_i_cacada"], 2)
    assert _check(service, imgs["sem_paineis"], 6, live=False) == []


def test_shop_without_gremory_warns(service, imgs):
    ev = _check(service, imgs["sem_paineis"], 3, is_shop=True)
    assert [(e.kind, e.panel) for e in ev] == [("fechou", "loja")]
    assert "não está aberto" in ev[0].detail


def test_shop_sale_needs_two_reads_and_ignores_withdrawals(service, imgs, monkeypatch):
    seq = iter([0, 0, 1, 1, 1, None, 0, 2, 2])  # None = algo por cima do contador

    def fake_counter(img, hit, ocr):
        v = next(seq)
        return None if v is None else (v, 150)

    monkeypatch.setattr(panels_mod.P, "read_shop_counter", fake_counter)
    monkeypatch.setattr(panels_mod.P, "same_image", lambda a, b, tol=4.0: False)  # o contador "mudou" sempre
    got = []
    for _ in range(9):
        got.append([e for e in _check(service, imgs["loja_gremory"], 1, is_shop=True) if e.kind == "venda"])
    sales = [i for i, ev in enumerate(got) if ev]
    assert sales == [3, 8]  # 0→1 confirmado na 2ª leitura; retirada (→0) não avisa; 0→2 de novo
    assert "0 → 1 de 150" in got[3][0].detail and got[3][0].image[:2] == b"\xff\xd8"
    assert "+2 itens" in got[8][0].detail


def test_gremory_sale_in_any_window_and_while_app_closed(scanned, imgs, ocr, monkeypatch, tmp_path):
    """Gremory Case aberto em janela que não se chama Loja também avisa; venda com o app fechado também."""
    def fake_scan(img, _ocr, kinds=P.KINDS):
        key = min(imgs, key=lambda k: float(np.mean(cv2.absdiff(img, imgs[k]))))
        return scanned[key]

    monkeypatch.setattr(panels_mod.P, "scan", fake_scan)
    monkeypatch.setattr(panels_mod.P, "same_image", lambda a, b, tol=4.0: False)
    seq = iter([3, 3, 4, 4])
    monkeypatch.setattr(panels_mod.P, "read_shop_counter", lambda img, hit, o: (next(seq), 150))
    store = tmp_path / "contagem.json"
    clock = {"t": 1000.0}

    def run(svc, n):
        out = []
        for _ in range(n):
            clock["t"] += 10
            out += [e for e in svc.check(2, imgs["loja_gremory"], live=True, user_active=False, is_shop=False,
                                         shop_key="Vendedor") if e.kind == "venda"]
        return out

    svc = PanelService(ocr=ocr, clock=lambda: clock["t"], store=store)
    assert run(svc, 2) == []  # base 3
    sales = run(svc, 2)
    assert len(sales) == 1 and "3 → 4" in sales[0].detail
    cnt, cap, sold = svc.shop_status(2)
    assert (cnt, cap, sold) == (4, 150, clock["t"])
    # app fechado; ao abrir de novo o Gremory já tem 6 itens
    monkeypatch.setattr(panels_mod.P, "read_shop_counter", lambda img, hit, o: (6, 150))
    again = PanelService(ocr=ocr, clock=lambda: clock["t"], store=store)
    sales = run(again, 1)
    assert len(sales) == 1 and "enquanto o MU Sentinel estava fechado: 4 → 6" in sales[0].detail


def test_shop_counter_skips_ocr_when_unchanged(service, imgs, monkeypatch):
    calls = []

    def fake_counter(img, hit, ocr):
        calls.append(1)
        return (0, 150)

    monkeypatch.setattr(panels_mod.P, "read_shop_counter", fake_counter)
    _check(service, imgs["loja_gremory"], 6, is_shop=True)
    assert len(calls) == 1  # mesma imagem do contador: OCR só na primeira leitura


def test_inventory_report_tracks_changes(service, imgs):
    r1 = service.report(1, imgs["c_i_cacada"], "inventario")
    assert r1 is not None and "Desde o último pedido" not in r1.fields
    img2 = imgs["c_i_cacada"].copy()
    hit = r1.hit
    gx, gy, cell, _, _ = P.INV_GRID
    x, y = int(hit.ref[0] + gx + 6 * cell + 3), int(hit.ref[1] + gy + 7 * cell + 3)
    img2[y:y + 15, x:x + 15] = np.random.default_rng(1).integers(0, 255, (15, 15, 3), dtype=np.uint8)
    r2 = service.report(1, img2, "inventario")
    assert r2.data["new"] == 1 and r2.data["used"] == 49
    assert service.report(1, imgs["sem_paineis"], "inventario") is None


# ---------------------------------------------------------------------- loja: config e estado
def test_shop_name_rule():
    assert is_shop_name("Loja") and is_shop_name("loja 2") and is_shop_name("Loja do Elf") and is_shop_name("LOJA")
    assert not is_shop_name("Lojão") and not is_shop_name("Elf Kanturu") and not is_shop_name("")
    c = Config()
    c.slot(2).name = "Loja"
    assert c.is_shop(2) and not c.is_shop(1)


def test_config_yaml_has_panels_and_commands():
    y = Config().to_yaml()
    assert "paineis:" in y and "avisar_quando_fechar: true" in y and "aceitar_comandos: true" in y


def test_shop_slot_never_hunting_stalled():
    cfg = Config()
    cfg.slot(1).name = "Loja"
    tr = SlotTracker(1, cfg)
    t = 1_000_000.0
    for _ in range(400):  # 13 min parado na cidade, sem EXP
        t += 2
        sig = tr.update(Observation(ts=t, hp=(500, 500), exp=(10, 1000), map="Elbeland", coords=(50, 50),
                                    connected=True))
        assert not [s for s in sig if s.kind in ("PARADO", "MORTO")]
    assert tr.view.state == State.ONLINE


# ---------------------------------------------------------------------- pedidos pelo celular
@pytest.mark.parametrize("text,name,slot", [
    ("/inventario 2", "inventario", 2), ("🎒 Inventário", "inventario", None), ("/print@MeuBot 3", "print", 3),
    ("ok", "ok", None), ("✅ OK, vi o alerta", "ok", None), ("⏱ Caçada", "caca", None), ("/cacada 1", "caca", 1),
    ("🧍 Personagem", "personagem", None), ("C 2", "personagem", 2), ("/pausar 30", "pausar", 30),
    ("🏪 Loja", "loja", None), ("/start", "ajuda", None), ("📊 Status", "status", None),
])
def test_parse_commands(text, name, slot):
    cmd = parse(text)
    assert cmd is not None and (cmd.name, cmd.slot) == (name, slot)


def test_parse_unknown():
    assert parse("bom dia") is None and parse("") is None


class FakeEngine:
    def __init__(self, frames, cfg, service):
        from musentinel.core.alerts import AlertManager
        from musentinel.core.engine import SlotSnapshot

        self.cfg = cfg
        self.frames = frames
        self.panels = service
        self.alerts = AlertManager(cfg, [])
        self.acked = 0
        self._snaps = [SlotSnapshot(n, cfg.slot_name(n), State.CACANDO, 0.0, True, None, (800, 600), map="Kanturu",
                                    hp=(800, 811), exp_per_h=5_000_000, exp_pct_per_h=2.5) for n in frames]

    def snapshots(self):
        return self._snaps

    def frame_copy(self, n):
        img = self.frames.get(n)
        return None if img is None else img.copy()

    def ack(self, slot=None):
        self.acked += 1
        return 1


@pytest.fixture
def remote(service, imgs):
    cfg = Config()
    cfg.slot(1).name = "Elf"
    cfg.slot(2).name = "Loja"
    eng = FakeEngine({1: imgs["c_i_cacada"], 2: imgs["loja_gremory"]}, cfg, service)
    return RemoteCommands(eng, clock=lambda: 600.0), eng


def test_remote_inventory_sends_photo_and_summary(remote):
    rc, _ = remote
    out = rc.handle(parse("/inventario"))
    assert len(out) == 1 and out[0].image[:2] == b"\xff\xd8"
    assert out[0].text.startswith('Slot 1 "Elf" — Inventário') and "48 ocupados" in out[0].text


def test_remote_panel_not_open_explains(remote):
    rc, _ = remote
    out = rc.handle(parse("/inventario 2"))
    assert len(out) == 1 and out[0].image is None
    assert "não está aberto" in out[0].text and "abra com I" in out[0].text


def test_remote_shop_uses_loja_slot(remote):
    rc, _ = remote
    out = rc.handle(parse("🏪 Loja"))
    assert len(out) == 1 and out[0].text.startswith('Slot 2 "Loja" — Gremory Case') and "0 / 150" in out[0].text


def test_remote_status_and_ok(remote):
    rc, eng = remote
    st = rc.handle(parse("/status"))[0].text
    assert 'Slot 1 "Elf" — CAÇANDO' in st and "EXP/h 5,0 mi (2,5%/h)" in st and "(loja)" in st
    assert "visto" in rc.handle(parse("ok"))[0].text and eng.acked == 1


def test_remote_target_picker_and_filter(remote, tmp_path):
    rc, eng = remote
    rc._store = tmp_path / "alvo.json"
    pick = rc.handle(parse("🎯 Escolher personagem"), chat_id=111)[0]
    labels = [label for row in pick.buttons for label, _ in row]
    assert labels == ["✓ Todos", "1 · Elf", "2 · Loja"] and "Agora: Todos" in pick.text
    toast, new = rc.on_button("alvo:1", 111)
    assert toast == "Agora: 1 · Elf" and "✓ 1 · Elf" in [label for row in new.buttons for label, _ in row]
    st = rc.handle(parse("/status"), chat_id=111)[0].text
    assert 'Slot 1 "Elf"' in st and 'Slot 2' not in st  # só o escolhido
    assert len(rc.handle(parse("/print"), chat_id=111)) == 1
    assert 'Slot 2' in rc.handle(parse("/status"), chat_id=222)[0].text  # outra conversa: todos
    assert rc.handle(parse("/print 2"), chat_id=111)[0].text.startswith('Slot 2')  # número digitado manda
    # a escolha sobrevive a reiniciar o app
    again = RemoteCommands(eng, store=rc._store)
    assert again.target_name(111) == "1 · Elf"
    rc.on_button("alvo:0", 111)
    assert rc.target_name(111) == "Todos"


def test_remote_target_not_open(remote):
    rc, _ = remote
    rc.targets[5] = 7
    out = rc.handle(parse("/inventario"), chat_id=5)
    assert "não está aberto agora" in out[0].text and "Escolher personagem" in out[0].text


def test_remote_print(remote):
    rc, _ = remote
    out = rc.handle(parse("/print 2"))
    assert len(out) == 1 and out[0].image[:2] == b"\xff\xd8" and out[0].text.startswith('Slot 2 "Loja"')
    assert "Não existe o slot 7" in rc.handle(parse("/print 7"))[0].text


def test_engine_turns_panel_events_into_alerts(monkeypatch):
    from musentinel.core import engine as engine_mod
    from musentinel.core.events import EventBus
    from musentinel.core.notifiers import FakeNotifier

    cfg = Config()
    ext = FakeNotifier(external=True)
    ext.supports_images = True
    e = engine_mod.Engine(cfg, EventBus(), [ext])
    e._panel_event(2, PanelEvent("venda", "loja", "Gremory Case (Personal Shop): 0 → 1 de 150", b"\xff\xd8x"))
    e._panel_event(1, PanelEvent("fechou", "inventario", "Inventário (I) fechou: abra com I"))
    e.alerts.flush()
    assert "VENDA NA LOJA" in ext.sent[0] and "PAINEL FECHADO" in ext.sent[0]
    assert ext.images[0] == b"\xff\xd8x"
    cfg.panels.warn_closed = False
    e._panel_event(1, PanelEvent("fechou", "caca", "x"))
    e.alerts.flush()
    assert len(ext.sent) == 1
