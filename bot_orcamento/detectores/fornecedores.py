"""Fragmentação de fornecedores para o mesmo tipo de gasto."""

from __future__ import annotations

import re

from ..modelo import Oportunidade
from ..util import brl, normalizar, pct

ID = "fragmentacao_fornecedores"
NOME = "Fragmentação de fornecedores"
DESCRICAO = "Mesmo tipo de gasto dividido entre três ou mais fornecedores: consolidar volume e renegociar."
REQUER = ["fornecedor"]

GENERICOS = {"diversos", "varios", "a definir", "indefinido", "outros", "nd", "n a", "na", "sem fornecedor"}
PARADAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "com", "servico", "servicos"}


def _familia(desc: str) -> str:
    toks = [t for t in normalizar(desc).split() if t not in PARADAS]
    return toks[0] if toks else ""


def _familia_legivel(desc: str) -> str:
    """Primeira palavra significativa, com acentos, como aparece no arquivo."""
    for palavra in re.findall(r"[\wÀ-ÿ]+", desc):
        if normalizar(palavra) not in PARADAS:
            return palavra.capitalize()
    return desc


def detectar(ctx) -> list[Oportunidade]:
    grupos: dict[tuple[str, str], list] = {}
    for lin in ctx.itens:
        if lin.protegida or lin.orcado <= 0 or not lin.fornecedor:
            continue
        if normalizar(lin.fornecedor) in GENERICOS:
            continue
        grupos.setdefault((lin.categoria, _familia(lin.descricao)), []).append(lin)
    ops = []
    for (cid, fam), lst in grupos.items():
        forn = {}
        for x in lst:
            forn[x.fornecedor] = forn.get(x.fornecedor, 0.0) + x.orcado
        if len(forn) < 3:
            continue
        soma = sum(forn.values())
        if soma < ctx.premissas["peso_minimo_categoria"] * ctx.total:
            continue
        maior = max(forn.items(), key=lambda kv: kv[1])
        nome_cat = ctx.taxonomia.nome(cid)
        legivel = _familia_legivel(lst[0].descricao)
        rotulo = nome_cat if normalizar(legivel) in normalizar(nome_cat) else f"{nome_cat} ({legivel.lower()})"
        ops.append(Oportunidade(
            detector=ID, titulo=f"Consolidação de fornecedores — {rotulo}",
            racional=(f"{len(forn)} fornecedores dividem {brl(soma)} em gastos do mesmo tipo. O maior "
                      f"({maior[0]}) concentra só {pct(maior[1] / soma)}. Volume fragmentado reduz o poder de "
                      "negociação e multiplica custos de gestão de contratos."),
            acao=("Agrupar o escopo em um ou dois contratos (acordo-quadro) com concorrência entre os atuais "
                  "fornecedores; usar o volume total como alavanca de preço e SLA."),
            linhas=ctx.linhas_oportunidade(lst, (0.03, 0.06, 0.10)), categoria=cid,
            confianca="media", esforco="medio", horizonte="medio",
            evidencias=[f"{f}: {brl(v)}" for f, v in sorted(forn.items(), key=lambda kv: -kv[1])],
            indicador="Nº de fornecedores por família de gasto e preço médio pago",
        ))
    return ops
