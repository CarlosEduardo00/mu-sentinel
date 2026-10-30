# MU Sentinel

App desktop para Windows que monitora janelas do MU Online (Webzen), detecta morte,
desconexão, travamento e caça parada, e avisa pelo WhatsApp.

> A política operacional da Webzen proíbe macros e programas não oficiais e prevê banimento
> permanente, inclusive de todas as contas ligadas à mesma pessoa. Os níveis 1 a 4 enviam teclas
> ao jogo. Use por sua conta e risco.

**Estado atual: só nível 0 (Observador), por decisão do dono do projeto.** O app só lê a imagem das
janelas e informações do Windows; **nunca** envia teclas ao jogo. As ações que enviam teclas (níveis 1 a 4)
não serão feitas, para não correr risco de banimento.

## Abrir o app

```powershell
.\.venv\Scripts\pythonw.exe -m musentinel          # painel + bandeja
.\.venv\Scripts\pythonw.exe -m musentinel --minimizado
```

Fechar a janela só esconde o painel: o monitor continua na bandeja (botão direito no ícone → Sair).
Só abre uma instância por vez.

Na primeira vez abre o **assistente** (janelas, perfil, alertas no celular, nível, iniciar com o Windows);
para refazer: *Arquivo → Assistente de configuração* ou `--assistente`.

## Gerar o executável para os amigos

> **GameGuard:** o nProtect GameGuard que roda com o MU restringe o `MUSentinel.exe` empacotado: poucos
> segundos depois de abrir, o Windows deixa de informar de qual processo são as janelas do jogo. O app
> **não tenta contornar** isso: avisa "MONITORAMENTO LIMITADO PELO ANTI-CHEAT" e segue só pela janela
> (imagem, HUD, janela travada/fechada, queda da internet do PC), sem checar a conexão TCP com o
> servidor do jogo. Rodando pelo código-fonte (`python.exe`) a restrição não apareceu nos testes.
> O zip é distribuído sem assinatura e o uso é por conta e risco de cada um (ver `LEIA-ME.md`).

```powershell
.\build.ps1
```

Cria um venv limpo, roda os testes, gera `dist\MUSentinel\` (PyInstaller onedir, sem UPX), faz o
smoke test do `.exe` com dados zerados e compacta em `MUSentinel-vX.Y.Z-win64.zip`. O zip leva o
`LEIA-ME.md` com o passo a passo para quem vai usar. A versão vem do `pyproject.toml`.
Assinatura de código opcional: variável `MUSENTINEL_SIGN_CMD` (ver o topo do `build.ps1`).
Antes de distribuir, teste o zip numa máquina/VM sem Python.

## Alertas no celular

### Telegram (recomendado)

Bot API oficial do Telegram, grátis e sem fila de espera. Em *Configurações → Telegram*: criar um bot no
@BotFather (`/newbot`), colar o token e **Verificar**, tocar em **Iniciar** no link do bot, **Buscar
conversas** e **Testar**. Nos alertas críticos vai junto o print da janela. O token fica no Gerenciador
de Credenciais.

**Pedidos pelo celular** (`core/remote.py`, `TelegramCommandListener`): `/status`, `/print N`,
`/inventario N`, `/personagem N`, `/cacada N`, `/loja`, `/ok`, `/pausar M`, `/retomar`, também como botões
no bot. Só conversas da lista do app são atendidas; mensagens enviadas com o app fechado são ignoradas.
Nada disso mexe no jogo: os comandos leem a imagem e controlam os alertas do próprio app.

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

### WhatsApp (CallMeBot)

Os alertas saem pelo **CallMeBot** (grátis, sem servidor). Às vezes o CallMeBot fica sem vagas
("The bot is currently full") e não entrega a chave; nesse caso use o Telegram até abrir vaga. A chave do CallMeBot é ligada ao
número que fez a ativação, então **cada pessoa ativa o próprio número** e cadastra em
*Arquivo → Configurações → WhatsApp* (ou no link amarelo do painel):

1. No celular que vai receber, salve o contato do bot. O número do bot muda de tempos em tempos:
   confira o atual em https://www.callmebot.com/blog/free-api-whatsapp-messages/
2. Mande para ele pelo WhatsApp: `I allow callmebot to send me messages`
3. O bot responde com a **apikey**. No app: **Adicionar** → nome, telefone com DDI (`+55 11 99999-0000`) e a chave.
4. **Testar**. A mensagem chega em alguns segundos.

Dá para cadastrar vários números (você e um amigo recebendo os mesmos alertas) e desligar
cada um quando quiser. Passando o app para um amigo, ele cadastra o número **dele** no PC **dele**.
As chaves ficam no Gerenciador de Credenciais do Windows (nunca no `config.yaml`, no log ou em export).

## Estados e alertas

| Estado | Quando | Alerta |
| --- | --- | --- |
| CAÇANDO | EXP ou Hunting Time subindo | — |
| ONLINE | HUD legível, ainda sem sinal de caça | — |
| PARADO | sem EXP há 5 min (vindo de CAÇANDO) | aviso, 1 vez |
| MORTO | HP 0 em 2 leituras, ou foi do spot para uma cidade sem você mexer no PC | **crítico** |
| DESCONECTADO | a conexão do jogo com o servidor fechou, ou a internet do PC caiu | **crítico** |
| TRAVADO | janela sem responder por 10 s ou imagem parada por 30 s | **crítico** |
| FECHADO | o processo do jogo sumiu | **crítico** |
| ILEGÍVEL | menu/loading/janela por cima do HUD | aviso só após 2 min, **nunca** crítico |

Também avisa: Helper parou (Hunting Time parado), HP abaixo de 30%.

- Um estado novo só vale após 2 ciclos seguidos iguais (ciclo de 2 s).
- Crítico repete a cada 5 min (no máximo 3 vezes no CallMeBot) até você clicar **OK, vi o alerta**.
- Mesmo alerta do mesmo slot: no máximo 1× a cada 5 min. Vários alertas no mesmo ciclo saem numa mensagem só.
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

## Preparar o ambiente (desenvolvimento)

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

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

Os prints da suíte guardam só as regiões do HUD (o resto fica preto) para caber no git;
os originais completos ficam em `%APPDATA%\MUSentinel\captures\originais\`.

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
- **1280x960** — client em 800x600 com a escala do Windows em 125%.

O HUD do MU não escala proporcionalmente (orbes e barras ficam presos às bordas), então outro
tamanho precisa de calibração própria: o painel avisa "sem perfil para LxA".
