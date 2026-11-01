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
- MU Online aberto em janela, em qualquer resolução. Para 800x600 e 1024x768 (com escala de 125% do Windows a
  janela fica 1280x960) já vem perfil pronto. Em outro tamanho o app **se calibra sozinho** (veja abaixo).

## Calibração automática

O app lê a tela de cada janela com um leitor completo (mais lento) e ensina o leitor rápido do HUD: HP, EXP,
mapa, coordenadas e o tempo de caça (na janela de caça, onde quer que você a deixe). Acontece sozinho:

- quando abre uma janela de um tamanho que ainda não tem perfil;
- quando o HUD de uma janela fica ilegível por uns 30 s (no máximo 1 vez a cada 10 min por janela).

Também dá para pedir com o app aberto: botão **Calibrar** no quadro de cada janela, ou *Leitura → Calibrar
todas as janelas agora*. Use depois de mudar a resolução ou o layout. Aparece um resumo do que foi lido e
aprendido. Calibrar de novo com outros números na tela (ex.: depois de tomar dano) ensina dígitos que faltam.
Os painéis (C, I, caçada, Gremory) se ajustam sozinhos a qualquer resolução.

## Instalar

0. Baixe o arquivo `MUSentinel-vX.Y.Z-win64.zip` da versão mais nova em
   <https://github.com/CarlosEduardo00/mu-sentinel/releases/latest>.
1. **Extraia o `.zip` antes de abrir:** botão direito no `.zip` → **Extrair tudo…** → escolha uma pasta sua
   (ex.: `C:\Jogos\MUSentinel`). Não precisa ser em Arquivos de Programas.
   Abrir o exe direto de dentro do zip dá o erro *"Failed to load Python DLL … python312.dll"*.
2. Na pasta extraída, abra **MUSentinel.exe**. Ele precisa ficar junto da pasta `_internal`; para ter um
   ícone na Área de Trabalho, crie um **atalho** em vez de mover o exe.
3. Se o Windows mostrar **"O Windows protegeu o computador"** (SmartScreen): clique em
   **Mais informações → Executar assim mesmo**. Isso aparece porque o app não tem assinatura digital.

Não precisa rodar como administrador.

## Assistente (primeira vez)

1. **Janelas do jogo:** abra os clients (até 4) e dê um nome a cada janela (ex.: "Elf Kanturu").
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

## Pedidos pelo Telegram

Com o Telegram ativo, dá para **pedir** coisas pelo celular (botões que aparecem no bot, ou digitando).
Só as conversas da lista do app são atendidas:

| Pedido | O que volta |
| --- | --- |
| `/status` | Estado de cada janela, mapa, HP, EXP/h e painéis abertos |
| `/print 2` | Print da janela 2 (sem número: todas) |
| `/inventario 2` | Imagem do Inventário (I), espaços ocupados/livres, Zen e o que mudou desde o último pedido |
| `/personagem 2` | Imagem da janela C: classe, level, pontos a distribuir, atributos |
| `/cacada 2` | Instant Hunting Log: tempo de caça, EXP por segundo e por hora, abates, dano |
| `/loja` | Gremory Case da janela **Loja** (quantos itens entraram) |
| `/ok` | Para os lembretes dos alertas críticos (se estiverem ligados) |
| `/pausar 60` · `/retomar` | Pausa os alertas por 60 min / volta |
| 🎯 **Escolher personagem** (`/alvo`) | Escolhe de qual personagem os pedidos respondem: um só ou **Todos**. Fica valendo até você trocar; um número digitado (`/inventario 2`) vale só para aquele pedido |

O MU Sentinel **não aperta teclas** no jogo: os painéis precisam estar **abertos por você** (C, I, a janela de
caça). Ele acha cada painel pelo título, em qualquer lugar da tela, então pode arrumar as janelas do jeito que
couber. Os nomes dos itens do inventário não aparecem na tela (são só ícones): por isso vai a imagem, mais a
contagem de espaços e o Zen.

Se um painel que estava aberto **fechar sozinho** (relog, morte, teleporte) com você longe do PC, chega um
aviso para abrir de novo. Fechou com você mexendo no PC: o app entende que foi de propósito.

## Loja (personagem vendendo)

Dê o nome **Loja** à janela do personagem que vende (no assistente ou em *Configurações → Slots*). Nessa
janela:

- deixe o **Gremory Case** aberto na aba **Personal Shop**;
- quando o número de itens dele subir (ex.: `0 / 150` → `1 / 150`), chega no celular **"VENDA NA LOJA"** com a
  imagem do Gremory Case;
- se o Gremory Case fechar ou ficar em outra aba, chega um aviso;
- não há alertas de caça parada (o personagem fica na cidade de propósito).

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

