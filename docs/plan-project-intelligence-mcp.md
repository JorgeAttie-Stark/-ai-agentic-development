# Project 1 — Project Intelligence MCP

> **Status:** planejado, não iniciado
> **Autor:** subagent `planner` (`.claude/agents/planner.md`)
> **Data:** 2026-09-07
> **Contrato:** 8 seções, conforme `.claude/agents/planner.md` e `.claude/agents/python-developer.md`

**Como usar este documento:** ele é a entrada do agente `python-developer`. As 8 seções
abaixo são o contrato literal — não remova nem renomeie títulos. O escopo executável
hoje é **Milestone 0 + Milestone 1**; os Milestones 2-5 exigem ciclo de planejamento
próprio antes de começar.

**Revisão:** a origem do `projectRoot` foi corrigida após revisão humana. Ver
`Proposed Architecture §1` — ele vem da configuração do processo servidor, com o `cwd`
como mecanismo inicial, nunca de uma extensão do payload de `initialize`. A mesma seção
registra a costura deixada para múltiplos projetos, que **não** é implementada agora.

---

## Understanding

Evoluir o laboratório para um **MCP server generalista, agnóstico de linguagem**, que
aponta para um `project_root` arbitrário — não necessariamente este repositório — e
oferece ~20 tools em 5 camadas: Exploração, Entendimento, Análise, Visualização e
Documentação.

Este plano substitui integralmente o plano anterior de 3 tools fixadas neste repo
(`list_tests`/`run_tests`/`read_repo_file`). Aquele escopo não é reaproveitado; só o
conhecimento já validado sobre o repositório e suas restrições.

Requisito de primeira classe: **epistemologia por evidência**. Nenhuma tool de Camada 2+
pode devolver uma conclusão sem (a) evidência concreta — arquivo, linha, trecho — e
(b) confiança explícita. Isso precisa estar no **contrato de retorno** das tools, não
apenas em texto de instrução.

---

## Relevant Files

Existentes, usados como contexto e precedente:

| Arquivo | Por quê |
|---|---|
| `CLAUDE.md:8-19` | stack: Python 3 stdlib, `unittest`, proibição de `pytest` |
| `CLAUDE.md:21-29` | arquitetura declarada: pacote único `ai_dev_lab` |
| `CLAUDE.md:31-48` | comando de teste canônico e Definition of Done |
| `README.md:12` | badge declara "Python 3.9+"; nenhum arquivo do repo fixa `3.9.6` |
| `README.md:242` | comando canônico, já alinhado ao `CLAUDE.md` |
| `README.md:261-274` | checklist de experimentos — MCP é o único item de cobertura zero |
| `src/ai_dev_lab/parity.py`, `tests/test_parity.py` | único precedente real de estilo do repo |
| `pyproject.toml` | **0 bytes** — nenhuma dependência, nenhum `[project]` declarado |
| `.claude/agents/planner.md`, `python-developer.md`, `tester.md`, `code-reviewer.md` | contratos e limites (2 rodadas; `tester` só escreve em `tests/`; `reviewer` sem `Edit`/`Write`) |
| `.claude/commands/feature.md:1-16` | orquestrador; limite de 2 rodadas somando passos 3 e 4 |
| `.claude/skills/test-driven-development/SKILL.md`, `code-review/SKILL.md` | processos que os agents seguem |
| `.claude/settings.local.json` | allowlist Bash em prefixo: `Bash(PYTHONPATH=src python3 -m unittest *)` |

Confirmado por `Glob`: **não existe** `.gitignore` na raiz, **não existe** `.mcp.json`.

Novos, propostos para Milestone 0 e 1:

- `src/ai_dev_lab/project_intelligence/__init__.py`
- `src/ai_dev_lab/project_intelligence/__main__.py` — entrypoint, parsing de `--root`
- `src/ai_dev_lab/project_intelligence/config.py` — resolução e validação do `projectRoot`
- `src/ai_dev_lab/project_intelligence/protocol.py`
- `src/ai_dev_lab/project_intelligence/paths.py`
- `src/ai_dev_lab/project_intelligence/exploration.py`
- `tests/project_intelligence/__init__.py`
- `tests/project_intelligence/test_config.py`
- `tests/project_intelligence/test_protocol.py`
- `tests/project_intelligence/test_paths.py`
- `tests/project_intelligence/test_exploration.py`
- `tests/project_intelligence/fixtures/fake_project/` — repositório-alvo sintético multi-linguagem

