"""Criação de skills pelo bot.

Uma skill é uma pasta em ``.claude/skills/<nome>/`` com um ``SKILL.md`` (instruções que o
Claude Code carrega) e, opcionalmente, código que o motor do bot carrega sozinho:

* ``detector.py``      — nova regra de oportunidade de redução
* ``leitor.py``        — novo formato de arquivo de orçamento
* ``categorias.json``  — categorias/palavras-chave da empresa (taxonomia)
* ``cenario.py``       — novo cenário de adaptação do orçamento
* (só ``SKILL.md``)    — instruções/procedimento, sem código

Toda skill com código ganha também um ``test_skill.py`` que roda com ``python -m pytest``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .util import normalizar


def _id(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalizar(nome)).strip("_") or "skill"


def _pasta_nome(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(nome)).strip("-") or "skill"


SKILL_MD = """---
name: {pasta}
description: {descricao}
---

# {titulo}

{descricao}

## Tipo

{tipo_txt}

## Como o bot usa esta skill

{uso}

## Manutenção

- Contrato e exemplos: `.claude/skills/criar-skill-orcamento/SKILL.md`.
- Teste: `python -m pytest {pasta_rel}` — mantenha verde antes de gerar relatório.
- Depois de alterar, gere o relatório de novo: a seção "Premissas" lista as skills carregadas e
  a "Controle de revisões" registra a mudança.