- Fechar a janela do app **não** desliga o monitor: ele fica no ícone do escudo perto do relógio.
  Para sair: botão direito no ícone → **Sair**.
- A bolinha no ícone mostra como estão as janelas: 🟢 tudo certo, 🟡 atenção (caça parada, tela ilegível),
  🔴 alerta (morte, queda, travou, fechou), ⚪ alertas pausados. Passe o mouse por cima para ler o resumo, ou
  clique com o botão direito para pausar, testar ou abrir as Configurações.
- No topo do app, uma frase resume tudo ("Tudo certo · 3 janelas", "1 alerta: Crusader MORTO"). O rodapé mostra
  para onde os alertas vão (Telegram, WhatsApp, Windows) e se o monitor está rodando.
- Cada acontecimento (morte, desconexão, janela travada ou fechada) gera **uma** mensagem, e outra quando
  resolve. Quer ser lembrado enquanto o problema continua (ex.: para acordar)? Ligue o **lembrete** em
  *Configurações → Alertas*: chega "LEMBRETE: MORTE continua" a cada 5 min até você responder **/ok** no
  Telegram ou clicar em **OK, vi o alerta** no painel.
- **Janela travada** é quando o Windows marca o jogo como "Não respondendo" por 30 s. Personagem parado
  (a Loja, alguém na cidade) não conta.
- Se o mesmo alerta acontecer 3 vezes em 30 min, a 3ª mensagem avisa que está **instável** e, por 30 min,
  ele aparece só no painel do app (sem encher o celular).
- **Pausar alertas** no topo do painel (30 min, 1 h, 2 h ou até retomar).
- Se o mapa/HP aparecer como ILEGÍVEL: algum menu está por cima do HUD (inventário, Helper…).
  Isso nunca gera alerta crítico.
- Deixe a janela do jogo **não minimizada** (pode ficar atrás de outras janelas).

## Atualizações

Ao abrir, o app procura uma versão nova no GitHub. Se tiver, aparecem as novidades com os botões
**Atualizar agora**, **Depois** e **Pular esta versão**. "Atualizar agora" baixa, confere o arquivo e abre o
app de novo já atualizado, em alguns segundos. Configuração, Telegram e nomes das janelas continuam como estão.

- Com o app na bandeja, vem um aviso perto do relógio; o rodapé do painel mostra "atualização X disponível".
- Procurar na hora: *Ajuda → Procurar atualizações*. Desligar: *Configurações → Monitor*.
- A procura só consulta o GitHub; nada seu é enviado.
- Quem tem a versão 0.2.2 ou anterior instala a 0.2.3 do jeito normal uma vez (saia do app, apague a
  pasta antiga e extraia o zip novo). Daí em diante as atualizações são pelo próprio app.
- Se a pasta do app estiver num lugar que pede administrador (ex.: Arquivos de Programas), o app não
  consegue se trocar sozinho e abre a página de download.

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
| "Failed to load Python DLL … python312.dll" | O exe foi aberto de dentro do zip ou separado da pasta `_internal`. Extraia o zip inteiro (Instalar, passo 1) |
| "Monitoramento limitado pelo anti-cheat" | É o GameGuard (veja acima). O app segue pela imagem; não há o que configurar |
| "sem perfil para LxA" no card | Tamanho novo: o app calibra sozinho em alguns segundos. Se não resolver, clique em **Calibrar** no quadro da janela |
| HP/EXP ilegível ou errado depois de mudar resolução | Clique em **Calibrar** no quadro da janela (com o HUD visível, sem menu por cima) |
| PC lento ou barulhento com o app aberto | Atualize: a versão nova usa cerca de 15% de um núcleo e ~250 MB (antes: 3 núcleos e ~750 MB) |
| Telegram: "token inválido" | Copie de novo o token inteiro que o @BotFather mandou |
| Pedido responde "não está aberto" | Abra o painel no jogo (C, I, janela de caça, Gremory Case) e deixe aberto |
| Telegram: "outra cópia do MU Sentinel está lendo as mensagens" | O mesmo bot está em dois PCs: cada PC precisa do próprio bot |
| Telegram: "Buscar conversas" não acha ninguém | Abra o link do bot e toque em Iniciar (vale por 24 h), depois busque de novo |
| WhatsApp: teste falha | Confira o número com DDI, a apikey e se o número do bot ainda é o do site |
| WhatsApp: "o CallMeBot aceitou", mas não chega | Abra no navegador o link de teste que o próprio bot mandou no WhatsApp. Se também não chegar, a fila do CallMeBot está atrasada ou parada: use o Telegram |
| Nenhuma janela encontrada | O título da janela precisa ser "MU" e o processo `main.exe` (ajustável em *Configurações → Monitor*) |
| Alertas não chegam com o PC em espera | Veja a seção Energia |