---

## Current Architecture

O repositório hoje tem um único módulo de produção (`src/ai_dev_lab/parity.py`, 5 linhas)
e sua suíte (`tests/test_parity.py`, 32 linhas), descobertos via
`PYTHONPATH=src python3 -m unittest discover -s tests`.

Não há pacote instalado, não há CLI, não há processo servidor e **não há noção de
"projeto alvo"** — tudo que existe opera sobre o próprio repositório.

O pipeline de 4 agents e o comando `/feature` existem como contratos completos, mas —
pelo checklist do `README.md:261-274` — ainda não foram exercitados numa tarefa real de
ponta a ponta. `parity.py` foi construído por interação direta com as skills de TDD e
Code Review, não pelo orquestrador.

Não existe hoje nenhuma noção de servidor, protocolo, raiz de projeto configurável ou
evidência estruturada em lugar nenhum do código. MCP permanece em cobertura zero — as
únicas menções ao termo no repositório inteiro são as linhas de checklist e diagrama do
`README.md`.

---

## Proposed Architecture

Servidor MCP sobre **stdio**, com framing JSON-RPC 2.0 newline-delimited, suportando
`initialize`, `tools/list`, `tools/call` e notificações (requisições sem `id`, que não
geram resposta).

### 1. `projectRoot` vem da configuração do servidor

O `initialize` do MCP tem payload **padronizado** — `protocolVersion`, `capabilities`,
`clientInfo` — e não carrega `projectRoot`. Estender esse payload com um campo próprio
produziria um servidor que passa nos nossos testes e **nunca funciona num cliente real**,
porque um cliente spec-compliant como o Claude Desktop não manda um campo que não existe
na especificação.

`projectRoot` é, portanto, **configuração do processo servidor**, resolvida antes de
qualquer tráfego MCP acontecer:

```
Claude Desktop
      │
      ▼
configuração do servidor  ──►  --root  |  cwd  |  env
      │
      ▼
processo inicia · resolve e valida projectRoot · falha rápido se inválido
      │
      ▼
MCP initialize   (payload padrão — sem projectRoot)
      │
      ▼
tools/call   ──►   paths confinados a projectRoot
```

Origem do valor na v1, em ordem de precedência:

1. **`--root <path>`** — a forma canônica e, na prática, **obrigatória** para uso via
   cliente MCP. Configuração de processo, nunca payload de protocolo.
2. `cwd` do processo, quando `--root` está ausente — conveniência para invocação manual
   em terminal, onde o `cwd` é o do shell e portanto previsível.
3. Falha na **inicialização** se o valor resolvido não existir ou não for diretório: o
   processo não sobe. Não é erro de tool em runtime — é erro de configuração, e deve
   aparecer como tal.

> ⚠️ **Correção após verificação contra cliente real.** A versão anterior deste plano
> tratava o `cwd` como o mecanismo inicial, na premissa de que *"o cliente MCP já
> controla o diretório de trabalho do servidor que ele lança"*. **Essa premissa é falsa
> para o Claude Desktop:** ele não aceita a chave `cwd` no bloco `mcpServers` — ao
> reescrever o `claude_desktop_config.json`, ele **descarta** a chave silenciosamente.
>
> Sem `--root`, a raiz vira o diretório de trabalho do próprio app. Medido:
> `total_files: 20000`, `scan_truncated: true`, `unreadable_entries_skipped: 48` — um
> inventário inútil, e sem nenhum erro que indique a causa.
>
> É a mesma classe de erro do `BLOQUEANTE` do `tools/call`: uma suposição sobre o
> comportamento do cliente que passa em todos os nossos testes e falha no cliente real.
> Só apareceu ao tentar conectar de verdade — é o argumento mais concreto a favor de o
> item 10 do Definition of Done existir.

Configuração real, em `claude_desktop_config.json` — `--root` é obrigatório aqui:

```json
{
  "mcpServers": {
    "project-intel": {
      "command": "python3",
      "args": [
        "-m", "ai_dev_lab.project_intelligence",
        "--root", "/caminho/do/projeto/alvo"
      ],
      "env": { "PYTHONPATH": "/caminho/do/repositorio/src" }
    }
  }
}
```

O `cwd` continua suportado pelo código e é o caminho conveniente para rodar o servidor
à mão no terminal — mas não é utilizável via `claude_desktop_config.json`.

