"""Teste de captura: janela coberta, minimizada e monitor apagado.

Uso:
    python -m musentinel.tools.capture_check --minutos 3
    python -m musentinel.tools.capture_check --minutos 3 --apagar-monitor

Com --apagar-monitor o app desliga o monitor 10 s depois de começar
(como a economia de energia do Windows). NÃO mexa no mouse/teclado até o fim:
qualquer movimento liga o monitor de novo e invalida essa parte do teste.

Gera reports/captura_<data>.md dizendo, para cada janela, se os quadros
continuaram chegando e mudando em cada condição.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..core import paths, winapi
from ..core.capture import CaptureError, WgcCapture, PrintWindowCapture, WindowMinimizedError
from ..core.perception.reader import HudReader


def last_input_age_s() -> float:
    import ctypes
    import ctypes.wintypes as wt

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(li)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Testa a captura em várias condições.")
    ap.add_argument("--minutos", type=float, default=3.0)
    ap.add_argument("--intervalo", type=float, default=5.0)
    ap.add_argument("--apagar-monitor", action="store_true")
    ap.add_argument("--saida", type=Path, default=paths.app_dir() / "reports")
    a = ap.parse_args(argv)

    winapi.enable_dpi_awareness()
    wins = winapi.list_windows("MU", "main.exe")
    if not wins:
        print("Nenhuma janela do MU aberta.")
        return 1
    backends = [WgcCapture(), PrintWindowCapture()]
    profile = paths.load_or_default_profile()
    reader = HudReader(profile)
    last: dict[tuple[str, int], np.ndarray] = {}
    # condição -> backend -> [quadros ok, quadros que mudaram, falhas, leituras de HP ok]
    stats = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    errors: dict[str, set[str]] = defaultdict(set)

    t0 = time.time()
    off_sent = False
    print(f"Testando {len(wins)} janela(s) por {a.minutos} min…")
    while time.time() - t0 < a.minutos * 60:
        if a.apagar_monitor and not off_sent and time.time() - t0 > 10:
            winapi.monitor_off()
            off_sent = True
            off_at = time.time()
        for w in wins:
            if not winapi.is_window(w.hwnd):
                continue
            cov = winapi.covered_fraction(w.hwnd)
            if winapi.is_minimized(w.hwnd):
                cond = "minimizada"
            elif off_sent and last_input_age_s() >= time.time() - off_at - 1:
                cond = "monitor apagado"
            elif cov >= 0.5:
                cond = "coberta ≥50%"
            elif cov > 0.02:
                cond = "parcialmente coberta"
            else:
                cond = "visível"
            for be in backends:
                st = stats[cond][be.name]
                try:
                    f = be.grab(w.hwnd)
                except WindowMinimizedError:
                    st[2] += 1
                    errors[be.name].add("minimizada não renderiza")
                    continue
                except CaptureError as e:
                    st[2] += 1
                    errors[be.name].add(str(e))
                    continue
                st[0] += 1
                small = cv2.resize(f.image, (64, 48))
                prev = last.get((be.name, w.hwnd))
                if prev is not None and float(np.abs(small.astype(int) - prev).mean()) > 0.5:
                    st[1] += 1
                last[(be.name, w.hwnd)] = small.astype(int)
                if reader.read_field(f.image, "hp").ok:
                    st[3] += 1
        time.sleep(a.intervalo)
    for be in backends:
        be.close()

    lines = [
        "# Teste de captura",
        "",
        f"- Data: {datetime.now():%d/%m/%Y %H:%M} · duração {a.minutos} min · {len(wins)} janela(s)",
        f"- App rodando como administrador: {'sim' if winapi.current_process_elevated() else 'não'}",
        f"- Client rodando como administrador: {', '.join(str(w.elevated) for w in wins)}",
        "",
        "| Condição | Método | Quadros ok | Quadros que mudaram | Falhas | HP lido |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cond, per in stats.items():
        for be, (ok, changed, fail, hp) in per.items():
            lines.append(f"| {cond} | {be} | {ok} | {changed} | {fail} | {hp} |")
    lines += ["", "Quadros que mudaram > 0 indica imagem viva (não congelada) naquela condição.", ""]
    for be, errs in errors.items():
        lines.append(f"- Falhas de **{be}**: " + "; ".join(sorted(errs)))
    if a.apagar_monitor:
        lines.append("")
        lines.append(
            "- Monitor apagado: se não aparece a linha 'monitor apagado', o mouse/teclado foi usado logo depois "
            "de apagar e o monitor voltou."
        )
    text = "\n".join(lines) + "\n"
    a.saida.mkdir(parents=True, exist_ok=True)
    out = a.saida / f"captura_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Relatório salvo em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
