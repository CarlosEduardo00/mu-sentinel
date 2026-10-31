# Novidades do MU Sentinel

## [0.2.1] - 2026-10-31

### Correções
- **Fim do falso "JANELA TRAVADA"**: imagem parada não conta mais (a Loja e personagens parados na
  cidade disparavam o alerta à toa). Travada agora é só o Windows marcar o jogo como "Não respondendo"
  por 30 s.
- Trocar de servidor não gera mais "DESCONECTADO": o app espera até 90 s o jogo voltar.
- Leitura errada do HP (ex.: "0/81" no lugar de "800/811") não vira mais morte nem HP baixo. A Loja não
  tem mais alerta de morte nem de HP baixo (na cidade não se morre).
- Leitura errada do Hunting Time não dispara mais "HELPER PAROU".
- Contador do Gremory lido errado uma vez para menos não vira mais uma venda falsa.

### Melhorias
- Alerta que se repete 3 vezes em 30 min avisa que está **instável** e para de chegar no celular por 30 min
  (continua aparecendo no app).
- HP baixo: no máximo 1 aviso a cada 15 min.
- "Helper parou" e "leitura ilegível" esperam você sair do PC (perto, foi você que pausou ou abriu o menu).
- Erro interno vai ao celular uma vez só por tipo de erro.

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