**Caminho spec-correto, para depois:** a especificação MCP tem a capability `roots`,
pela qual o **cliente** informa ao servidor quais diretórios estão em escopo, via
`roots/list`. Esse é o mecanismo padronizado para exatamente este problema. O suporte
varia entre clientes, então: v1 usa configuração do servidor, que funciona hoje sem
depender de capability alguma; suporte a `roots` entra como incremento quando houver
cliente que a declare — **nunca como única via**, para o servidor não deixar de
funcionar onde a capability não existe.

Toda tool que toca arquivo resolve caminhos relativos a `projectRoot`, **nunca** à raiz
do AI Dev Lab. Qualquer path resolvido que não seja `is_relative_to(projectRoot)` é
rejeitado.

Regra de protocolo, separada disso: chamar `tools/call` antes do handshake de
`initialize` é erro estruturado, não crash — mas isso é sequenciamento MCP, não tem
relação com a origem do `projectRoot`.

**Costura para múltiplos projetos — preparada, não implementada.**

A evolução previsível é o servidor atender mais de um projeto ao mesmo tempo. Preparar
para isso **não** significa construir agora; significa não fechar a porta. Três decisões
que custam zero linha extra e deixam a porta aberta:

1. **`projectRoot` não é global de módulo.** Ele vive num `context` passado
   explicitamente para `dispatch`/`serve_stdio`. Trocar uma raiz por várias passa a ser
   mudar o que está no `context`, não caçar leitura de global dentro de cada tool.
2. **O `context` guarda um mapeamento, não um `Path` solto** — hoje com exatamente uma
   entrada: `{"roots": {"default": Path(...)}}` em vez de `{"root": Path(...)}`. É a
   mesma linha de código, e é a diferença entre acrescentar uma chave depois e reescrever
   a assinatura de tudo.
3. **Tools recebem a raiz por parâmetro.** `paths.resolve_within(project_root, path)` já
   é assim. Nenhuma tool descobre a raiz sozinha.

O que **não** entra agora, e é explicitamente proibido pelo Definition of Done: nenhum
parâmetro `root`/`root_id` no schema das tools, nenhum resolver com lista de caminhos,
nenhum branch para um caso que não existe. Código para uma segunda raiz que ninguém
exercita é generalidade especulativa não testada — pior do que a duplicação que ela
tentaria evitar, e contra a regra de abstração na segunda ocorrência.

O caminho natural para essa evolução é a capability `roots` descrita acima, não uma
invenção nossa.

### 2. Contrato de retorno com evidência + confiança

Somente tools **interpretativas** (Camadas 2 a 5) carregam este envelope. Tools de
retrieval puro (`list_files`, `read_file`, `project_info`, `project_profile`) não
precisam, porque elas **são** a evidência, não uma inferência sobre ela.

```json
{
  "findings": [
    {
      "claim": "texto da conclusão",
      "confidence": "HIGH",
      "method": "manifest-read",
      "evidence": [
        {"file": "caminho/relativo", "line": 12, "snippet": "trecho literal"}
      ]
    }
  ],
  "scope_limitations": ["frase explícita do que esta tool não tenta responder"]
}
```

Dict simples, sem classes — data over objects.

`confidence` é amarrada ao `method`, não a julgamento subjetivo:

| `method` | `confidence` | Razão |
|---|---|---|
| `manifest-read`, `ast-parse` | `HIGH` | parsing de formato bem definido — a evidência **é** o fato |
| `name-pattern` | `MEDIUM` | convenção forte e comum, não verificada semanticamente |
| `regex-heuristic` | `LOW` | sem parser real; falso positivo é esperado |

**Invariante:** nenhuma tool emite uma `claim` sem ao menos um item em `evidence`.

### 3. Fronteira honesta: agnóstico de linguagem vs. específico de linguagem

Esta é a resposta ao risco de análise profunda usando apenas stdlib. Para cada tool,
o que é honestamente factível e o que seria invenção:

