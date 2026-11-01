"""Atualização pelo GitHub Releases: procura versão nova, baixa, confere e troca os arquivos.

Fluxo:
1. check(): consulta as releases do repositório e devolve a versão mais nova que a instalada,
   com as novidades de todas as versões no meio.
2. download(): baixa o zip da release, confere tamanho e SHA-256 e extrai numa pasta de preparo.
3. launch_finisher(): abre o MUSentinel.exe NOVO (da pasta de preparo) com --concluir-atualizacao,
   e o app atual fecha.
4. finish() roda no exe novo: espera o app antigo fechar, troca o MUSentinel.exe e a pasta
   _internal da pasta instalada, desfaz tudo se algo falhar e abre o app de novo.

A configuração, o Telegram e o modo portátil (portable.flag e data\\) não são tocados.
Só conversa com o GitHub (api.github.com e o download da release); nada do usuário é enviado.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import __version__
from . import paths
from .changelog import _key, is_newer

log = logging.getLogger(__name__)

REPO = "OWNER/mu-sentinel"  # dono/nome do repositório público no GitHub
API = "https://api.github.com/repos/{repo}/releases?per_page=20"
ASSET = "MUSentinel-v{version}-win64.zip"
EXE = "MUSentinel.exe"
INTERNAL = "_internal"
OLD_TAG = ".antigo-"  # sufixo das cópias de segurança durante a troca (apagadas no fim)
FINISH_FLAG = "--concluir-atualizacao"
MAX_NOTES = 8000
CHECK_EVERY_S = 12 * 3600

_TAG = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")


class UpdateError(Exception):
    """Falha com mensagem pronta para o usuário (pt-BR)."""


class UpdateCancelled(UpdateError):
    def __init__(self) -> None:
        super().__init__("download cancelado")


@dataclass
class Release:
    version: str
    notes: str  # markdown com as novidades de todas as versões mais novas que a instalada
    page_url: str
    zip_url: str | None
    zip_size: int
    sha256: str | None  # "digest" que o GitHub calcula para o arquivo
    sha256_url: str | None  # arquivo .sha256 publicado junto (lancar.ps1)


# ---------------------------------------------------------------------------------- consulta
def enabled() -> bool:
    return "/" in REPO and not REPO.startswith("OWNER/")


def can_self_update() -> bool:
    """Só o .exe se atualiza sozinho (rodando do código-fonte é git pull)."""
    return bool(getattr(sys, "frozen", False))


def releases_page(repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases/latest"


def _client(timeout: float = 20.0):
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"User-Agent": f"MUSentinel/{__version__}",
                                 "Accept": "application/vnd.github+json"})


def _version_of(tag: str) -> str | None:
    m = _TAG.match((tag or "").strip())
    return m.group(1) if m else None


def parse_releases(data: list, current: str, repo: str = REPO) -> Release | None:
    """Lista de releases da API → a mais nova que current (None = já está na mais nova)."""
    newer = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        v = _version_of(r.get("tag_name", ""))
        if v and is_newer(v, current):
            newer.append((v, r))
    if not newer:
        return None
    newer.sort(key=lambda t: _key(t[0]), reverse=True)
    version, top = newer[0]
    notes = "\n\n".join(f"## Versão {v}\n\n{(r.get('body') or '').strip() or '(sem descrição)'}"
                        for v, r in newer)
    if len(notes) > MAX_NOTES:
        notes = notes[:MAX_NOTES].rsplit("\n", 1)[0] + "\n\n…(continua na página da versão)"
    assets = {a.get("name"): a for a in top.get("assets") or [] if isinstance(a, dict)}
    z = assets.get(ASSET.format(version=version)) or {}
    sha_file = assets.get(ASSET.format(version=version) + ".sha256") or {}
    digest = str(z.get("digest") or "")
    return Release(
        version=version,
        notes=notes,
        page_url=top.get("html_url") or releases_page(repo),
        zip_url=z.get("browser_download_url"),
        zip_size=int(z.get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
        sha256_url=sha_file.get("browser_download_url"),
    )


def check(current: str = __version__, repo: str = REPO, client=None) -> Release | None:
    """Pergunta ao GitHub se há versão nova. Erro de rede/limite vira UpdateError."""
    own = client is None
    client = client or _client()
    try:
        r = client.get(API.format(repo=repo))
    except Exception as exc:
        raise UpdateError(f"sem conexão com o GitHub ({type(exc).__name__})") from exc
    finally:
        if own:
            client.close()
    if r.status_code == 404:
        raise UpdateError("o repositório de atualizações não foi encontrado")
    if r.status_code in (403, 429):
        raise UpdateError("o GitHub limitou as consultas por agora; tento de novo mais tarde")
    if r.status_code != 200:
        raise UpdateError(f"o GitHub respondeu HTTP {r.status_code}")
    try:
        return parse_releases(r.json(), current, repo)
    except ValueError as exc:
        raise UpdateError("resposta inválida do GitHub") from exc


# ---------------------------------------------------------------------------------- download
def update_dir() -> Path:
    """Pasta de preparo (fora da pasta do app e da pasta de dados)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / paths.APP_NAME / "atualizacao"