"""

DETECTOR_PY = '''"""{descricao}"""

from __future__ import annotations

from bot_orcamento.modelo import Alerta, Oportunidade  # noqa: F401
from bot_orcamento.util import brl, normalizar, pct  # noqa: F401

ID = "{id}"
NOME = "{titulo}"
DESCRICAO = "{descricao}"
# Dados de que o detector precisa (chaves de ctx.estrutura.tem): "realizado", "ano_anterior", "meses",
# "meses_realizado", "fornecedor", "centro_custo", "preco_unitario", "projetado". Vazio = sempre roda.
REQUER: list[str] = []


def detectar(ctx) -> list[Oportunidade]:
    """Devolve oportunidades. Disponível em ``ctx``:

    ctx.itens            linhas do orçamento (bot_orcamento.modelo.Linha), já sem subtotais
    ctx.total            total orçado
    ctx.premissas        dict de premissas (config.py + --config)
    ctx.taxonomia        categorias (ctx.taxonomia.get(id).faixa / .nome / .protegida)
    ctx.por_categoria()  {{categoria: [linhas]}}
    ctx.em_estouro(l)    True se a linha já executa acima do orçado
    ctx.linhas_oportunidade(linhas, (conservador, base, agressivo))  monta as taxas por linha
    ctx.alertar(Alerta(titulo=..., detalhe=..., severidade="media"))  registra risco (não economia)
    """
    # TODO: troque o critério abaixo pela regra desta skill.
    selecionadas = [x for x in ctx.itens if x.orcado > 0 and not x.protegida and False]
    if not selecionadas:
        return []
    soma = sum(x.orcado for x in selecionadas)
    return [Oportunidade(
        detector=ID,
        titulo=NOME,
        racional=f"{{len(selecionadas)}} linha(s) somando {{brl(soma)}} atendem ao critério desta skill.",
        acao="Descreva a ação recomendada, quem executa e como medir.",
        linhas=ctx.linhas_oportunidade(selecionadas, (0.02, 0.05, 0.08)),
        confianca="media", esforco="medio", horizonte="medio",
        evidencias=[f"Linha {{x.linha_origem}}: {{x.rotulo}} — {{brl(x.orcado)}}" for x in selecionadas][:12],
        indicador="Indicador de acompanhamento",
    )]
'''

LEITOR_PY = '''"""{descricao}"""

from __future__ import annotations

from pathlib import Path


def pode_ler(caminho: Path) -> bool:
    """True se este leitor reconhece o arquivo (pela extensão, nome ou conteúdo)."""
    # TODO: ajuste o critério.
    return caminho.suffix.lower() == ".exemplo"


def ler(caminho: Path):
    """Devolve um pandas.DataFrame com UMA linha de cabeçalho nas colunas (ex.: Código, Descrição,
    Orçado, Realizado, Jan…Dez). O bot cuida do resto: mapeamento, subtotais, classificação."""
    import pandas as pd

    # TODO: converta o formato para tabela.
    return pd.DataFrame(columns=["Código", "Descrição", "Orçado"])
'''

CENARIO_PY = '''"""{descricao}"""

ID = "{id}"
NOME = "{titulo}"
DESCRICAO = "{descricao}"


def selecionar(oportunidade):
    """Para cada oportunidade, devolva "conservador", "base", "agressivo" ou None (fora do cenário).

    Campos úteis: oportunidade.categoria, .detector, .confianca, .esforco, .horizonte, .economia("base")
    """
    # TODO: regra do cenário.
    if oportunidade.esforco == "baixo":
        return "base"
    return None
'''

TESTE_PY = '''"""Teste da skill {pasta}. Rode com: python -m pytest {pasta_rel}"""

from pathlib import Path

from bot_orcamento.analise import analisar
from bot_orcamento.exemplos import gerar_todos

PASTA_SKILLS = Path(__file__).resolve().parents[1]


def test_skill_carrega_e_roda(tmp_path):
    arquivos = gerar_todos(tmp_path)
    a = analisar(arquivos[0], pastas_skills=[PASTA_SKILLS], log=lambda *x: None)
    minha = [s for s in a.skills if s["nome"] == "{pasta}"]
    assert minha, "skill não foi encontrada pelo motor"
    assert all(s["status"] == "carregada" for s in minha), minha
    erros = [d for d in a.detectores if d["status"] == "erro"]
    assert not erros, erros
'''

TIPO_TXT = {
    "detector": "Detector de oportunidade (`detector.py`) — carregado automaticamente pelo motor.",
    "leitor": "Leitor de formato de arquivo (`leitor.py`) — usado antes dos leitores nativos.",
    "taxonomia": "Taxonomia (`categorias.json`) — categorias e palavras-chave da empresa.",
    "cenario": "Cenário de adaptação (`cenario.py`) — aparece na seção de cenários e no simulador.",
    "instrucoes": "Instruções/procedimento (só `SKILL.md`) — orienta o agente; o motor não executa código.",
}
USO = {
    "detector": "O motor executa `detectar(ctx)` junto com os detectores nativos; as oportunidades entram "
                "na priorização, nos cenários, no simulador e na revisão do HTML.",
    "leitor": "Se `pode_ler(arquivo)` for verdadeiro, o bot usa `ler(arquivo)` para obter a tabela e segue "
              "com a leitura de estrutura normal.",
    "taxonomia": "As categorias entram antes das nativas (são mais específicas). Uma categoria com id já "
                 "existente só acrescenta palavras-chave.",
    "cenario": "O cenário é montado com a mesma regra de sobreposição dos demais.",
    "instrucoes": "O agente `bot-orcamento` lê este arquivo quando a situação descrita acontecer.",
}


def criar_skill(nome: str, tipo: str, descricao: str, pasta_skills: str | Path) -> list[Path]:
    if tipo not in TIPO_TXT:
        raise ValueError(f"tipo inválido: {tipo}")
    pasta_skills = Path(pasta_skills)
    pasta = pasta_skills / _pasta_nome(nome)
    if pasta.exists() and any(pasta.iterdir()):
        raise RuntimeError(f"A skill já existe: {pasta}")
    pasta.mkdir(parents=True, exist_ok=True)
    descricao = (descricao or f"Skill {nome} do Bot de Orçamento.").replace('"', "'").strip()
    titulo = nome.replace("-", " ").replace("_", " ").strip().capitalize()
    try:
        pasta_rel = pasta.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        pasta_rel = pasta
    fmt = dict(pasta=pasta.name, descricao=descricao, titulo=titulo, id=_id(nome), tipo_txt=TIPO_TXT[tipo],
               uso=USO[tipo], pasta_rel=pasta_rel)
    criados = [pasta / "SKILL.md"]
    criados[0].write_text(SKILL_MD.format(**fmt), encoding="utf-8")
    if tipo == "detector":
        (pasta / "detector.py").write_text(DETECTOR_PY.format(**fmt), encoding="utf-8")
        criados.append(pasta / "detector.py")
    elif tipo == "leitor":
        (pasta / "leitor.py").write_text(LEITOR_PY.format(**fmt), encoding="utf-8")
        criados.append(pasta / "leitor.py")
    elif tipo == "cenario":
        (pasta / "cenario.py").write_text(CENARIO_PY.format(**fmt), encoding="utf-8")
        criados.append(pasta / "cenario.py")
    elif tipo == "taxonomia":
        exemplo = [{"id": _id(nome), "nome": titulo, "palavras": ["termo exemplo*"], "faixa": [0.03, 0.06, 0.10],
                    "comportamento": "variavel", "discricionaria": False, "protegida": False, "esforco": "medio",
                    "horizonte": "medio", "confianca": "media", "alavanca": f"Alavanca de {titulo.lower()}",
                    "acoes": ["Descreva a ação"], "indicador": "Indicador"}]
        (pasta / "categorias.json").write_text(json.dumps(exemplo, ensure_ascii=False, indent=2), encoding="utf-8")
        criados.append(pasta / "categorias.json")
    if tipo != "instrucoes":
        (pasta / "test_skill.py").write_text(TESTE_PY.format(**fmt), encoding="utf-8")
        criados.append(pasta / "test_skill.py")
    return criados
