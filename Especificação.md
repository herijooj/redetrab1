# Especificação Simplificada do Protocolo para Copas em Rede Anel

## 1. Visão Geral

Este documento especifica o protocolo de comunicação e as regras para implementar o jogo de cartas Copas para 4 jogadores em uma rede em anel com 4 máquinas, utilizando sockets DGRAM (UDP) e controle de acesso por passagem de bastão. O protocolo foi simplificado para reduzir a complexidade, mantendo a funcionalidade, e inclui uma sincronização explícita na fase de passagem de cartas.

---

## 2. Arquitetura da Rede

- **Topologia:** Rede em anel com 4 máquinas (M0, M1, M2, M3).
- **Comunicação:** Socket DGRAM (UDP).
- **Endereçamento:** Cada máquina conhece o IP e a porta da próxima máquina no anel. Escuta em uma porta fixa para receber da máquina anterior.
- **Ordem Fixa:** M0 → M1 → M2 → M3 → M0.
- **Coordenador/Dealer (M0):** M0 inicia o jogo, distribui cartas, coordena fases e calcula pontuações.
- **Bastão (Token):** Uma mensagem `TOKEN_PASS` circula para autorizar ações significativas (ex.: jogar carta, passar cartas).

---

## 3. Formato das Mensagens

Todas as mensagens têm um cabeçalho fixo seguido de um payload variável, em formato binário para eficiência.

| TIPO_MSG (1 byte) | ORIGEM_ID (1 byte) | DESTINO_ID (1 byte) | SEQ_NUM (1 byte) | TAM_PAYLOAD (1 byte) | PAYLOAD (até 255 bytes) |
|-------------------|--------------------|---------------------|------------------|----------------------|-------------------------|

- **TIPO_MSG:** Identifica o tipo da mensagem (ver Seção 4).
- **ORIGEM_ID:** ID da máquina que criou a mensagem (0-3).
- **DESTINO_ID:** 0-3 para jogador específico, 0xFF (BROADCAST) para todos.
- **SEQ_NUM:** Número de sequência incrementado pela origem para cada mensagem enviada.
- **TAM_PAYLOAD:** Tamanho do payload em bytes.
- **PAYLOAD:** Dados específicos do tipo de mensagem.

---

## 4. Tipos de Mensagem

| TIPO_MSG (Hex) | Nome           | Payload Detalhado                                      | Descrição                                                                 |
|----------------|----------------|--------------------------------------------------------|---------------------------------------------------------------------------|
| 0x01           | TOKEN_PASS     | ID_NOVO_DONO_TOKEN (1 byte)                            | Passa o bastão para ID_NOVO_DONO_TOKEN.                                   |
| 0x02           | GAME_START     | Nenhum                                                 | M0 inicia o jogo (BROADCAST).                                             |
| 0x03           | DEAL_HAND      | CARTAS_DA_MAO (13 bytes)                               | M0 envia as 13 cartas da mão para DESTINO_ID.                             |
| 0x04           | START_PHASE    | FASE (1 byte: 0=Passagem, 1=Vazas), SENTIDO_PASSAGEM (1 byte, se FASE=0) | M0 anuncia início da fase de passagem (com sentido) ou vazas (BROADCAST). |
| 0x05           | PASS_CARDS     | CARTAS_PASSADAS (3 bytes)                              | Jogador envia 3 cartas para DESTINO_ID (com token).                       |
| 0x06           | PLAY_CARD      | CARTA_JOGADA (1 byte)                                  | Jogador joga uma carta (BROADCAST, com token).                            |
| 0x07           | TRICK_SUMMARY  | ID_GANHADOR_VAZA (1 byte), ID_JOGADOR_C1 (1 byte), CARTA_J1 (1 byte), ID_JOGADOR_C2 (1 byte), CARTA_J2 (1 byte), ID_JOGADOR_C3 (1 byte), CARTA_J3 (1 byte), ID_JOGADOR_C4 (1 byte), CARTA_J4 (1 byte), PONTOS_VAZA (1 byte) | M0 anuncia ganhador, cartas (com ID do jogador que jogou cada uma) e pontos da vaza (BROADCAST). Total 10 bytes de payload. |
| 0x08           | HAND_SUMMARY   | PONTOS_MAO_J0..J3 (4 bytes), PONTOS_ACUM_J0..J3 (4 bytes), SHOOT_MOON (1 byte: 0xFF=Não, 0-3=ID do jogador) | M0 anuncia pontuação da mão, acumulada e "Atirar na Lua" (BROADCAST).     |
| 0x09           | GAME_OVER      | ID_VENCEDOR (1 byte), PONTOS_FINAIS_J0..J3 (4 bytes)   | M0 anuncia fim do jogo e vencedor (BROADCAST).                            |

**Notas:**
- Mensagens como `GAME_INIT` e `ANNOUNCE_TRICK_LEAD` foram combinadas em `GAME_START` e `START_PHASE`.
- `ERROR_INFO` e `ACK` foram removidos.
- `SENTIDO_PASSAGEM` (em `START_PHASE`): 0=Esquerda, 1=Direita, 2=Frente, 3=Sem Passar.

