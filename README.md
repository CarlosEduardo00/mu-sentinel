# MU Sentinel

**Vigia as suas janelas do MU Online e avisa no celular, pelo Telegram, quando o personagem morre, cai do
servidor, a janela trava ou fecha, ou a caça para.** Funciona com uma ou várias contas abertas ao mesmo tempo.

[![Baixar o MU Sentinel](https://img.shields.io/badge/BAIXAR-MU%20Sentinel%20para%20Windows-2ea44f?style=for-the-badge)](https://github.com/CarlosEduardo00/mu-sentinel/releases/latest/download/MUSentinel-win64.zip)
![Versão mais nova](https://img.shields.io/github/v/release/CarlosEduardo00/mu-sentinel?label=vers%C3%A3o%20mais%20nova&style=flat-square)

Windows 10 ou 11 (64 bits) · grátis · não precisa instalar Python nem nada · se o botão não funcionar:
[página de download](https://github.com/CarlosEduardo00/mu-sentinel/releases/latest).

> **Leia antes de usar:** a Webzen proíbe programas não oficiais e pode banir a conta. O MU Sentinel
> só **olha** a tela: não aperta teclas, não lê a memória do jogo e nunca pede a sua senha. Mesmo assim,
> o uso é por sua conta e risco ([detalhes](#aviso-de-risco)).

## Instalar em 3 passos

1. **Baixe:** clique no botão verde acima. Se o navegador avisar que o arquivo "não é baixado com frequência",
   escolha **Manter** (no Edge: **…** → **Manter** → **Manter assim mesmo**).
2. **Extraia:** na pasta Downloads, clique com o botão direito em `MUSentinel-win64.zip` → **Extrair tudo…** →
   **Extrair**. Não abra o programa de dentro do zip, porque assim ele não funciona.
   > Dica: extraia numa pasta fora do OneDrive, por exemplo `C:\Jogos\MUSentinel`. As atualizações ficam mais rápidas.
3. **Abra** o `MUSentinel.exe` da pasta extraída. Se aparecer **"O Windows protegeu o computador"**, clique em
   **Mais informações** → **Executar assim mesmo**. Esse aviso só aparece na primeira vez, porque o app não tem
   assinatura digital (que é paga).

Na primeira vez abre um assistente: você dá um nome para cada janela do jogo e liga o Telegram. Leva uns
2 minutos. Não precisa abrir como administrador.

**Atalho na Área de Trabalho:** botão direito no `MUSentinel.exe` → **Mostrar mais opções** → **Enviar para** →
**Área de trabalho (criar atalho)**. Não tire o exe de dentro da pasta: ele precisa da pasta `_internal`.

## Atualizar

**É sozinho.** Ao abrir, o MU Sentinel confere se saiu versão nova. Se saiu, mostra as novidades: clique em
**Atualizar agora** e, em alguns segundos, ele baixa, confere o arquivo, troca e abre de novo. A configuração,
o Telegram e os nomes das janelas continuam como estavam.

- Quer conferir na hora? Menu **Ajuda** → **Procurar atualizações**.
- A versão instalada aparece no rodapé do app.
- **Tem a versão 0.2.2 ou mais antiga?** Ela ainda não se atualiza sozinha. Faça só uma vez: saia do app (botão
  direito no ícone perto do relógio → **Sair**), apague a pasta antiga e instale de novo pelos 3 passos acima.
  A sua configuração fica guardada.

## Ligar os alertas no celular (Telegram)

Grátis, uns 2 minutos. Dá para fazer no assistente da primeira vez ou depois em **Configurações** → **Telegram**:

1. No Telegram, abra o [@BotFather](https://t.me/BotFather) e mande `/newbot`. Escolha um nome (ex.: *MU Alertas*)
   e um usuário que termine em `bot`.
2. Ele responde com um **token**. Copie, cole no MU Sentinel e clique em **Verificar**.
3. Abra o link do seu bot que aparece no app e toque em **Iniciar**.
4. Clique em **Buscar conversas** e depois em **Testar**. A mensagem de teste chega no seu Telegram.

Outra pessoa também pode receber os alertas do seu PC: ela abre o link do seu bot, toca em **Iniciar**, e você
clica em **Buscar conversas** de novo. Prefere WhatsApp? Também dá, pelo CallMeBot, quando ele tiver vaga
(veja o [LEIA-ME](LEIA-ME.md#alertas-no-whatsapp-callmebot)).

## O que ele faz

### Alertas

| Alerta | Quando chega |
| --- | --- |
| 💀 **MORTE** | o HP zerou, ou o personagem foi parar na cidade sem você mexer no PC |
| 🔌 **DESCONECTADO** | o jogo perdeu a conexão com o servidor, ou a internet do PC caiu |
| 🧊 **JANELA TRAVADA** | o Windows marcou o jogo como "Não respondendo" por 30 segundos |
| ❌ **CLIENT FECHADO** | o jogo fechou (crash, erro) |
| ⏸️ **CAÇA PARADA** / **HELPER PAROU** | sem ganhar EXP há 5 minutos / o Hunting Time parou |
| ❤️ **HP BAIXO** | HP abaixo de 30% (no máximo 1 aviso a cada 15 minutos) |
| 💰 **VENDA NA LOJA** | entrou item novo no Gremory Case da janela chamada "Loja" |
| 📋 **PAINEL FECHADO** | o Inventário, a janela C ou a de caça fechou sozinha enquanto você estava longe |

- Os alertas graves chegam com o **print da janela**.
- Chega **uma** mensagem quando acontece e outra quando resolve, sem encher o celular. Se quiser ser lembrado
  até responder (para acordar, por exemplo), ligue o lembrete em **Configurações** → **Alertas**.
- Dá para **pausar os alertas** por 30 min, 1 h, 2 h ou até retomar.

### Pedidos pelo celular

Com o Telegram ligado, você também pode **pedir** coisas, pelos botões do bot ou digitando:

| Pedido | O que volta |
| --- | --- |
| `/status` | como está cada janela: estado, mapa, HP, EXP por hora |
| `/print 2` | print da janela 2 (sem número: todas) |
| `/inventario 2` | imagem do Inventário, espaços livres e Zen |
| `/personagem 2` | imagem da janela C: level, pontos, atributos |
| `/cacada 2` | tempo de caça, EXP por hora, abates |
| `/loja` | o Gremory Case da janela "Loja" |
| `/pausar 60` · `/retomar` | pausa os alertas por 60 minutos / volta |
| 🎯 **Escolher personagem** | de qual personagem os pedidos respondem: um só ou todos |

Os painéis precisam estar **abertos por você** no jogo (C, I, janela de caça), porque o app não aperta teclas.
Pode deixá-los em qualquer lugar da tela.

### No computador

- Um quadro para cada janela do jogo, com estado, HP, mapa, EXP por hora, Hunting Time, conexão e painéis abertos.
- Aba **Eventos** com o histórico de tudo que aconteceu (dá para exportar).
- Fica no ícone perto do relógio e pode **iniciar junto com o Windows**.
- **Calibra sozinho** para a resolução da sua janela (800x600 e 1024x768 já vêm prontos).
- É leve: cerca de 15% de um núcleo do processador e 250 MB de memória com 3 janelas abertas.
- **Loja:** dê o nome **Loja** à janela do personagem que vende e deixe o Gremory Case aberto na aba
  **Personal Shop**. Cada venda gera um aviso com a imagem.

## Segurança e privacidade

- **Só observa:** lê a imagem das janelas e informações do Windows. Não envia teclas, não lê a memória do jogo,
  não mexe nos arquivos do jogo e **nunca pede nem guarda a senha do jogo**.
- O token do Telegram e as chaves ficam no **Gerenciador de Credenciais do Windows**, nunca em arquivo, log ou
  exportação.
- O app só se conecta ao Telegram ou ao WhatsApp (se você ligar) e ao GitHub, para procurar atualizações (dá para
  desligar em **Configurações** → **Monitor**). Nada seu é enviado ao GitHub.
- Toda atualização é conferida (SHA-256) antes de ser instalada.
- O código é aberto: qualquer um pode conferir o que o app faz.

**Anti-cheat (GameGuard):** o GameGuard do MU pode esconder do app de qual programa são as janelas do jogo. O
MU Sentinel não tenta contornar isso: mostra o aviso "Monitoramento limitado pelo anti-cheat" e continua pela
imagem. Nesse modo ele só deixa de detectar a queda do servidor do jogo com a internet do PC funcionando.

## Problemas comuns

| O que aparece | O que fazer |
| --- | --- |
| "Failed to load Python DLL … python312.dll" | O app foi aberto de dentro do zip. Extraia primeiro (passo 2) |
| "O Windows protegeu o computador" | **Mais informações** → **Executar assim mesmo** |
| O navegador bloqueou o download | Escolha **Manter** no aviso do navegador (passo 1) |
| Nenhuma janela encontrada | Abra o jogo em janela. O título precisa ser "MU" e o processo `main.exe` |
| "sem perfil para LxA" no quadro da janela | O app calibra sozinho em alguns segundos. Se não resolver, clique em **Calibrar** |
| HP ou EXP ilegível depois de mudar a resolução | Clique em **Calibrar** no quadro da janela, com o HUD à vista |
| Telegram: "token inválido" | Copie de novo o token inteiro que o @BotFather mandou |
| Telegram: "Buscar conversas" não acha ninguém | Abra o link do bot, toque em **Iniciar** e busque de novo |
| Os alertas param quando o PC entra em espera | Em **Configurações** → **Monitor**, ligue "manter a tela ligada" (importante em notebook) |
| A atualização não conseguiu trocar os arquivos | A pasta do app pede administrador ou está no OneDrive. Instale de novo numa pasta como `C:\Jogos\MUSentinel` |

Mais respostas no [LEIA-ME](LEIA-ME.md), o manual completo, que também vai dentro do zip.

## Aviso de risco

A política operacional da Webzen proíbe macros e programas não oficiais e prevê banimento permanente,
inclusive de todas as contas ligadas à mesma pessoa. O MU Sentinel é um programa não oficial: ele só observa a
tela, mas o GameGuard pode registrar programas a que ele reage, e não há como saber se isso é informado à
Webzen. **Use por sua conta e risco.**

## Mais informações

- [Novidades de cada versão](CHANGELOG.md) · [todas as versões para baixar](https://github.com/CarlosEduardo00/mu-sentinel/releases)
- [Manual completo (LEIA-ME)](LEIA-ME.md)
- [Para quem quer mexer no código](DESENVOLVIMENTO.md)
