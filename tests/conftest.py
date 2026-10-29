"""Isola os testes do %APPDATA% real: usam só o perfil-semente do repositório."""

import os
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="musentinel-test-")
