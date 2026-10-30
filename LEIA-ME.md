# MU Sentinel — LEIA-ME

Monitor das janelas do **MU Online (Webzen)**: avisa no seu WhatsApp e no Windows quando um
personagem morre, desconecta, a janela trava ou fecha, ou a caça para.

> **Aviso de risco:** A política operacional da Webzen proíbe macros e programas não oficiais e prevê
> banimento permanente, inclusive de todas as contas ligadas à mesma pessoa. Os níveis 1 a 4 enviam
> teclas ao jogo. Use por sua conta e risco.
>
> Esta versão funciona só no **nível 0 (Observador)**: o app apenas olha a imagem das janelas e
> informações do Windows. Não envia teclas, não lê a memória do jogo, não mexe nos arquivos do jogo
> e **nunca pede nem guarda a senha do jogo**.

## Requisitos

- Windows 10 ou 11, 64 bits. Não precisa instalar Python nem mais nada.
- MU Online aberto em janela. Perfis prontos para a janela de **800x600** (escala do Windows em 100%)
  e **1280x960** (800x600 com escala em 125%). Outro tamanho: use *Arquivo → Calibração*.

## Instalar

1. Descompacte o `.zip` numa pasta sua (ex.: `C:\Jogos\MUSentinel`). Não precisa ser em Arquivos de Programas.
2. Abra **MUSentinel.exe**.
3. Se o Windows mostrar **"O Windows protegeu o computador"** (SmartScreen): clique em
   **Mais informações → Executar assim mesmo**. Isso aparece porque o app não tem assinatura paga.

Não precisa rodar como administrador.

## Assistente (primeira vez)

1. **Janelas do jogo:** abra os clients (até 4) e dê um nome a cada slot (ex.: "Elf Kanturu").
2. **Perfil de resolução:** mostra se a sua janela já tem perfil. Se um colega com a mesma resolução
   já calibrou, dá para **importar** o perfil dele (`.json`, sem senhas nem chaves).
3. **WhatsApp:** cadastre o seu número (veja abaixo) e clique em **Testar**.
4. **Nível de risco:** fica no 0 (Observador).
5. **Iniciar com o Windows:** o app abre sozinho, minimizado na bandeja.

Dá para refazer depois em *Arquivo → Assistente de configuração*.

## Ativar o WhatsApp (CallMeBot, grátis)

Cada pessoa ativa o **próprio número** uma vez:

1. No celular que vai receber os alertas, salve o contato do bot do CallMeBot. O número do bot muda de
   tempos em tempos: **confira o número atual no site oficial**:
   https://www.callmebot.com/blog/free-api-whatsapp-messages/
2. Mande para esse contato, pelo WhatsApp: `I allow callmebot to send me messages`
3. O bot responde com a sua **apikey**.
4. No MU Sentinel: *Configurações → WhatsApp → Adicionar*: seu nome, telefone com DDI e DDD
   (ex.: `+55 11 99999-0000`) e a apikey. Clique em **Testar**.

Pode cadastrar mais de um número (ex.: você e um amigo). A chave fica guardada no Gerenciador de
Credenciais do Windows, não em arquivo.

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
| "sem perfil para LxA" no card | A janela tem um tamanho sem perfil: deixe o client em 800x600 ou calibre em *Arquivo → Calibração* |
| Teste do WhatsApp falha | Confira o número com DDI, a apikey e se o número do bot ainda é o do site |
| Nenhuma janela encontrada | O título da janela precisa ser "MU" e o processo `main.exe` (ajustável em *Configurações → Monitor*) |
| Alertas não chegam com o PC em espera | Veja a seção Energia |