| Tool | Fatia agnóstica honesta | Exigiria parser de linguagem | Decisão |
|---|---|---|---|
| `project_map`, `architecture_explainer` | nomes de diretório contra vocabulário arquitetural comum (`routes/`, `services/`, `models/`, `tests/`) — `MEDIUM`/`LOW` | grafo de imports real, semântica de camadas | relata **padrões de nome com evidência**; nunca conclui o estilo arquitetural como fato |
| `code_structure_analyzer` | contagem de linhas, distribuição de tamanhos de arquivo | contagem de função/classe, profundidade de aninhamento | Python: `ast` da stdlib → `HIGH`. Outras linguagens: regex de keyword (`def`/`function`/`class`) → sempre `LOW`, rotulado como heurística |
| `dependency_analyzer` | dependências **declaradas**: `requirements.txt`, `package.json` via `json` da stdlib | `pyproject.toml` exige TOML; `tomllib` só existe a partir do **Python 3.11** | v1: apenas os dois primeiros (`HIGH`). TOML via extração regex (`LOW`), ou dependência nova (`tomli`) proposta e justificada quando o Milestone 2 for planejado |
| grafo de import interno | — | Python via `ast.parse` → `HIGH`; outras via regex de `import`/`require`/`#include` → `LOW` | idem acima |
| `data_flow_analyzer` | nenhuma fatia honesta além de call graph Python via `ast` | data flow real exige CFG e análise semântica — inviável em stdlib puro e agnóstico | **rescopado**: primeira versão é "call graph, Python-only, best-effort"; nunca chamado de "data flow" no retorno sem essa ressalva. Adiado para milestone próprio |
| `business_rules_analyzer` | coleta de **localizações candidatas** (condicionais/validação densas perto de vocabulário de domínio) com trecho literal | extrair a regra em si é síntese semântica — exatamente o que o requisito proíbe | a tool **não tem campo para descrever a regra em prosa**. Devolve só `{file, line, snippet, confidence: LOW}`; a interpretação cabe a quem chama |
| `security_analyzer` | grep de padrões conhecidos (`eval`/`exec`, `shell=True`, `password=`/`SECRET` hardcoded) com evidência literal | taint analysis real é data flow — mesma limitação | v1 = detecção de **padrão**, não vulnerabilidade confirmada. `scope_limitations` deve dizer isso explicitamente |
| `improvement_analyzer` | métricas estruturais (arquivo/função longos, contagem de `TODO`/`FIXME`) | juízo de qualidade de design | reporta métrica + evidência; nunca "isto é ruim" |
| `test_analyzer` | razão arquivo-de-teste/arquivo-de-fonte, convenção de nome, contagem de `assert`/`expect` | nada | **única tool de Camada 3 sem risco de fronteira** — pode ir cedo. Análise **estática**: nunca executar código do repo-alvo |
| `generate_mermaid` e diagramas | serialização mecânica de grafo já produzido pelas Camadas 2-3 | nada | tool "burra" por design. Obrigada a tornar a confiança visível: **aresta tracejada para `LOW`/`MEDIUM`, sólida para `HIGH`** |
| Camada 5 (`generate_project_report`, `generate_architecture_documentation`, `generate_project_summary`) | templating puro sobre o envelope acima | nada | nenhuma lógica de análise nova. Só existe depois que as Camadas 1-4 emitem o contrato padronizado |

### 4. Módulos

```
src/ai_dev_lab/project_intelligence/
    __init__.py
    __main__.py         # entrypoint: parsing de --root, sobe o loop stdio
    config.py           # resolve e valida projectRoot (cwd, ou --root), falha rápido
    protocol.py         # dispatch JSON-RPC + loop stdio
    paths.py            # confinamento de path contra projectRoot
    exploration.py      # Camada 1 — Milestone 1
    understanding.py    # Camada 2 — Milestone 2 (não criado ainda)
    analysis.py         # Camada 3 — Milestone 3 (não criado ainda)
    visualization.py    # Camada 4 — Milestone 4 (não criado ainda)
    documentation.py    # Camada 5 — Milestone 5 (não criado ainda)
```

Primeira vez que o repositório deixa de ser inteiramente flat. Justificado por escala:
~20 tools em 5 camadas não cabe honestamente num único arquivo do jeito que `parity.py`
cabe. Apenas `__main__.py`, `config.py`, `protocol.py`, `paths.py` e `exploration.py`
são criados nas etapas detalhadas abaixo — os demais são nomeados só para deixar a
intenção legível, evitando abstração antes da segunda necessidade real.

`paths.py` existe como módulo isolado desde o dia 1 porque **toda** tool de leitura
precisa do mesmo primitivo de confinamento. Concentrar isso num único lugar é também a
única forma sensata de revisar segurança de acesso a arquivo.

