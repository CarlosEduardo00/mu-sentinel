"""Atualização pelo GitHub: consulta, download conferido, troca dos arquivos e volta em caso de erro."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile

import httpx
import pytest

from musentinel.core import updater
from musentinel.core.config import Config
from musentinel.core.updater import Release, UpdateCancelled, UpdateError

REPO = "dono/mu-sentinel"


def rel_json(tag, body="novidade", assets=(), draft=False, pre=False):
    return {"tag_name": tag, "body": body, "draft": draft, "prerelease": pre,
            "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "assets": list(assets)}


def asset(name, url=None, size=0, digest=None):
    a = {"name": name, "browser_download_url": url or f"https://dl/{name}", "size": size}
    if digest:
        a["digest"] = digest
    return a


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


APP_ZIP = make_zip({"MUSentinel/MUSentinel.exe": b"exe novo", "MUSentinel/_internal/lib.dll": b"dll nova",
                    "MUSentinel/LEIA-ME.md": b"leia novo"})


def client_for(routes: dict[str, httpx.Response | Exception]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        r = routes.get(str(request.url))
        if isinstance(r, Exception):
            raise r
        return r if r is not None else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def release(data=APP_ZIP, sha=None, size=None, **kw) -> Release:
    return Release(version="0.3.0", notes="x", page_url="https://p", zip_url="https://dl/app.zip",
                   zip_size=len(data) if size is None else size,
                   sha256=hashlib.sha256(data).hexdigest() if sha is None else sha, sha256_url=None, **kw)


# ---------------------------------------------------------------------------------- consulta
def test_parse_picks_newest_and_joins_notes():
    data = [
        rel_json("v0.4.0", "rascunho", draft=True),
        rel_json("v0.3.1-beta", "beta"),  # tag fora do padrão: ignorada
        rel_json("v0.3.0", "três", [asset("MUSentinel-v0.3.0-win64.zip", size=10, digest="sha256:ABC"),
                                     asset("MUSentinel-v0.3.0-win64.zip.sha256")]),
        rel_json("v0.2.9", "dois nove", pre=True),
        rel_json("v0.2.5", "dois cinco"),
        rel_json("v0.2.2", "atual"),
    ]
    r = updater.parse_releases(data, "0.2.2", REPO)
    assert r.version == "0.3.0"
    assert r.notes.index("Versão 0.3.0") < r.notes.index("Versão 0.2.5")
    assert "três" in r.notes and "dois cinco" in r.notes
    assert "atual" not in r.notes and "beta" not in r.notes and "rascunho" not in r.notes
    assert r.zip_url == "https://dl/MUSentinel-v0.3.0-win64.zip" and r.zip_size == 10
    assert r.sha256 == "abc" and r.sha256_url.endswith(".sha256")


def test_parse_nothing_newer():
    assert updater.parse_releases([rel_json("v0.2.2"), rel_json("v0.1.0")], "0.2.2", REPO) is None
    assert updater.parse_releases({"message": "x"}, "0.2.2", REPO) is None


def test_parse_release_without_zip():
    r = updater.parse_releases([rel_json("0.3.0")], "0.2.2", REPO)
    assert r.version == "0.3.0" and r.zip_url is None and r.sha256 is None


def test_check_ok_and_errors():
    url = updater.API.format(repo=REPO)
    ok = client_for({url: httpx.Response(200, json=[rel_json("v0.3.0")])})
    assert updater.check("0.2.2", REPO, ok).version == "0.3.0"
    assert updater.check("0.3.0", REPO, ok) is None
    for resp, word in ((httpx.Response(404), "não foi encontrado"), (httpx.Response(403), "limitou"),
                       (httpx.Response(500), "HTTP 500"), (httpx.ConnectError("x"), "sem conexão")):
        with pytest.raises(UpdateError, match=word):
            updater.check("0.2.2", REPO, client_for({url: resp}))


# ---------------------------------------------------------------------------------- download
def test_download_checks_and_extracts(tmp_path):
    seen = []
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=APP_ZIP)})
    root = updater.download(release(), tmp_path, progress=lambda g, t: seen.append((g, t)), client=c)
    assert (root / "MUSentinel.exe").read_bytes() == b"exe novo"
    assert (root / "_internal" / "lib.dll").exists()
    assert seen and seen[-1][0] == len(APP_ZIP)
    assert not (tmp_path / "v0.3.0" / "download.zip").exists()


def test_download_uses_sha_file_when_no_digest(tmp_path):
    sha = hashlib.sha256(APP_ZIP).hexdigest()
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=APP_ZIP),
                    "https://dl/app.zip.sha256": httpx.Response(200, text=f"{sha.upper()}  app.zip\n")})
    r = Release("0.3.0", "", "https://p", "https://dl/app.zip", len(APP_ZIP), None, "https://dl/app.zip.sha256")
    assert (updater.download(r, tmp_path, client=c) / "MUSentinel.exe").exists()


def test_download_refuses_bad_sha_and_missing_sha(tmp_path):
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=APP_ZIP)})
    with pytest.raises(UpdateError, match="não confere"):
        updater.download(release(sha="0" * 64), tmp_path, client=c)
    assert not (tmp_path / "v0.3.0" / "novo").exists()
    no_sha = Release("0.3.0", "", "https://p", "https://dl/app.zip", 0, None, None)
    with pytest.raises(UpdateError, match="SHA-256"):
        updater.download(no_sha, tmp_path, client=c)


def test_download_incomplete_cancel_and_http_error(tmp_path):
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=APP_ZIP)})
    with pytest.raises(UpdateError, match="incompleto"):
        updater.download(release(size=len(APP_ZIP) + 5), tmp_path, client=c)
    with pytest.raises(UpdateCancelled):
        updater.download(release(), tmp_path, cancel=lambda: True, client=c)
    with pytest.raises(UpdateError, match="HTTP 404"):
        updater.download(release(), tmp_path, client=client_for({}))


def test_download_rejects_path_escape(tmp_path):
    evil = make_zip({"MUSentinel/MUSentinel.exe": b"x", "MUSentinel/_internal/a": b"x", "../fora.txt": b"x"})
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=evil)})
    with pytest.raises(UpdateError, match="caminho inválido"):
        updater.download(release(evil), tmp_path, client=c)
    assert not (tmp_path / "v0.3.0" / "fora.txt").exists()


def test_download_requires_exe(tmp_path):
    z = make_zip({"MUSentinel/outra.txt": b"x"})
    c = client_for({"https://dl/app.zip": httpx.Response(200, content=z)})
    with pytest.raises(UpdateError, match="não tem o MUSentinel.exe"):
        updater.download(release(z), tmp_path, client=c)


# ---------------------------------------------------------------------------------- troca
def installed(tmp_path):
    t = tmp_path / "instalado"
    (t / "_internal").mkdir(parents=True)
    (t / "_internal" / "velha.dll").write_bytes(b"dll velha")
    (t / "MUSentinel.exe").write_bytes(b"exe velho")
    (t / "LEIA-ME.md").write_bytes(b"leia velho")
    (t / "portable.flag").write_bytes(b"")
    (t / "data").mkdir()
    (t / "data" / "config.yaml").write_text("nivel: 0", encoding="utf-8")
    return t


def staged(tmp_path):
    s = tmp_path / "novo"
    (s / "_internal").mkdir(parents=True)
    (s / "_internal" / "lib.dll").write_bytes(b"dll nova")
    (s / "MUSentinel.exe").write_bytes(b"exe novo")
    (s / "LEIA-ME.md").write_bytes(b"leia novo")
    (s / "NOVIDADES.md").write_bytes(b"novidades")
    return s


def test_swap_replaces_app_and_keeps_data(tmp_path):
    t, s = installed(tmp_path), staged(tmp_path)
    updater.swap(s, t, retry_s=0)
    assert (t / "MUSentinel.exe").read_bytes() == b"exe novo"
    assert (t / "_internal" / "lib.dll").exists() and not (t / "_internal" / "velha.dll").exists()
    assert (t / "LEIA-ME.md").read_bytes() == b"leia novo" and (t / "NOVIDADES.md").exists()
    assert (t / "portable.flag").exists() and (t / "data" / "config.yaml").read_text(encoding="utf-8") == "nivel: 0"
    assert not [p for p in t.iterdir() if updater.OLD_TAG in p.name]


def test_swap_rolls_back_on_error(tmp_path, monkeypatch):
    t, s = installed(tmp_path), staged(tmp_path)

    def boom(*a, **k):
        (t / "_internal").mkdir()  # cópia pela metade
        raise OSError("disco cheio")

    monkeypatch.setattr(updater.shutil, "copytree", boom)
    with pytest.raises(OSError):
        updater.swap(s, t, retry_s=0)
    assert (t / "MUSentinel.exe").read_bytes() == b"exe velho"
    assert (t / "_internal" / "velha.dll").read_bytes() == b"dll velha"
    assert not [p for p in t.iterdir() if updater.OLD_TAG in p.name]


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_finish_waits_swaps_and_reopens(tmp_path):
    t, s = installed(tmp_path), staged(tmp_path)
    started = []
    ok = updater.finish(s, t, dead_pid(), ["--minimizado"], wait_s=5, retry_s=0,
                        start=lambda args, cwd: started.append((args, cwd)))
    assert ok and (t / "MUSentinel.exe").read_bytes() == b"exe novo"
    assert started == [([str(t / "MUSentinel.exe"), "--minimizado"], t)]


def test_finish_gives_up_if_old_app_stays_open(tmp_path):
    import os

    t, s = installed(tmp_path), staged(tmp_path)
    started, msgs = [], []
    ok = updater.finish(s, t, os.getpid(), wait_s=0.2, retry_s=0,
                        start=lambda args, cwd: started.append(args), notify=msgs.append)
    assert not ok and started == [] and "não fechou" in msgs[0]
    assert (t / "MUSentinel.exe").read_bytes() == b"exe velho"


def test_finish_reopens_old_version_when_swap_fails(tmp_path, monkeypatch):
    t, s = installed(tmp_path), staged(tmp_path)
    monkeypatch.setattr(updater.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("bloqueado")))
    started, msgs = [], []
    ok = updater.finish(s, t, dead_pid(), wait_s=5, retry_s=0,
                        start=lambda args, cwd: started.append(args), notify=msgs.append)
    assert not ok and "versão anterior foi mantida" in msgs[0]
    assert started == [[str(t / "MUSentinel.exe")]]
    assert (t / "MUSentinel.exe").read_bytes() == b"exe velho"


def test_cleanup_removes_leftovers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    t = installed(tmp_path)
    (t / "_internal.antigo-20261101").mkdir()
    (t / "MUSentinel.exe.antigo-20261101").write_bytes(b"x")
    (updater.update_dir() / "v0.3.0").mkdir(parents=True)
    updater.cleanup(t)
    assert not [p for p in t.iterdir() if updater.OLD_TAG in p.name]
    assert not updater.update_dir().exists()
    assert (t / "MUSentinel.exe").exists() and (t / "data").exists()


def test_main_routes_finish_flag(monkeypatch):
    from musentinel import main as main_mod

    got = []
    monkeypatch.setattr(updater, "finish_main", lambda argv: got.append(argv) or 7)
    assert main_mod.main([updater.FINISH_FLAG, "C:/app", "123", "--minimizado"]) == 7
    assert got == [["C:/app", "123", "--minimizado"]]


def test_finish_main_rejects_bad_args():
    assert updater.finish_main(["C:/app"]) == 2
    assert updater.finish_main(["C:/app", "abc"]) == 2


def test_config_keeps_update_choices():
    c = Config()
    assert c.check_updates and c.skipped_version == ""
    c.check_updates, c.skipped_version = False, "0.3.0"
    y = c.to_yaml()
    assert "procurar_atualizacoes: false" in y and "versao_pulada: 0.3.0" in y
    back = Config.from_yaml(y)
    assert not back.check_updates and back.skipped_version == "0.3.0"


def test_repo_placeholder_disables_check(monkeypatch):
    monkeypatch.setattr(updater, "REPO", "OWNER/mu-sentinel")
    assert not updater.enabled()
    monkeypatch.setattr(updater, "REPO", REPO)
    assert updater.enabled()
