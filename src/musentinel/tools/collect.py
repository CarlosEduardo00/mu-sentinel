"""Coletor de prints: grava a área cliente de cada janela do MU a cada N segundos.

Uso:
    python -m musentinel.tools.collect --intervalo 15
Ctrl+C para parar. Pula quadros quase idênticos ao anterior da mesma janela.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..core import paths, winapi
from ..core.capture import CaptureError, make_backend


def tiny_hash(img: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (32, 24), interpolation=cv2.INTER_AREA)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grava prints das janelas do MU para rotular.")
    ap.add_argument("--intervalo", type=float, default=15.0, help="segundos entre rodadas")
    ap.add_argument("--titulo", default="MU")
    ap.add_argument("--processo", default="main.exe")
    ap.add_argument("--saida", type=Path, default=None)
    ap.add_argument("--max", type=int, default=0, help="parar após N prints (0 = sem limite)")
    ap.add_argument("--backend", default="auto", choices=["auto", "wgc", "printwindow"])
    a = ap.parse_args(argv)

    winapi.enable_dpi_awareness()
    out = a.saida or paths.captures_dir() / datetime.now().strftime("%Y%m%d")
    out.mkdir(parents=True, exist_ok=True)
    cap = make_backend(a.backend)
    last: dict[int, np.ndarray] = {}
    saved = 0
    print(f"Gravando em {out}  (Ctrl+C para parar)")
    try:
        while True:
            wins = winapi.list_windows(a.titulo, a.processo)
            if not wins:
                print("nenhuma janela do MU encontrada")
            for i, w in enumerate(sorted(wins, key=lambda w: w.pid)):
                try:
                    f = cap.grab(w.hwnd)
                except CaptureError as e:
                    print(f"[{w.pid}] não capturou: {e}")
                    continue
                h = tiny_hash(f.image)
                prev = last.get(w.hwnd)
                if prev is not None and float(np.abs(h.astype(int) - prev).mean()) < 1.5:
                    continue  # praticamente igual ao último
                last[w.hwnd] = h
                name = f"{datetime.now():%H%M%S}_pid{w.pid}_{f.size[0]}x{f.size[1]}.png"
                cv2.imwrite(str(out / name), f.image)
                saved += 1
                print(f"{saved:5d}  {name}")
                if a.max and saved >= a.max:
                    return
            time.sleep(a.intervalo)
    except KeyboardInterrupt:
        pass
    finally:
        cap.close()
        print(f"{saved} prints gravados em {out}")


if __name__ == "__main__":
    main()