def _expected_sha(rel: Release, client) -> str:
    if rel.sha256:
        return rel.sha256
    if rel.sha256_url:
        try:
            r = client.get(rel.sha256_url)
        except Exception as exc:
            raise UpdateError(f"sem conexão com o GitHub ({type(exc).__name__})") from exc
        m = re.search(r"\b([0-9a-fA-F]{64})\b", r.text if r.status_code == 200 else "")
        if m:
            return m.group(1).lower()
    raise UpdateError("a versão nova não tem a soma de conferência (SHA-256); baixe pela página")


def safe_extract(zpath: Path, out: Path) -> None:
    """Extrai sem deixar nenhum arquivo sair da pasta de destino."""
    out = out.resolve()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = (out / info.filename).resolve()
            if target != out and out not in target.parents:
                raise UpdateError("o zip baixado tem um caminho inválido; nada foi trocado")
        z.extractall(out)


def find_app_root(folder: Path) -> Path:
    """Pasta que tem o MUSentinel.exe e a _internal (o zip traz uma pasta MUSentinel dentro)."""
    for cand in [folder, *sorted(p for p in folder.iterdir() if p.is_dir())]:
        if (cand / EXE).is_file() and (cand / INTERNAL).is_dir():
            return cand
    raise UpdateError("o zip baixado não tem o MUSentinel.exe; nada foi trocado")


def download(rel: Release, dest: Path | None = None, progress: Callable[[int, int], None] | None = None,
             cancel: Callable[[], bool] | None = None, client=None) -> Path:
    """Baixa, confere e extrai a versão nova. Devolve a pasta com o MUSentinel.exe novo."""
    if not rel.zip_url:
        raise UpdateError("a versão nova não tem o arquivo do Windows (zip); baixe pela página")
    own = client is None
    client = client or _client(timeout=60.0)
    try:
        expected = _expected_sha(rel, client)
        work = (dest or update_dir()) / f"v{rel.version}"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        zpath = work / "download.zip"
        h, got = hashlib.sha256(), 0
        try:
            with client.stream("GET", rel.zip_url) as r:
                if r.status_code != 200:
                    raise UpdateError(f"o download falhou (HTTP {r.status_code})")
                total = int(r.headers.get("content-length") or rel.zip_size or 0)
                with open(zpath, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        if cancel and cancel():
                            raise UpdateCancelled()
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, total)
        except UpdateError:
            raise
        except Exception as exc:
            raise UpdateError(f"o download foi interrompido ({type(exc).__name__})") from exc
    finally:
        if own:
            client.close()
    if rel.zip_size and got != rel.zip_size:
        raise UpdateError("o download veio incompleto; tente de novo")
    if h.hexdigest() != expected:
        raise UpdateError("o arquivo baixado não confere (SHA-256 diferente); nada foi trocado")
    out = work / "novo"
    safe_extract(zpath, out)
    zpath.unlink(missing_ok=True)
    return find_app_root(out)


# ---------------------------------------------------------------------------------- troca
def can_write(folder: Path) -> bool:
    probe = folder / f".musentinel-teste-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _detached(args: list[str], cwd: Path) -> None:
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, cwd=str(cwd), creationflags=flags, close_fds=True)


def launch_finisher(new_root: Path, target: Path, relaunch_args: list[str] | None = None) -> None:
    """Abre o exe novo para fazer a troca; quem chama fecha o app logo depois."""
    _detached([str(new_root / EXE), FINISH_FLAG, str(target), str(os.getpid()), *(relaunch_args or [])],
              new_root)


