"""MU Sentinel — monitor de janelas do MU Online."""

import os as _os

# Antes de qualquer import do numpy/OpenCV: a biblioteca de matemática do numpy (OpenBLAS) reserva um
# buffer por núcleo (~490 MB num PC de 16 núcleos) e o app não faz álgebra pesada. Com 1 thread: ~18 MB.
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_k, "1")

from importlib.metadata import PackageNotFoundError, version  # noqa: E402

try:
    __version__ = version("musentinel")
except PackageNotFoundError:  # rodando direto do código-fonte
    __version__ = "0.0.0-dev"
