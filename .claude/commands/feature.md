---
description: Pipeline completo planner → python-developer → tester → reviewer
---

Execute o pipeline para a tarefa: $ARGUMENTS

1. Invoque o subagent `planner`. Saída = plano de 8 seções.
2. Invoque `python-developer` passando o plano **literal** como entrada.
3. Invoque `tester`.
   - Veredito `REPROVADO` → volte ao passo 2 com o relatório do tester.
4. Invoque `reviewer`.
   - Veredito `REPROVADO` → volte ao passo 2 com os findings `BLOQUEANTE`.
   - `APROVADO COM RESSALVAS` → volte ao passo 2 com os findings `IMPORTANTE`.
5. Limite de 2 rodadas de correção, contando passos 3 e 4 juntos.
   Após a segunda, PARE e reporte ao humano o que ficou aberto.

Não pule etapas. Não implemente você mesmo.