`config.py` é separado de `__main__.py` de propósito: a resolução do `projectRoot` é
função pura sobre `argv` e `cwd`, testável sem subir processo nenhum. O `__main__.py`
fica sendo só a casca que lê `sys.argv`/`os.getcwd()`, monta o `context` e chama. É
também `config.py` quem monta o mapeamento `roots` de uma entrada — a costura de
múltiplos projetos fica concentrada num arquivo, não espalhada.

### Fora de escopo, explicitamente

`resources`, `prompts` e negociação de capacidades além do mínimo. A capability `roots`
fica registrada como incremento futuro, não como requisito de v1. Isso precisa continuar
declarado como não-objetivo em cada milestone, ou o projeto cresce silenciosamente além
de "poucas sessões" por etapa.

---

## Implementation Plan

Cada milestone é um `/feature` completo e independente
(`planner` → `python-developer` → `tester` → `reviewer`), respeitando o limite de
2 rodadas de correção por etapa.

### Milestone 0 — configuração + esqueleto do protocolo

Menor fatia possível que prova a arquitetura de ponta a ponta.

1. `config.py`: `resolve_project_root(args, cwd) -> Path` — usa o `cwd` por padrão,
   aceita `--root` como override opcional, valida que existe e é diretório, levanta erro
   de configuração se não. Função pura sobre os argumentos recebidos, sem tocar `sys` —
   testável sem subprocess. Monta também o `context` na forma
   `{"roots": {"default": <raiz>}}`, com uma entrada só.
2. `protocol.py`: `dispatch(request, context)` e
   `serve_stdio(input_stream, output_stream, context)`. O `context` carrega o
   `projectRoot` já resolvido, sempre como mapeamento — nunca `Path` solto. Streams como
   parâmetro (não `sys.stdin`/`sys.stdout` fixos) — é o que torna o loop testável com
   `io.StringIO` sem subprocess real.
3. Implementar `initialize` com o **payload padrão do MCP** — responder
   `protocolVersion`, `capabilities` e `serverInfo`. `initialize` não recebe nem precisa
   de `projectRoot`.
4. Implementar `tools/list` (retorna só o que já existe) e a regra de sequenciamento:
   `tools/call` antes do handshake é erro estruturado.
5. Uma única tool real para provar o fio: `project_info` — contagem de arquivos por
   extensão, total de linhas, presença de manifestos conhecidos. Retrieval pura, sem
   envelope de confiança.
6. Códigos de erro JSON-RPC padrão: `-32700` parse error, `-32600` invalid request,
   `-32601` method not found, `-32602` invalid params, `-32603` internal error.
7. `__main__.py`: lê `sys.argv` e `os.getcwd()`, chama `config.resolve_project_root`,
   e sobe `serve_stdio` com o `context` montado. Casca fina, sem lógica própria.
   **Nenhuma tool expõe parâmetro de raiz** — a costura de múltiplos projetos para na
   forma do `context`.

### Milestone 1 — Camada Exploração completa

8. `paths.py`: `resolve_within(project_root, relative_path) -> Path`, rejeitando path
   absoluto de entrada e qualquer resultado fora de `project_root`
   (`is_relative_to`, disponível a partir do Python 3.9).
9. `list_files` — `os.walk`/`pathlib.rglob`, ignorando `.git/` sempre. Respeito
   best-effort a um `.gitignore` de topo se existir (glob simples, **não** a spec
   completa — documentar a limitação, não fingir compliance total).
10. `read_file` — usa `paths.resolve_within`. Erro estruturado (nunca stack trace com
    caminho absoluto, que vazaria estrutura da máquina) para: fora da raiz, inexistente,
    é diretório, não-UTF8.
11. `search_code` — `re` da stdlib, com limite de tamanho de arquivo e cap explícito de
    resultados (ex.: 200 ocorrências), pulando arquivos binários por heurística de byte
    nulo.
12. `project_profile` — agrega `project_info` + `list_files` (maiores diretórios,
    extensão mais comum). Ainda retrieval pura.
13. Atualizar `README.md` e `CLAUDE.md` na mesma tarefa, porque um diretório novo foi
    criado — exigido pelo próprio contrato em `python-developer.md:190-191`.
14. Documentar em `README.md` o bloco de `claude_desktop_config.json` necessário para
    apontar o servidor a um projeto-alvo — sem isso, ninguém consegue usar o que foi
    construído.

### Milestones 2-5 — não detalhados aqui

