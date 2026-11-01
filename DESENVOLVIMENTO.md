# MU Sentinel — desenvolvimento

Detalhes técnicos para quem quer mexer no código. Para baixar e usar o app, veja o [README](README.md).

App desktop para Windows (Python 3.12 + PySide6) que monitora janelas do MU Online (Webzen) só pela imagem
e por informações do Windows, e avisa pelo Telegram, WhatsApp (CallMeBot) e notificação do Windows.

**Só nível 0 (Observador), por decisão do dono do projeto.** O app nunca envia teclas ao jogo, não lê
memória, não injeta nada e não mexe nos arquivos do jogo. As ações que enviariam teclas (níveis 1 a 4) não
serão feitas, para não correr risco de banimento.

## Preparar o ambiente

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Testes automáticos

[![Testes](https://github.com/CarlosEduardo00/mu-sentinel/actions/workflows/testes.yml/badge.svg)](https://github.com/CarlosEduardo00/mu-sentinel/actions/workflows/testes.yml)

`.\.venv\Scripts\python.exe -m pytest` roda tudo no PC. No GitHub, `.github/workflows/testes.yml` roda a mesma
suíte no Windows com Python 3.12 a cada envio para a `main` e em pull requests (a tela é testada sem abrir
janela, com `QT_QPA_PLATFORM=offscreen`).

## Abrir pelo código-fonte

```powershell
.\.venv\Scripts\pythonw.exe -m musentinel          # painel + bandeja
.\.venv\Scripts\pythonw.exe -m musentinel --minimizado
```

Fechar a janela só esconde o painel: o monitor continua na bandeja (botão direito no ícone → Sair).
Só abre uma instância por vez. Na primeira vez abre o **assistente**; para refazer:
*Arquivo → Assistente de configuração* ou `--assistente`.

## Gerar o executável

> **GameGuard:** o nProtect GameGuard que roda com o MU restringe o `MUSentinel.exe` empacotado: poucos
> segundos depois de abrir, o Windows deixa de informar de qual processo são as janelas do jogo. O app
> **não tenta contornar** isso: avisa "MONITORAMENTO LIMITADO PELO ANTI-CHEAT" e segue só pela janela
> (imagem, HUD, janela travada/fechada, queda da internet do PC), sem checar a conexão TCP com o
> servidor do jogo. Rodando pelo código-fonte (`python.exe`) a restrição não apareceu nos testes.

```powershell
.\build.ps1
```

Cria um venv limpo, roda os testes, gera `dist\MUSentinel\` (PyInstaller onedir, sem UPX), faz o
smoke test do `.exe` com dados zerados e compacta em `MUSentinel-vX.Y.Z-win64.zip`. O zip leva o
`LEIA-ME.md` com o passo a passo para quem vai usar. A versão vem de `src\musentinel\_version.py`.
Assinatura de código opcional: variável `MUSENTINEL_SIGN_CMD` (ver o topo do `build.ps1`).

## Lançar uma versão (atualização automática)

1. Mude o número em `src\musentinel\_version.py` e escreva a seção `## [X.Y.Z] - AAAA-MM-DD` no topo do
   `CHANGELOG.md` (é o texto que aparece no aviso de atualização).
2. Faça o commit.
3. Rode `powershell -NoProfile -ExecutionPolicy Bypass -File .\lancar.ps1` (com `-Rascunho` para revisar a
   release antes de publicar).

O script roda o `build.ps1` completo, cria a tag `vX.Y.Z`, envia para o GitHub e publica a release com:

- `MUSentinel-vX.Y.Z-win64.zip`: o arquivo que o app baixa para se atualizar;
- `MUSentinel-vX.Y.Z-win64.zip.sha256`: a soma de conferência;
- `MUSentinel-win64.zip`: cópia com nome fixo, para o botão do README
  (`releases/latest/download/MUSentinel-win64.zip` sempre baixa a mais nova).

Precisa do `gh` logado (`gh auth login`, uma vez).

Como o app se atualiza (`core/updater.py`): ao abrir e a cada 12 h ele consulta
`api.github.com/repos/CarlosEduardo00/mu-sentinel/releases`. Se houver versão mais nova (rascunhos e
pré-releases ficam de fora), mostra as novidades de todas as versões no meio. "Atualizar agora" baixa o zip
para `%LOCALAPPDATA%\MUSentinel\atualizacao`, confere tamanho e SHA-256 (o `digest` do GitHub ou o `.sha256`
da release) e abre o `MUSentinel.exe` novo com `--concluir-atualizacao`. Ele espera o app antigo fechar,
troca o `MUSentinel.exe` e a pasta `_internal`, volta tudo se algo falhar e reabre o app. `config.yaml`,
`portable.flag` e `data\` não são tocados. Log da troca: `logs\atualizacao.log`.

## Alertas no celular

### Telegram

Bot API oficial do Telegram, grátis e sem fila de espera. Em *Configurações → Telegram*: criar um bot no
@BotFather (`/newbot`), colar o token e **Verificar**, tocar em **Iniciar** no link do bot, **Buscar
conversas** e **Testar**. Nos alertas críticos vai junto o print da janela. O token fica no Gerenciador
de Credenciais.

**Pedidos pelo celular** (`core/remote.py`, `TelegramCommandListener`): `/status`, `/print N`,
`/inventario N`, `/personagem N`, `/cacada N`, `/loja`, `/ok`, `/pausar M`, `/retomar`, também como botões
no bot. Só conversas da lista do app são atendidas; mensagens enviadas com o app fechado são ignoradas.
Nada disso mexe no jogo: os comandos leem a imagem e controlam os alertas do próprio app.

### WhatsApp (CallMeBot)

Grátis e sem servidor, mas às vezes fica sem vagas ("The bot is currently full"). A chave do CallMeBot é
ligada ao número que fez a ativação, então **cada pessoa ativa o próprio número** e cadastra em
*Configurações → WhatsApp*. Dá para cadastrar vários números e desligar cada um. As chaves ficam no
Gerenciador de Credenciais do Windows (nunca no `config.yaml`, no log ou em export).

## Calibração automática e consumo

- `core/perception/autocal.py`: o OCR da tela inteira acha mapa, coordenadas, HP, EXP (também quando vem em
  dois pedaços) e o tempo de caça; vira gabarito para criar/esticar ROIs e ensinar o leitor de glifos
  (`training.learn_sample`). Dispara sozinho (tamanho sem perfil; HP/EXP ilegível ~30 s, no máx. 1×/10 min por
  janela, na thread dos painéis) ou pelo botão **Calibrar** / *Arquivo → Calibrar todas*. Salva o perfil do
  usuário daquele tamanho e recarrega os leitores.
- Tempo de caça é lido na posição do Instant Hunting Log de cada janela (`HudReader.read_field_at`).
- Escala dos painéis medida pela distância título → textos fixos (`perception/panels.LANDMARKS`): 1024x768 com
  escala de 125% dá ~1,5x.
- Consumo (i5 16 núcleos, 3 janelas 1280x960): OpenBLAS em 1 thread (o import do numpy reservava ~490 MB),
  OCR em 2 threads sem *spinning*, OpenCV em 1 thread, prioridade do processo abaixo do normal, WGC a 1 quadro/s,
  contador da Loja só faz OCR quando a imagem muda. Medido: de ~308% de CPU e 723 MB privados para ~15% e 234 MB.

## Painéis abertos no jogo e Loja

O usuário deixa abertos Personagem (C), Inventário (I), Instant Hunting Log e, na janela chamada **Loja**,
o Gremory Case na aba Personal Shop. `core/perception/panels.py` acha cada painel pelo título (OCR da tela
inteira, em qualquer posição; escala pela altura do texto) e lê: atributos e pontos do C; grade 8x8 e Zen do
inventário (nomes dos itens não aparecem, só ícones); tempo, EXP/s e abates da caçada; contador `N / 150` e
aba selecionada (pela cor) do Gremory Case. `core/panels.py` confere a cada 30 s (Loja: 10 s), sem OCR, se o
título continua no lugar; procura de novo na tela inteira quando some ou a cada 5 min. Avisos: painel que
fechou sozinho (com o usuário longe do PC), Gremory fora da aba Personal Shop, e **VENDA NA LOJA** quando o
contador sobe (confirmado em 2 leituras; retirada de itens só reajusta a base). A Loja não tem alertas de caça
parada nem a regra de morte por ida à cidade.

## Estados e alertas

| Estado | Quando | Alerta |
| --- | --- | --- |
| CAÇANDO | EXP ou Hunting Time subindo | — |
| ONLINE | HUD legível, ainda sem sinal de caça | — |
| PARADO | sem EXP há 5 min (vindo de CAÇANDO) | aviso, 1 vez |
| MORTO | HP 0 em 2 leituras (com o HP máximo de sempre), ou foi do spot para uma cidade sem você mexer no PC | **crítico** |
| DESCONECTADO | a conexão do jogo com o servidor fechou, ou a internet do PC caiu (trocar de servidor não conta: espera até 90 s o jogo voltar) | **crítico** |
| TRAVADO | o Windows marcou a janela como "Não respondendo" por 30 s (imagem parada **não** conta) | **crítico** |
| FECHADO | o processo do jogo sumiu | **crítico** |
| ILEGÍVEL | menu/loading/janela por cima do HUD | aviso só após 2 min com você longe do PC, **nunca** crítico |

Também avisa: Helper parou (Hunting Time parado; com você mexendo no PC, espera você sair), HP abaixo de
30% (no máximo 1 a cada 15 min). A Loja não tem alerta de morte, caça parada, Helper nem HP baixo (fica
parada na cidade de propósito); desconexão, travamento e fechamento valem para ela também.

- Um estado novo só vale após 2 ciclos seguidos iguais (ciclo de 2 s).
- Leituras erradas do HUD não viram alerta: HP com máximo diferente do de sempre, Hunting Time que pula
  mais do que o tempo que passou e contador do Gremory que cai uma vez só são ignorados.
- Número maior que a área de leitura (HP passou de 999, EXP ganhou um dígito): se o texto encosta na
  borda, o leitor amplia a área um dígito por vez até ver o número inteiro (só aceita dígitos colados
  no número) e salva a área nova no perfil. Se não couber, a leitura é "ilegível", nunca pela metade.
- Uma mensagem por acontecimento (e outra quando resolve). Lembrete opcional (`alertas.lembrete_critico`):
  "LEMBRETE: X continua" a cada 5 min, sem repetir o print, até o `/ok` (Telegram) ou **OK, vi o alerta**;
  no máximo 3 se só houver CallMeBot.
- Mesmo alerta do mesmo slot: no máximo 1× a cada 5 min. Vários alertas no mesmo ciclo saem numa mensagem só.
- O mesmo alerta crítico 3× em 30 min: a 3ª mensagem diz que está instável e, nos 30 min seguintes, ele
  aparece só no app.
- Erro interno: cada erro diferente vai ao celular uma vez só (o resto fica no log).
- 2+ slots desconectados juntos (ou internet fora): **um** alerta só, dizendo se a internet deste PC caiu.
- Horário silencioso (opcional) vale só para o WhatsApp; críticos passam por padrão.
- Morte "trava": renascer na cidade continua MORTO até voltar a ganhar EXP ou sair da cidade.

Exemplo:

```text
[CRÍTICO] MORTE - Slot 2 "Elf Kanturu" (Kanturu 213,39)
12:14 · HP 0/807 · estava CAÇANDO há 18 min · nível 0
```

## Energia (importante em notebook)

Se o Windows suspender, o jogo e o app param juntos e nenhum alerta sai. O app impede a
suspensão por tempo ocioso enquanto roda. Em notebooks com **Modern Standby**, apagar a tela
ou fechar a tampa coloca o Windows em espera mesmo assim: o painel avisa. Ative
*manter a tela ligada* em Configurações → Monitor, ou deixe "Desligar a tela" em Nunca.

## Dados

`%APPDATA%\MUSentinel\` (ou `data\` ao lado do .exe com `portable.flag`):
`config.yaml` (sem segredos) · `profiles\*.json` · `events.db` (histórico, aba Eventos, exporta CSV) ·
`logs\musentinel.log` (10 MB × 5, telefones mascarados) · `captures\prints\` (botão Print).

Conexões que o app faz: Telegram e CallMeBot (se ligados) e o GitHub para procurar atualizações
(desliga em *Configurações → Monitor*). Nenhum dado do usuário vai para o GitHub.

## Ferramentas de leitura (Fase 0)

| Comando | Para quê |
| --- | --- |
| `.\.venv\Scripts\python.exe -m musentinel.tools.autolabel --minutos 60` | **Coleta e rotula sozinho** enquanto você joga (ver abaixo); cada resolução tem a sua suíte |
| `.\.venv\Scripts\python.exe -m musentinel.tools.contact_sheet` | Folha-resumo dos gabaritos (recorte + valor) para conferir de olho |
| `.\.venv\Scripts\python.exe -m musentinel.gui.calibration` | Tela de calibração: captura a janela, desenha a região de cada campo, mostra a leitura ao vivo, ensina valores, salva/exporta/importa o perfil |
| `.\.venv\Scripts\python.exe -m musentinel.tools.collect --intervalo 15` | Grava prints de todas as janelas do MU a cada 15 s (Ctrl+C para parar) |
| `.\.venv\Scripts\python.exe -m musentinel.tools.label` | Rotulador: confere/corrige a leitura de cada print, monta a suíte de testes e ensina o perfil |
| `.\.venv\Scripts\python.exe -m musentinel.tools.accuracy_report --tamanho 800x600` | Relatório de acurácia (aprende com 1/5 dos prints, mede nos outros 4/5) |
| `.\.venv\Scripts\python.exe -m musentinel.tools.capture_check --minutos 3 --apagar-monitor` | Testa a captura com janela coberta e monitor apagado |
| `.\.venv\Scripts\python.exe -m musentinel.tools.seed_profile` | Regera o perfil-semente que vai junto com o app |
| `.\.venv\Scripts\python.exe -m pytest` | Testes automáticos |

### Rotulagem automática

Ninguém precisa digitar 200 valores. O `autolabel` captura as janelas e lê cada número
por dois métodos independentes — o leitor por template do app e o OCR em duas escalas.
Um campo vira gabarito quando os dois dão **exatamente** o mesmo valor, ou quando só o OCR
leu e o valor é coerente com a leitura anterior (Hunting Time avançou o mesmo que o
relógio; HP máximo igual; EXP não caiu). Se os dois leem valores diferentes, o print vai
para `%APPDATA%\MUSentinel\captures\revisar\` — o único caso que pede olho humano
(dá para abrir no rotulador manual com `--pasta`).

Os prints da suíte guardam só as regiões do HUD (o resto fica preto) para caber no git e não mostrar
nomes de personagens; os originais completos ficam em `%APPDATA%\MUSentinel\captures\originais\`.
Prints de painéis inteiros (`tests/fixtures/panels_800x600`) vão com os nomes tapados à mão.

Morte, menu aberto e loading quase não aparecem numa coleta normal; por isso o relatório
também testa **HUD coberto** com casos sintéticos (campo inteiro ou metade coberto por
janela escura/clara): o leitor nunca pode afirmar um valor errado nesses casos.

### No rotulador manual (opcional)

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

O perfil é por **tamanho real** da área da janela. O app já vem com dois:

- **800x600** — client em 800x600 com a escala do Windows em 100%;
- **1280x960** — janela de 1280x960 de verdade (ex.: jogo em 1024x768 com a escala do Windows em 125%).

O HUD do MU não escala proporcionalmente (orbes e barras ficam presos às bordas), então outro
tamanho precisa de calibração própria. O app calibra sozinho; o painel avisa "sem perfil para LxA" enquanto isso.

## Segurança do repositório

- Segredos (token do Telegram, chaves do CallMeBot) só no Gerenciador de Credenciais do Windows
  (`core/secrets.py`); nunca em YAML, log, export ou nos testes (os testes usam token e telefones falsos).
- Logs mascaram telefones e tokens (`core/logsetup.py`).
- Antes de commitar print novo, confira que os nomes de personagens estão tapados.