def wait_exit(pid: int, timeout: float) -> bool:
    import psutil

    try:
        psutil.Process(pid).wait(timeout)
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        return False
    return True


def _retry(fn, timeout: float = 30.0, step: float = 0.5):
    """Antivírus e o Explorer seguram arquivos por alguns segundos: tenta de novo até timeout."""
    end = time.monotonic() + timeout
    while True:
        try:
            return fn()
        except OSError:
            if time.monotonic() >= end:
                raise
            time.sleep(step)


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def swap(src: Path, target: Path, retry_s: float = 30.0) -> None:
    """Troca MUSentinel.exe, _internal e os textos da pasta instalada pelos de src.

    Se algo falhar no meio, volta tudo como estava e levanta o erro.
    """
    stamp = time.strftime("%Y%m%d%H%M%S")
    moved: list[tuple[Path, Path]] = []
    try:
        for name in (INTERNAL, EXE):
            p = target / name
            if p.exists():
                bak = target / f"{name}{OLD_TAG}{stamp}"
                _retry(lambda p=p, bak=bak: os.replace(p, bak), retry_s)
                moved.append((p, bak))
        shutil.copytree(src / INTERNAL, target / INTERNAL)
        shutil.copy2(src / EXE, target / EXE)
        for f in src.iterdir():  # LEIA-ME, NOVIDADES e o aviso de extrair
            if f.is_file() and f.name != EXE:
                shutil.copy2(f, target / f.name)
    except Exception:
        log.exception("troca falhou; voltando a versão anterior")
        for p, bak in reversed(moved):
            try:
                if p.exists():
                    _remove(p)
                os.replace(bak, p)
            except OSError:
                log.exception("não consegui voltar %s", p.name)
        raise
    for _, bak in moved:
        try:
            _remove(bak)
        except OSError:  # apaga na próxima abertura (cleanup)
            log.warning("não consegui apagar %s agora", bak.name)


def finish(src: Path, target: Path, old_pid: int, relaunch_args: list[str] | None = None,
           wait_s: float = 90.0, retry_s: float = 30.0,
           start: Callable[[list[str], Path], None] = _detached,
           notify: Callable[[str], None] | None = None) -> bool:
    """Roda no exe novo: espera o antigo fechar, troca os arquivos e abre o app de novo."""
    args = relaunch_args or []
    log.info("concluindo atualização: %s -> %s (pid antigo %s)", src, target, old_pid)
    if not wait_exit(old_pid, wait_s):
        msg = ("A atualização não terminou: o MU Sentinel antigo não fechou. Nada foi trocado. "
               "Feche o app e tente de novo.")
        log.error(msg)
        if notify:
            notify(msg)
        return False
    try:
        swap(src, target, retry_s)
    except Exception as exc:
        msg = (f"A atualização não terminou ({type(exc).__name__}: {exc}). A versão anterior foi mantida "
               f"e vai abrir de novo. Se repetir, baixe o zip novo pela página do GitHub.")
        if notify:
            notify(msg)
        if (target / EXE).exists():
            start([str(target / EXE), *args], target)
        return False
    log.info("atualização concluída")
    start([str(target / EXE), *args], target)
    return True


def cleanup(target: Path | None = None) -> None:
    """Na abertura: apaga sobras da troca e a pasta de preparo (o que estiver livre)."""
    target = target or paths.app_dir()
    try:
        for p in target.iterdir():
            if OLD_TAG in p.name:
                try:
                    _remove(p)
                except OSError:
                    pass
    except OSError:
        pass
    shutil.rmtree(update_dir(), ignore_errors=True)


def _message_box(text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "MU Sentinel", 0x30)  # MB_ICONWARNING
    except Exception:
        pass


def finish_main(argv: list[str]) -> int:
    """MUSentinel.exe --concluir-atualizacao <pasta instalada> <pid antigo> [args para reabrir]."""
    from .logsetup import logs_dir

    handler = logging.FileHandler(logs_dir() / "atualizacao.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    if len(argv) < 2 or not argv[1].isdigit():
        log.error("argumentos inválidos: %s", argv)
        return 2
    src = paths.app_dir()
    target = Path(argv[0])
    if src.resolve() == target.resolve():
        log.error("a pasta nova e a instalada são a mesma: %s", src)
        return 2
    ok = finish(src, target, int(argv[1]), argv[2:], notify=_message_box)
    return 0 if ok else 1
