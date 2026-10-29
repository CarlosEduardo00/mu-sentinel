"""Coleta e rotula prints sozinho, sem o usuário digitar nada.

Uso:
    python -m musentinel.tools.autolabel --minutos 60

Para cada print, cada campo numérico é lido por dois métodos independentes:
  1. template matching (o leitor do app)
  2. OCR em duas escalas (só vale se as duas concordarem)
Um campo vira gabarito quando:
  - os dois métodos dão exatamente o mesmo valor; ou
  - só o OCR leu e o valor é coerente com a leitura anterior da mesma janela
    (Hunting Time avançou o mesmo que o relógio; HP/EXP máximos iguais; EXP não caiu).
Quando os dois métodos leem valores diferentes, o print vai para
captures/revisar/ (é o único caso que precisa de olho humano).
O perfil aprende com os gabaritos durante a coleta.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..core import paths, winapi
from ..core.capture import CaptureError, make_backend
from ..core.perception.dataset import TESTED_ROIS, Sample, mask_to_rois
from ..core.perception.fields import PARSERS
from ..core.perception.ocr import DEFAULT_CITIES, OcrEngine
from ..core.perception.profile import CHARSETS
from ..core.perception.reader import HudReader
from ..core.perception.training import learn_sample

NUM_FIELDS = ("hp", "coords", "exp", "hunting_time")


@dataclass
class WinState:
    """Últimas leituras confirmadas de uma janela, para checar coerência no tempo."""

    last_hash: np.ndarray | None = None
    hunt: tuple[float, int] | None = None  # (relógio, segundos do Hunting Time)
    hp_max: int | None = None
    exp: tuple[int, int] | None = None
    history: dict = field(default_factory=dict)


def coherent(name: str, value, st: WinState, now: float) -> bool | None:
    """True = coerente, False = incoerente, None = sem como checar."""
    if name == "hunting_time":
        if st.hunt is None:
            return None
        t0, v0 = st.hunt
        if value < v0:
            return None  # Helper reiniciado: contador zerou
        return abs((value - v0) - (now - t0)) <= 3
    if name == "hp":
        if st.hp_max is None:
            return None
        return value[1] == st.hp_max
    if name == "exp":
        if st.exp is None:
            return None
        if value[1] != st.exp[1]:
            return None  # subiu de nível
        return value[0] >= st.exp[0]
    return None


def remember(name: str, value, st: WinState, now: float) -> None:
    if name == "hunting_time":
        st.hunt = (now, value)
    elif name == "hp":
        st.hp_max = value[1]
    elif name == "exp":
        st.exp = value


def tiny(img: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (32, 24), interpolation=cv2.INTER_AREA).astype(int)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coleta e rotula prints automaticamente.")
    ap.add_argument("--minutos", type=float, default=60)
    ap.add_argument("--intervalo", type=float, default=12)
    ap.add_argument("--suite", type=Path, default=None, help="padrão: a suíte da resolução de cada janela")
    a = ap.parse_args(argv)

    winapi.enable_dpi_awareness()
    cap = make_backend("auto")
    ocr = OcrEngine()
    ctx: dict[tuple[int, int], tuple] = {}  # resolução → (perfil, leitor, suíte)
    skipped: set[tuple[int, int]] = set()

    def context(size: tuple[int, int]):
        if size not in ctx:
            if not paths.has_profile(*size):
                if size not in skipped:
                    skipped.add(size)
                    print(f"janela {size[0]}x{size[1]}: sem perfil para esta resolução (calibre antes)")
                return None
            prof = paths.load_or_default_profile(*size)
            # template puro: o OCR é o segundo leitor
            ctx[size] = (prof, HudReader(prof, ocr=ocr, ocr_fallback=False), a.suite or paths.fixtures_dir(size))
        return ctx[size]
    cities = {c.lower() for c in DEFAULT_CITIES}
    review = paths.captures_dir() / "revisar"
    states: dict[int, WinState] = {}
    counts = {"gabaritos": 0, "conflitos": 0, "concordou": 0, "so_ocr": 0, "aprendeu": 0}
    t_end = time.time() + a.minutos * 60
    print(f"Autorrotulando por {a.minutos} min (intervalo {a.intervalo}s). Ctrl+C para parar.")

    try:
        while time.time() < t_end:
            for w in sorted(winapi.list_windows(), key=lambda w: w.pid):
                try:
                    f = cap.grab(w.hwnd)
                except CaptureError as e:
                    print(f"[{w.pid}] sem captura: {e}")
                    continue
                c = context(f.size)
                if c is None:
                    continue
                profile, reader, suite = c
                st = states.setdefault(w.hwnd, WinState())
                h = tiny(f.image)
                if st.last_hash is not None and float(np.abs(h - st.last_hash).mean()) < 1.0:
                    continue
                st.last_hash = h
                now = time.time()
                img = f.image
                expected: dict = {}
                evidence: dict = {}
                conflict = False

                for name in NUM_FIELDS:
                    tpl = reader.read_field(img, name)
                    if tpl.status == "absent":
                        o, _ = ocr.read_number(profile.rois[name].crop(img), CHARSETS[name])
                        if o is None:
                            expected[name] = None
                            evidence[name] = "ausente (painel fechado, OCR vazio)"
                        continue
                    o_text, o_score = ocr.read_number(profile.rois[name].crop(img), CHARSETS[name])
                    o_val = PARSERS[name](o_text, o_score) if o_text else None
                    o_ok = o_val is not None and o_val.ok and o_score >= 0.85
                    if tpl.ok and o_ok:
                        if tpl.value == o_val.value:
                            expected[name] = tpl.raw
                            evidence[name] = "template = OCR"
                            counts["concordou"] += 1
                            remember(name, tpl.value, st, now)
                        else:
                            conflict = True
                            evidence[name] = f"CONFLITO template {tpl.raw!r} × OCR {o_text!r}"
                    elif o_ok:
                        c = coherent(name, o_val.value, st, now)
                        if c is False:
                            evidence[name] = f"OCR {o_text!r} incoerente com a leitura anterior"
                            continue
                        expected[name] = o_text
                        evidence[name] = "OCR" + (" + coerente no tempo" if c else " (2 escalas)")
                        counts["so_ocr"] += 1
                        remember(name, o_val.value, st, now)
                    elif tpl.ok:
                        c = coherent(name, tpl.value, st, now)
                        if c:
                            expected[name] = tpl.raw
                            evidence[name] = "template + coerente no tempo"
                            remember(name, tpl.value, st, now)

                m = reader.read_field(img, "map")
                if m.ok:
                    expected["map"] = m.value
                    evidence["map"] = f"mapa (conf {m.confidence:.2f})"

                stamp = f"{datetime.now():%Y%m%d_%H%M%S}_pid{w.pid}"
                if conflict:
                    review.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(review / f"{stamp}.png"), img)
                    (review / f"{stamp}.txt").write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
                    counts["conflitos"] += 1
                    print(f"[{w.pid}] conflito → revisar: {evidence}")
                    continue
                if len([k for k in expected if k in NUM_FIELDS]) < 2:
                    continue  # pouco confirmado: não vale como gabarito

                hp = expected.get("hp") or ""
                scene = "morto" if hp.startswith("0/") else (
                    "cidade" if str(expected.get("map", "")).lower() in cities else "cacando")
                d = suite / scene
                d.mkdir(parents=True, exist_ok=True)
                png = d / f"auto_{stamp}.png"
                # original completo fica fora do git; a suíte guarda só as regiões do HUD
                orig = paths.captures_dir() / "originais"
                orig.mkdir(parents=True, exist_ok=True)
                cv2.imencode(".png", img)[1].tofile(str(orig / png.name))
                keep = [profile.rois[k] for k in TESTED_ROIS if k in profile.rois]
                cv2.imencode(".png", mask_to_rois(img, keep))[1].tofile(str(png))
                Sample(png, scene, expected).save()
                data = json.loads(png.with_suffix(".json").read_text(encoding="utf-8"))
                data["auto"] = evidence
                png.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                counts["gabaritos"] += 1

                learned = learn_sample(profile, reader, img, expected)
                if learned:
                    counts["aprendeu"] += 1
                    profile.save(paths.profile_path(*profile.client_size))
                print(f"[{w.pid}] {counts['gabaritos']:4d} {scene:8s} {expected}" + (f"  aprendeu {learned}" if learned else ""))
            time.sleep(a.intervalo)
    except KeyboardInterrupt:
        pass
    finally:
        cap.close()
        for profile, _, _ in ctx.values():
            profile.save(paths.profile_path(*profile.client_size))
    print(f"Fim: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
