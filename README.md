# Bot de Orçamento

Bot que **lê e entende qualquer estrutura orçamentária**, mostra **várias adaptações (cenários)** do
orçamento, aponta **onde reduzir custos e quais as oportunidades**, e entrega tudo num **relatório HTML
com controle de revisões** — revisado automaticamente lendo o próprio arquivo HTML antes da entrega.

Funciona sozinho pela linha de comando (motor determinístico em Python) e como **agente do Claude Code**
(`bot-orcamento`), que opera o motor, interpreta os resultados, escreve o parecer e **cria skills novas**
quando o orçamento exige.

```bash
pip install -r requirements.txt
python -m bot_orcamento exemplos                                   # bases de demonstração (fictícias)
python -m bot_orcamento analisar exemplos/orcamento_opex_mina_2026.xlsx --pdf
```

Um relatório de demonstração já gerado está em
[`exemplos/relatorio-demo/`](exemplos/relatorio-demo/) (dados fictícios).

---

## O que o bot faz

| Etapa | O que acontece |
|---|---|
| **Lê** | XLSX/XLSM, CSV/TXT (`;` ou `,`, decimal pt-BR), PDF (tabelas), JSON; XLS/ODS com leitor instalado. Formatos novos via skill `leitor`. |
| **Entende** | Acha a aba e a linha de cabeçalho (mesmo com título/linhas em branco antes), cabeçalho em duas linhas, mapeia colunas pelo rótulo **e** pelo conteúdo (código, descrição, centro de custo, fornecedor, qtd × preço, meses, orçado × realizado × ano anterior pelos anos), pivota arquivos de lançamentos. Separa **itens de subtotais/total** (por descrição, hierarquia de código, soma do bloco e negrito), concilia com o total do arquivo e aponta problemas de qualidade. |
| **Classifica** | 29 categorias de custo (inclui mineração: perfuração e desmonte, pneus OTR, combustíveis, locação de equipamentos…), perfil fixo/variável, discricionário, protegido. |
| **Detecta oportunidades** | 10 detectores nativos + os de skills: alavancas por categoria, horas extras × folha, folga de execução (orçado × realizado), crescimento acima da inflação, duplicidades, dispersão de preço unitário, fragmentação de fornecedores, picos mensais e dezembro inflado, estimativas sem memória de cálculo, rubricas genéricas/contingência. |
| **Adapta (cenários)** | Conservador, Base (recomendado), Agressivo, Ganhos rápidos, Base zero nos discricionários, Meta de X%, Corte linear (comparativo) e Realinhamento ao realizado — **linha a linha**, sem dupla contagem: `1 − Π(1 − rᵢ)` com teto por linha. |
| **Relata** | HTML autocontido (abre sem internet) no padrão visual da equipe, com 10 seções, simulador interativo, plano de ação editável (salvar/carregar base em JSON), exportação CSV, impressão A4; Excel com o orçamento adaptado por cenário; `analise.json`; PDF opcional. |
| **Revisa** | Lê o **arquivo HTML final** e confere 26 itens: estrutura, cada número exibido × dado, recálculo independente dos cenários, formato pt-BR, artefatos (NaN/undefined), e no Chromium: erros de JS, simulador = cenário base, interatividade, celular sem rolagem lateral. Reimprime o checklist no relatório e confere de novo até estabilizar. |
| **Controla revisões** | `historico_revisoes.json`: Rev. 00, 01… com data, descrição e **o que mudou** (dados, premissas, oportunidades, economia). Sem mudança → reemite a mesma revisão. |

## Relatório (10 seções)

1. **Resumo executivo** — total, faixa de redução por cenário, maiores oportunidades, parecer.
2. **Como o bot leu o orçamento** — arquivo, cabeçalho, o que cada coluna significa e por quê, conciliação, subtotais fora da soma, qualidade dos dados.
3. **Raio-X** — categorias, concentração (Pareto), perfil fixo/variável, distribuição mensal, maiores linhas.
4. **Oportunidades** — tabela + cartões com evidência (linhas da planilha), faixa conservador/base/agressivo, ação, indicador.
5. **Cenários** — comparação, de onde vem a redução, orçamento adaptado linha a linha.
6. **Simulador** — liga/desliga cada oportunidade e muda a intensidade; mesma regra de sobreposição.
7. **Plano de ação** — por prazo, com responsável/data/status editáveis.
8. **Riscos** — estouros previstos, linhas novas sem histórico, qualidade de dados, protegidas.
9. **Premissas e metodologia** — todas as premissas, faixas por categoria, detectores e skills.
10. **Controle de revisões** — histórico e checklist da revisão automática.

## Comandos

```bash
python -m bot_orcamento estrutura <arquivo>              # só mostra como o arquivo foi entendido
python -m bot_orcamento analisar <arquivo> [opções]      # análise + relatório revisado
python -m bot_orcamento revisar <relatorio.html> --fonte <arquivo>
python -m bot_orcamento nova-skill <nome> --tipo detector|leitor|taxonomia|cenario|instrucoes
python -m bot_orcamento skills                           # detectores e skills carregadas
```

