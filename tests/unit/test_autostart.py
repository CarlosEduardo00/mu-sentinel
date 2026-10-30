"""Iniciar com o Windows: chave Run do HKCU (usa um nome de teste para não mexer na real)."""

from musentinel.core import autostart


def test_enable_disable(monkeypatch):
    monkeypatch.setattr(autostart, "VALUE", "MUSentinel_TESTE_PYTEST")
    autostart.set_enabled(False)
    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    try:
        assert autostart.is_enabled()
        cmd = autostart.current_command()
        assert "--minimizado" in cmd and "musentinel" in cmd.lower()
    finally:
        autostart.set_enabled(False)
    assert not autostart.is_enabled()