---

## 5. Representação de Cartas

Uma carta é codificada em 1 byte:

- **Bits 0-3 (Valor):** 1: Ás, 2: Dois, ..., 10: Dez, 11: Valete (J), 12: Dama (Q), 13: Rei (K).
- **Bits 4-5 (Naipe):** 0: Ouros (♦), 1: Paus (♣), 2: Copas (♥), 3: Espadas (♠).
- **Bits 6-7:** Zeros.

**Exemplo:** Dama de Espadas (Q♠) → Valor=12 (1100), Naipe=3 (11) → `00111100` (binário) → `0x3C` (hex).

---

## 6. Processamento de Mensagens

- **Envio:** Uma máquina só origina mensagens de ação (`PASS_CARDS`, `PLAY_CARD`) ou coordenação (se M0) quando possui o bastão.
- **Circulação:** Todas as mensagens circulam pelo anel até retornarem à origem.
- **Recepção:**
  - Se `ORIGEM_ID == ID_DA_MAQUINA`: A mensagem completou a volta e é removida (não repassada). Usada para confirmação interna (ex.: log).
  - Se `ORIGEM_ID != ID_DA_MAQUINA`:
    - Verifica `DESTINO_ID`.
    - Se `DESTINO_ID == ID_DA_MAQUINA` ou `0xFF` (BROADCAST), processa o payload conforme `TIPO_MSG`.
    - Repassa a mensagem inalterada para a próxima máquina (a menos que seja a origem).

---

## 7. Estado Local

Cada máquina mantém:

- Seu ID (0-3).
- Mão de cartas.
- Pontuação de todos os jogadores (mão e acumulada).
- Cartas da vaza atual e naipe inicial.
- Estado de "Copas quebradas".
- Sentido da passagem de cartas.
- Quem possui o bastão (inferido por `TOKEN_PASS`).
- Fase atual (passagem ou vazas).

---

## 8. Fluxo do Jogo

1. **Configuração:**
   - 4 instâncias iniciadas com ID, porta de escuta e IP/porta do próximo nó.
   - M0 inicia com o bastão.

2. **Início do Jogo:**
   - M0 envia `GAME_START` (BROADCAST).

3. **Início da Mão:**
   - M0 embaralha e envia `DEAL_HAND` para cada jogador (4 mensagens, `DESTINO_ID=0-3`).
   - M0 envia `START_PHASE` (BROADCAST, `FASE=0`, `SENTIDO_PASSAGEM`).

4. **Fase de Passagem de Cartas:**
   - M0 passa o bastão para M0 (primeiro a passar).
   - Jogador com bastão:
     - Escolhe 3 cartas.
     - Envia `PASS_CARDS` para o destinatário (baseado em `SENTIDO_PASSAGEM`).
     - Passa o bastão ao próximo jogador (ordem: M0→M1→M2→M3).
   - **Sincronização:** M0 monitora as 4 mensagens `PASS_CARDS` (usando `SEQ_NUM` e `ORIGEM_ID`). Após todas circularem, M0 envia `START_PHASE` (BROADCAST, `FASE=1`) para iniciar as vazas.

5. **Fase de Vazas:**
   - M0 identifica o jogador com 2♣ (primeira vaza) ou o ganhador da vaza anterior.
   - Passa o bastão para esse jogador via `TOKEN_PASS`.
   - Jogador com bastão:
     - Joga uma carta válida (`PLAY_CARD`, BROADCAST).
     - Passa o bastão ao próximo na ordem (M0→M1→M2→M3).
   - Após 4 `PLAY_CARD`, M0:
     - Calcula ganhador e pontos.
     - Envia `TRICK_SUMMARY` (BROADCAST).
     - Passa o bastão ao ganhador da vaza.
   - Repete até 13 vazas.

6. **Fim da Mão:**
   - M0 calcula pontos (considerando "Atirar na Lua").
   - Envia `HAND_SUMMARY` (BROADCAST).

7. **Fim do Jogo:**
   - M0 verifica se alguém atingiu 100 pontos.
   - Se sim, envia `GAME_OVER` (BROADCAST) com o vencedor (menor pontuação).
   - Se não, atualiza `SENTIDO_PASSAGEM` e volta ao passo 3.

---

## 9. Regras de Copas

- **Atirar na Lua:** Se um jogador pega todos os pontos (13 Copas + Q♠), outros recebem 26 pontos (decisão da equipe). Indicado em `HAND_SUMMARY` (`SHOOT_MOON`: 0=Não, 1=ID do jogador).
- **Quebrar Copas:** Não se lidera com Copas até serem quebradas ou serem a única opção.
- **Primeira Vaza:** Liderada pelo 2♣. Sem pontos (Copas/Q♠), salvo exceção.
- **Validação:** Jogadas validadas localmente antes de `PLAY_CARD`. Assume-se clientes honestos.