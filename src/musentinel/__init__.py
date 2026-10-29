"""MU Sentinel — monitor de janelas do MU Online."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("musentinel")
except PackageNotFoundError:  # rodando direto do código-fonte
    __version__ = "0.0.0-dev"