Grandes e arriscados o bastante para merecer plano próprio, cada um reaberto como
ciclo de planejamento dedicado quando chegar a vez:

| Milestone | Escopo | Observação |
|---|---|---|
| 2 | resto da Camada 2: `architecture_explainer`, `code_structure_analyzer`, `dependency_analyzer` completo | inclui decidir o fork "heurística agnóstica (`MEDIUM`)" vs. "`ast` só para Python (`HIGH`)", e a questão do TOML |
| 3 | `data_flow_analyzer` e `business_rules_analyzer` | fronteira epistemológica mais arriscada do projeto; candidato natural a sessão de brainstorming antes de virar plano |
| 4 | Camada 3 completa: `security_analyzer`, `improvement_analyzer`, `test_analyzer` | `test_analyzer` pode ser antecipado — não tem risco de fronteira |
| 5 | Camadas 4 e 5: geradores Mermaid e documentação | depende de 2-4 estáveis; visualização só serializa `findings` já produzidos |

---

## Testing Strategy

Comando canônico, conforme `CLAUDE.md:31-40`:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Estrutura de testes espelhando a de produção:

```
tests/project_intelligence/
    __init__.py
    test_config.py
    test_protocol.py
    test_paths.py
    test_exploration.py
    fixtures/fake_project/
```

### A fixture é obrigatória, não opcional

Como estas tools apontam para um `project_root` **arbitrário**, testá-las só contra o
próprio AI Dev Lab — que é Python puro — **não prova agnosticismo nenhum**. É necessário
criar uma fixture sintética multi-linguagem em
`tests/project_intelligence/fixtures/fake_project/` contendo:

- um arquivo `.py`
- um arquivo `.js`
- um `package.json`
- um subdiretório aninhado
- um arquivo binário

Sem essa fixture, "agnóstico de linguagem" é uma alegação não testada — exatamente o
tipo de lacuna que o `reviewer` deveria pegar.

### Casos a cobrir

**`test_config.py`** — a correção arquitetural desta revisão precisa de teste próprio
- sem `--root` → resolve para o `cwd` recebido. **Este é o caminho padrão da v1**, então
  é o primeiro teste, não um caso de borda
- `cwd` inexistente, ou apontando para arquivo em vez de diretório → erro de configuração
- `--root <path válido>` → resolve para esse path
- `--root` presente **e** `cwd` diferente → `--root` ganha (prova a precedência)
- `--root` apontando para path inexistente ou para arquivo → erro de configuração
- path relativo em `--root` → resolvido para absoluto, não usado cru
- o `context` montado expõe a raiz sob `roots["default"]` — teste que trava a **forma do
  mapeamento**, para que acrescentar uma segunda raiz depois não exija reescrever
  assinatura de tool nenhuma

**`test_protocol.py`**
- `initialize` com o payload padrão do MCP → resposta contém `protocolVersion`,
  `capabilities`, `serverInfo`
- `initialize` **sem** `projectRoot` no payload → funciona normalmente. Este teste existe
  especificamente para travar a regressão que esta revisão corrigiu: se alguém voltar a
  ler `projectRoot` do payload, este teste quebra
- requisição válida → envelope JSON-RPC correto
- método desconhecido → `-32601`
- notificação (sem `id`) → nenhuma resposta escrita
- linha malformada seguida de linha válida → erro para a primeira, resposta correta para
  a segunda (prova de que o loop não quebra)
- `tools/call` antes do handshake de `initialize` → erro estruturado, não crash

**`test_paths.py`**
- `../../etc/passwd` → rejeitado
- path absoluto de entrada → rejeitado
- symlink saindo da fixture → rejeitado
- path legítimo dentro da raiz → resolvido

**`test_exploration.py`**
- `list_files` ignora `.git/`
- `search_code` respeita o cap de resultados e não trava com regex custosa
- `search_code` pula arquivo binário
- `read_file` com path fora da raiz → erro estruturado, sem caminho absoluto na mensagem
- `read_file` em diretório, inexistente, não-UTF8 → erro estruturado
- `project_info`/`project_profile` sobre diretório vazio → contagens zeradas, sem quebrar

### Verificação manual, fora da suíte

Um critério que teste automatizado não cobre: o servidor precisa **conectar de verdade**
num cliente MCP real. Configurar o bloco de `claude_desktop_config.json` e confirmar que
o Claude Desktop lista as tools é a única prova de que o handshake está correto. Um
servidor que passa 100% dos testes e não aparece no cliente não está pronto.