Opções de `analisar`: `--aba` (nome, lista ou `todas`), `--mapa campo=COLUNA` (corrige o mapeamento),
`--titulo`, `--data-base`, `--meta 0.12`, `--ipca 0.05`, `--config premissas.json`,
`--parecer parecer.md`, `--descricao-revisao "..."`, `--pdf`, `--ia`, `--sem-navegador`, `--sem-excel`,
`--saida <pasta>` (padrão `relatorios/<titulo>/`). Código de saída 2 = relatório reprovado na revisão.

### Premissas

Todas em [`bot_orcamento/config.py`](bot_orcamento/config.py), sobrescrevíveis por JSON:

```json
{
  "ipca": 0.05,
  "meta_reducao": 0.12,
  "faixas": {"viagens": [0.2, 0.3, 0.5], "combustiveis": [0.02, 0.04, 0.07]},
  "palavras_extras": {"perfuracao_desmonte": ["umb", "furo*"]},
  "protegidas": ["ssma", "impostos", "depreciacao", "financeiras"]
}
```

As faixas de redução por categoria são **referências** usuais de programas de redução de custos, não
fatos sobre o seu orçamento — o relatório lista cada uma (seção 09) para que possam ser ajustadas.

### Camada de IA (opcional, `--ia`)

Com `pip install anthropic` e credencial (`ANTHROPIC_API_KEY` ou `ant auth login`), o bot usa Claude
(`claude-opus-5-5`, configurável por `BOT_ORCAMENTO_MODELO`) para classificar linhas que a taxonomia
não reconheceu e redigir o parecer executivo. Saída estruturada por JSON Schema; fallback de recusa
no servidor ligado (`server-side-fallback-2026-07-01`, `fallbacks: "default"`). A IA **não altera
números**: o parecer passa pela verificação V20 (todo R$ citado precisa existir na análise).
**Atenção:** `--ia` envia descrições e valores do orçamento à API da Anthropic.

## Uso com o Claude Code (o "bot")

- **Agente** [`.claude/agents/bot-orcamento.md`](.claude/agents/bot-orcamento.md): fluxo completo —
  entender → analisar → ler resultados → criar skills se preciso → parecer → revisar → entregar.
- **Skills**:
  - [`analise-orcamentaria`](.claude/skills/analise-orcamentaria/SKILL.md) — como operar e interpretar (`/analise-orcamentaria`).
  - [`revisao-relatorio-html`](.claude/skills/revisao-relatorio-html/SKILL.md) — protocolo de revisão antes de entregar.
  - [`criar-skill-orcamento`](.claude/skills/criar-skill-orcamento/SKILL.md) — como o bot cria skills novas (contratos, testes).
  - [`compras-emergenciais`](.claude/skills/compras-emergenciais/SKILL.md) — exemplo de skill criada pelo próprio bot
    (`nova-skill`), já carregada pelo motor.

### Criação de skills

O motor carrega sozinho, de `.claude/skills/*/`, qualquer `detector.py` (nova regra de economia),
`leitor.py` (novo formato), `categorias.json` (taxonomia da empresa) ou `cenario.py` (novo cenário).
`nova-skill` gera o esqueleto + `SKILL.md` + teste. Skill com erro não derruba o bot: aparece como
"erro" na seção 09.

### Permissões sugeridas (opcional)

Para o agente rodar o bot e criar skills sem pedir confirmação a cada passo, um responsável pelo
repositório pode adicionar ao `.claude/settings.json` do projeto:

```json
{
  "permissions": {
    "allow": [
      "Bash(python -m bot_orcamento *)",
      "Bash(python3 -m bot_orcamento *)",
      "Bash(python -m pytest *)",
      "Bash(python3 -m pytest *)",
      "Edit(.claude/skills/**)",
      "Edit(relatorios/**)"
    ]
  }
}
```

`Edit(...)` cobre criar e editar arquivos naquelas pastas. Sem isso, tudo funciona igual — o Claude
Code apenas pede confirmação.

## Estrutura do código

```
bot_orcamento/
  leitura.py      grade bruta → aba, cabeçalho, mapeamento de colunas, linhas (largo e longo)
  estrutura.py    itens × subtotais, hierarquia, conciliação, qualidade, classificação
  taxonomia.py    29 categorias, palavras-chave, faixas e alavancas
  detectores/     10 detectores nativos + carregador de skills
  cenarios.py     cenários e regra de sobreposição
  analise.py      orquestração, priorização, insights
  relatorio/      render (Jinja2), template HTML, gráficos SVG, pipeline gerar→revisar→reimprimir
  revisor.py      revisão do HTML final (estática + Chromium via Playwright)
  revisoes.py     histórico Rev. 00, 01…
  excel.py · saida.py · ia.py · skills.py · cli.py · exemplos.py
tests/            74 testes (leitura, estrutura, detectores, cenários, relatório, revisor, IA, skills)
```

Testes: `python -m pytest` (inclui os testes das skills em `.claude/skills/`).
A revisão no navegador usa Playwright (Python ou Node); sem ele, as verificações de navegador aparecem
como "pulado" e as demais continuam valendo.
