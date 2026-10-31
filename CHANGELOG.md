# Novidades do MU Sentinel

## [0.2.0] - 2026-10-30

### Novo
- **Pedidos pelo Telegram**: /status, /print, /inventario, /personagem, /cacada, /loja, /ok, /pausar e
  /retomar, também como botões no bot. Vem a imagem do painel e os números lidos.
- **🎯 Escolher personagem**: os pedidos respondem de um personagem só ou de todos.
- **Loja / Gremory Case**: aviso **VENDA NA LOJA** a cada item novo no Gremory Case (aba Personal Shop),
  com a imagem. Vale para qualquer janela com o Gremory aberto, e avisa também o que vendeu enquanto o
  app estava fechado. O quadro da janela mostra a contagem e a hora da última venda.
- **Painéis do jogo**: lê Personagem (C), Inventário (I) e Instant Hunting Log em qualquer posição e
  resolução; avisa se um deles fechar sozinho.
- **Calibração automática** de cada janela (sozinha ou pelo botão **Calibrar**).
- Versão no rodapé e esta janela de novidades.

### Melhorias
- Consumo muito menor: ~13% de um núcleo e ~250 MB (antes: 3 núcleos e ~750 MB). O app roda com
  prioridade abaixo do normal, para o jogo vir primeiro.
- Alerta crítico manda **uma** mensagem por acontecimento (lembrete opcional em Configurações → Alertas).
- Leitura do HUD mais firme em 1280x960 (HP, EXP e coordenadas).

### Correções
- Telegram e WhatsApp não enviavam pelo exe (faltava um componente).
- Print do inventário no Telegram saía cortado em 1280x960.

## [0.1.0] - 2026-10-29

- Primeira versão: monitor das janelas do MU (morte, desconexão, janela travada ou fechada, caça
  parada) com alertas no Windows, Telegram e WhatsApp (CallMeBot).