### Regressão

`tests/test_parity.py` deve continuar 100% verde em todas as etapas — nenhuma mudança
em `parity.py`.

---

## Risks

- **Extensão inventada do protocolo — risco já materializado e corrigido nesta revisão.**
  A versão anterior deste plano punha `projectRoot` dentro do payload de `initialize`,
  que não é campo da especificação MCP. Teria produzido um servidor verde nos testes e
  inerte no Claude Desktop. Corrigido em `Proposed Architecture §1`, com teste de
  regressão explícito em `test_protocol.py`. Lição a carregar para os próximos
  milestones: **toda extensão do protocolo precisa ser checada contra a especificação
  antes de virar teste**, senão o teste só confirma a invenção.

- **Generalidade especulativa na costura de múltiplos projetos.** A preparação pedida é
  legítima, mas tem limite exato: `context` com mapeamento de uma entrada e raiz passada
  por parâmetro custam zero e não criam caminho não exercitado. Qualquer coisa além disso
  — parâmetro `root_id` no schema das tools, resolver com lista, branch para "múltiplas
  raízes" — é código sem nenhum teste que o exercite, e contraria a regra de abstração na
  segunda ocorrência. O `reviewer` deve tratar esse excesso como achado, não como zelo.

- **Não existe parser TOML na stdlib desta máquina.** `tomllib` entrou na stdlib apenas
  no Python 3.11. Verificado: `python3 → 3.9.6`, `import tomllib → ModuleNotFoundError`.
  Isso atinge `dependency_analyzer` diretamente ao ler `pyproject.toml` de um
  projeto-alvo. Decisão fica para quando o Milestone 2 for planejado.

- **O risco epistemológico está concentrado em `data_flow_analyzer` e
  `business_rules_analyzer`.** Implementados "genericamente" como o nome sugere, ambos
  violariam o requisito central de não inventar relação causal nem regra de negócio.
  Mitigação já embutida na arquitetura proposta: rescopar (call graph Python-only;
  candidatos com trecho literal e sem campo de interpretação) e adiar para milestone
  com plano próprio.

- **Confinamento de path continua sendo o maior risco de segurança**, mesmo com
  `projectRoot` vindo de configuração em vez de payload. A raiz agora é confiável (quem
  configura o servidor é quem o instala), mas os **paths pedidos pelas tools** continuam
  vindo do cliente: symlink apontando para fora, path absoluto disfarçado, `..`
  normalizado tarde. Candidato natural a achado `BLOQUEANTE` do `reviewer` — e por ser
  genuíno, não fabricado, serve bem ao objetivo do laboratório.

- **`except Exception:` no loop de dispatch.** Tensão real entre robustez do loop (não
  pode cair a cada erro de tool) e a proibição de captura ampla no padrão Python da
  organização. Resolução recomendada: um tipo de exceção específico (`ToolError`)
  levantado deliberadamente pelas tools para erros esperados, deixando exceções
  verdadeiramente inesperadas propagarem. A decisão e a justificativa cabem ao
  `python-developer`, não a este plano.

- **`.gitignore` respeitado só parcialmente** em `list_files`/`search_code` — glob
  simples, não a spec completa. Deve ir declarado no `scope_limitations` do retorno,
  não escondido.

- **Custo em repositório grande.** `list_files` e `search_code` sobre um repo real podem
  ser O(n) descontrolado. O cap de resultados e o limite de tamanho de arquivo são
  requisito, não otimização — e devem ser testados.

- **`unittest.TestLoader().discover()` não levanta exceção em módulo com erro de import** —
  ele sintetiza um teste falho especial (`unittest.loader._FailedTest`, confirmado
  presente na stdlib desta máquina). Se `test_analyzer` vier a inspecionar suítes, esse
  comportamento pode confundir; é um bug plausível de escapar.

- **Premissas sobre o comportamento do cliente MCP são o risco mais caro deste projeto,
  e duas já se materializaram.** O payload de `initialize` (pego em revisão de plano) e o
  `cwd` no `mcpServers` (pego só ao conectar de verdade — ver a nota em
  `Proposed Architecture §1`). As duas passariam por 100% dos testes automatizados. Regra
  a carregar: **toda suposição sobre o que o cliente faz precisa ser verificada contra a
  especificação ou contra um cliente real antes de virar documentação.** Um teste escrito
  a partir da suposição só confirma a suposição.

