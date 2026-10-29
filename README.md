# MU Sentinel

App desktop para Windows que monitora janelas do MU Online (Webzen), detecta morte,
desconexão, travamento e caça parada, e avisa pelo WhatsApp.

> A política operacional da Webzen proíbe macros e programas não oficiais e prevê banimento
> permanente, inclusive de todas as contas ligadas à mesma pessoa. Os níveis 1 a 4 enviam teclas
> ao jogo. Use por sua conta e risco.

**Estado atual: Fase 0 — leitura da tela** (captura, calibração e percepção). Ainda não há alertas.

## Preparar o ambiente (desenvolvimento)

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Ferramentas da Fase 0

| Comando | Para quê |
| --- | --- |
| `.\.venv\Scripts\python.exe -m musentinel.gui.calibration` | Tela de calibração: captura a janela, desenha a região de cada campo, mostra a leitura ao vivo, ensina valores, salva/exporta/importa o perfil |
| `.\.venv\Scripts\python.exe -m musentinel.tools.collect --intervalo 15` | Grava prints de todas as janelas do MU a cada 15 s (Ctrl+C para parar) |
| `.\.venv\Scripts\python.exe -m musentinel.tools.label` | Rotulador: confere/corrige a leitura de cada print, monta a suíte de testes e ensina o perfil |
| `.\.venv\Scripts\python.exe -m musentinel.tools.accuracy_report` | Relatório de acurácia (aprende com 1/5 dos prints, mede nos outros 4/5) |
| `.\.venv\Scripts\python.exe -m musentinel.tools.capture_check --minutos 3 --apagar-monitor` | Testa a captura com janela coberta e monitor apagado |
| `.\.venv\Scripts\python.exe -m musentinel.tools.seed_profile` | Regera o perfil-semente que vai junto com o app |
| `.\.venv\Scripts\python.exe -m pytest` | Testes automáticos |

### No rotulador

- Cada campo vem preenchido com o que o app leu; corrija só o que estiver errado e aperte **Enter**.
- `?` = ilegível (menu por cima, loading…) · `-` = ausente (painel Instant Hunting Log fechado).
- O print vai para `tests/fixtures/screens/<cena>/` e o perfil aprende na hora — os próximos já vêm mais certos.
- Ctrl+→ pula · Ctrl+← volta · Ctrl+Del descarta (move para `_descartados`, não apaga).

## Como funciona a leitura

- **Captura:** Windows Graphics Capture (funciona com a janela coberta e com o jogo rodando como
  administrador). Reserva: `PrintWindow`, que só funciona se o app também rodar como administrador.
  Janela minimizada não renderiza: é detectada e avisada.
- **Números do HUD** (HP, coordenadas, EXP, Hunting Time): template matching sobre a "tinta"
  (pixels claros e pouco saturados). Os modelos de cada caractere são aprendidos de exemplos
  rotulados. Se sobrar tinta sem caractere reconhecido, a leitura vira **ilegível** — nunca um
  número com um dígito a menos.
- **Nome do mapa:** comparação com a imagem de cada mapa já rotulado; mapa novo cai no OCR
  (RapidOCR) e é casado com a lista de mapas conhecidos.
- **Perfil:** `%APPDATA%\MUSentinel\profiles\<largura>x<altura>.json` (regiões + fontes
  aprendidas, sem segredos). Com `portable.flag` ao lado do .exe, usa `data\` na própria pasta.

## Resolução

A janela do client em "800x600" ocupa **1280x960 pixels reais** nesta máquina por causa da escala
de 125% do Windows. O perfil é por tamanho real da área da janela; outra escala do Windows = outro
perfil (a calibração detecta e oferece criar).
