# Copas (Hearts) - Regras e Restrições para Implementação de Jogo

## Visão Geral
Copas é um jogo de cartas para 4 jogadores onde o objetivo é evitar receber cartas de penalidade (Copas e a Dama de Espadas). Vence quem tiver menos pontos no final.

---

## Componentes
- **Cartas:** Baralho padrão de 52 cartas (sem curingas)
- **Jogadores:** 4 jogadores (sem times)
- **Distribuição:** 13 cartas para cada jogador

---

## Objetivo
Evitar pegar:
- Qualquer carta de **Copas** (♥) → 1 ponto cada
- **Dama de Espadas** (♠Q) → 13 pontos

**Meta final:** Ter a menor pontuação quando um jogador atingir ou ultrapassar **100 pontos**

---

## Regras de Jogo

### 1. Distribuição
- Embaralhar e distribuir 13 cartas para cada jogador.

### 2. Passagem de cartas
- Antes de cada rodada (exceto a 4ª, 8ª, etc.), cada jogador escolhe 3 cartas para passar:
  - Rodada 1: para o jogador à esquerda
  - Rodada 2: para o jogador à direita
  - Rodada 3: para o jogador à frente
  - Rodada 4: sem passagem
  - Repete o ciclo a cada 4 rodadas

### 3. Primeira Dobrada (Truco de Saída)
- O jogador com o **2 de Clubs (♣2)** começa a primeira rodada
- Ele deve jogar o ♣2 obrigatoriamente

### 4. Rodadas
- Jogadores devem seguir o naipe da primeira carta da rodada (se possível)
- Se não puder seguir, pode jogar qualquer carta (restrições abaixo)
- Quem jogar a maior carta do naipe de saída vence a rodada e coleta as cartas

### 5. Restrições de Jogo
- **Copas não podem ser jogadas** como primeira carta de uma rodada até que:
  - Uma carta de Copas tenha sido jogada em rodadas anteriores ("Copas quebradas")
- **Dama de Espadas pode ser jogada a qualquer momento**, exceto na primeira rodada
- **Na primeira rodada**, não é permitido:
  - Jogar Copas
  - Jogar a Dama de Espadas
  - Jogar qualquer carta que não seja do mesmo naipe do ♣2 (caso tenha)

---

## Pontuação
- Cada carta de **Copas (♥)** vale **1 ponto**
- **Dama de Espadas (♠Q)** vale **13 pontos**
- Total máximo por rodada: **26 pontos**

### Variação: Shooting the Moon
- Se um jogador pegar **todas as cartas de penalidade (26 pontos)**:
  - Ele recebe **0 pontos**
  - Todos os outros jogadores recebem **26 pontos**
- (Opcional) Pode-se permitir "Shooting the Sun": todas as 13 rodadas vencidas → 0 pontos, outros +39

---

## Fim de Jogo
- O jogo termina quando **qualquer jogador atingir ou ultrapassar 100 pontos**
- O jogador com **a menor pontuação total** vence