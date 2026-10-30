# MU Sentinel — LEIA-ME

Monitor das janelas do **MU Online (Webzen)**: avisa no seu celular (Telegram ou WhatsApp) e no
Windows quando um personagem morre, desconecta, a janela trava ou fecha, ou a caça para.

> **Aviso de risco — leia antes de usar.** A política operacional da Webzen proíbe macros e programas
> não oficiais e prevê banimento permanente, inclusive de todas as contas ligadas à mesma pessoa.
> Este app é um programa não oficial. **O uso é por sua conta e risco.**
>
> O MU Sentinel só **observa**: olha a imagem das janelas e informações do Windows. Ele **não envia
> teclas** ao jogo, não lê a memória do jogo, não mexe nos arquivos do jogo e **nunca pede nem guarda a
> senha do jogo**.

## Anti-cheat do jogo (GameGuard)

O MU roda junto com o **nProtect GameGuard**. Nos testes, poucos segundos depois de o MU Sentinel abrir,
o GameGuard passa a esconder dele de qual programa são as janelas do jogo. O MU Sentinel **não tenta
contornar** essa proteção: ele mostra o aviso **"Monitoramento limitado pelo anti-cheat"** e continua só
pela imagem da janela. Nesse modo:

- **continua detectando:** morte, caça parada, Helper parado, HP baixo, janela travada, janela fechada e
  queda da internet deste PC;
- **deixa de detectar:** desconexão do servidor do jogo com a internet do PC funcionando.

O GameGuard pode registrar programas a que ele reage; não há como saber se isso é informado à Webzen.
Mais um motivo para usar só sabendo do risco.

## Requisitos

- Windows 10 ou 11, 64 bits. Não precisa instalar Python nem mais nada.
- MU Online aberto em janela. Perfis prontos para a janela de **800x600** (escala do Windows em 100%)
  e **1280x960** (800x600 com escala em 125%). Outro tamanho: use *Arquivo → Calibração*.

## Instalar

1. Descompacte o `.zip` numa pasta sua (ex.: `C:\Jogos\MUSentinel`). Não precisa ser em Arquivos de Programas.
2. Abra **MUSentinel.exe**.
3. Se o Windows mostrar **"O Windows protegeu o computador"** (SmartScreen): clique em
   **Mais informações → Executar assim mesmo**. Isso aparece porque o app não tem assinatura digital.

Não precisa rodar como administrador.

## Assistente (primeira vez)

1. **Janelas do jogo:** abra os clients (até 4) e dê um nome a cada slot (ex.: "Elf Kanturu").
2. **Perfil de resolução:** mostra se a sua janela já tem perfil. Se um colega com a mesma resolução
   já calibrou, dá para **importar** o perfil dele (`.json`, sem senhas nem chaves).
3. **Alertas no celular:** Telegram (recomendado) e/ou WhatsApp. Veja abaixo.
4. **Nível:** só existe o 0 (Observador).
5. **Iniciar com o Windows:** o app abre sozinho, minimizado na bandeja.

Dá para refazer depois em *Arquivo → Assistente de configuração*.

## Alertas no Telegram (recomendado, grátis)

1. No Telegram, abra o **@BotFather** (https://t.me/BotFather) e mande `/newbot`.
   Escolha um nome (ex.: *MU Alertas*) e um usuário que termine em `bot`.
2. Ele responde com um **token** (algo como `123456789:AA…`). No MU Sentinel, *Configurações → Telegram*:
   cole o token e clique em **Verificar**.
3. Abra o link do seu bot que aparece no app e toque em **Iniciar**.
4. Clique em **Buscar conversas**, deixe marcado quem recebe e clique em **Testar**.

Nos alertas críticos vai junto o print da janela. Outra pessoa também pode receber os alertas do seu PC:
ela abre o link do seu bot, toca em Iniciar, e você busca as conversas de novo. O token fica guardado no
Gerenciador de Credenciais do Windows, não em arquivo.

## Alertas no WhatsApp (CallMeBot)

O CallMeBot às vezes fica **sem vagas** ("The bot is currently full") e não entrega a chave; nesse caso
use o Telegram e tente de novo em alguns dias. Quando houver vaga:

1. No celular que vai receber, salve o contato do bot. O número muda de tempos em tempos: confira o atual
   em https://www.callmebot.com/blog/free-api-whatsapp-messages/
2. Mande para ele pelo WhatsApp: `I allow callmebot to send me messages`
3. O bot responde com a sua **apikey**.
4. *Configurações → WhatsApp → Adicionar*: nome, telefone com DDI e DDD (ex.: `+55 11 99999-0000`) e a
   apikey. Clique em **Testar**.

## No dia a dia

- Fechar a janela do app **não** desliga o monitor: ele fica no ícone perto do relógio.
  Para sair: botão direito no ícone → **Sair**.
- Alerta crítico (morte, desconexão, janela travada ou fechada) repete a cada 5 min (até 3 vezes)
  até você clicar em **OK, vi o alerta** no painel.
- **Pausar alertas** no topo do painel (30 min, 1 h, 2 h ou até retomar).
- Se o mapa/HP aparecer como ILEGÍVEL: algum menu está por cima do HUD (inventário, Helper…).
  Isso nunca gera alerta crítico.
- Deixe a janela do jogo **não minimizada** (pode ficar atrás de outras janelas).

## Energia

Se o PC suspender, o jogo e os alertas param juntos. O app impede a suspensão por tempo ocioso
enquanto está aberto. Em **notebooks**, fechar a tampa ou apagar a tela pode colocar o Windows em
espera mesmo assim: o painel avisa quando for o seu caso. Em *Configurações → Monitor* dá para
**manter a tela ligada**.

## Onde ficam os dados

`%APPDATA%\MUSentinel\` — configuração (`config.yaml`), perfis, histórico de eventos e logs.
Para usar tudo dentro da própria pasta do app (pendrive), crie um arquivo vazio chamado
`portable.flag` ao lado do `MUSentinel.exe`.

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| "Monitoramento limitado pelo anti-cheat" | É o GameGuard (veja acima). O app segue pela imagem; não há o que configurar |
| "sem perfil para LxA" no card | A janela tem um tamanho sem perfil: deixe o client em 800x600 ou calibre em *Arquivo → Calibração* |
| Telegram: "token inválido" | Copie de novo o token inteiro que o @BotFather mandou |
| Telegram: "Buscar conversas" não acha ninguém | Abra o link do bot e toque em Iniciar (vale por 24 h), depois busque de novo |
| WhatsApp: teste falha | Confira o número com DDI, a apikey e se o número do bot ainda é o do site |
| Nenhuma janela encontrada | O título da janela precisa ser "MU" e o processo `main.exe` (ajustável em *Configurações → Monitor*) |
| Alertas não chegam com o PC em espera | Veja a seção Energia |