- **A capability `roots` fica sem cobertura na v1.** É o mecanismo padronizado do MCP
  para o cliente informar diretórios em escopo, e a ausência dela significa que trocar
  de projeto-alvo exige editar o `--root` no `claude_desktop_config.json` e reiniciar o
  app com `Cmd+Q`. Aceitável para v1, mas é
  limitação real de usabilidade — não deve ser esquecida como se fosse detalhe. É também
  o caminho natural para a evolução de múltiplos projetos: quando ela for implementada,
  o mapeamento `roots` do `context` passa a ser alimentado por `roots/list` em vez de
  ter uma entrada fixa. Nenhum mecanismo próprio deve ser inventado no lugar dela.

- **Nenhuma dependência nova é justificada nesta fase.** Milestone 0 e 1 usam apenas
  `json`, `re`, `os`, `pathlib`, `io`, `argparse`, `unittest` e `ast` — tudo stdlib.
  Qualquer dependência (`tomli` para TOML, parser real de outra linguagem) é decisão a
  ser tomada e justificada contra o `CLAUDE.md` só quando o milestone que precisar dela
  for planejado.

---

## Definition of Done

Alinhado ao Definition of Done do `CLAUDE.md:42-48`, aplicado a **Milestone 0 + 1** — o
único escopo executável agora. Uma etapa só está pronta quando todas as condições valem
para o que ela entrega:

1. `config.py`, `protocol.py`, `paths.py`, `exploration.py` e `__main__.py`
   implementados, **somente com stdlib**, expondo `initialize`, `tools/list` e
   `tools/call` para `project_info`, `list_files`, `read_file`, `search_code` e
   `project_profile`.
2. `initialize` implementado com o payload padrão do MCP. **Nenhum campo inventado.**
   `projectRoot` resolvido a partir do `cwd` do processo — com `--root` como override
   opcional — na inicialização, e o teste de regressão de `test_protocol.py` provando
   que o payload de `initialize` não é consultado para isso.
3. **Costura de múltiplos projetos presente, e nada além dela.** O `context` tem a forma
   `{"roots": {"default": <raiz>}}` com uma entrada, e toda tool recebe a raiz por
   parâmetro. Simultaneamente: nenhum parâmetro `root`/`root_id` no schema das tools,
   nenhum resolver multi-caminho, nenhum branch para uma segunda raiz. **Implementar a
   evolução agora reprova o milestone tanto quanto não deixar a costura.**
4. Fixture multi-linguagem criada em `tests/project_intelligence/fixtures/fake_project/`
   e usada para provar que as tools funcionam apontadas para um projeto que **não é** o
   AI Dev Lab.
5. Testes cobrindo caminho feliz, resolução por `cwd` e precedência do `--root`,
   confinamento de path com tentativa de escape, sequenciamento antes do handshake, a
   forma do mapeamento `roots`, e os edge cases listados em Testing Strategy.
6. `PYTHONPATH=src python3 -m unittest discover -s tests` passando 100%, com a saída real
   — copiada, não parafraseada — anexada como evidência pelo `tester`.
7. Nenhuma regressão em `parity.py`/`test_parity.py`.
8. `README.md` e `CLAUDE.md` atualizados para refletir o novo diretório
   `project_intelligence/`, incluindo o bloco de `claude_desktop_config.json` — com
   `cwd` — necessário para apontar o servidor a um projeto-alvo.
9. Nenhuma dependência nova adicionada. Em particular, `tomllib`/`tomli` **não** entra
   nesta fase.
10. Verificação manual registrada: o servidor conecta num cliente MCP real e as tools
    aparecem listadas. Teste verde sem essa confirmação não fecha o milestone.
11. Pipeline `/feature` executado de ponta a ponta, com pelo menos um achado real do
    `reviewer` classificado (`BLOQUEANTE` ou `IMPORTANTE`) — idealmente sobre o
    confinamento de path — resolvido dentro do limite de 2 rodadas, ou escalado ao humano
    conforme `feature.md:14-15` se não convergir. Qualquer um dos dois desfechos conta
    como pronto, já que o critério de sucesso do laboratório é exercitar o pipeline, não
    apenas obter verde.
12. Milestones 2-5 permanecem explicitamente fora de escopo e não começam sem um novo
    ciclo de planejamento dedicado a cada um.

