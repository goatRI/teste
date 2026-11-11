"""Rubricas genéricas e contingência sem destinação definida."""

from __future__ import annotations

from ..modelo import Oportunidade
from ..util import brl, pct, plural

ID = "rubricas_genericas"
NOME = "Rubricas genéricas e contingência"
DESCRICAO = "\"Diversos\", \"outros\" e contingências sem regra: verba sem destinação que tende a ser gasta."
REQUER: list[str] = []


def detectar(ctx) -> list[Oportunidade]:
    lst = [x for x in ctx.itens if x.categoria == "contingencia" and x.orcado > 0]
    if not lst:
        return []
    soma = sum(x.orcado for x in lst)
    peso = soma / ctx.total if ctx.total else 0.0
    if peso < ctx.premissas["participacao_generica"]:
        return []
    cat = ctx.taxonomia.get("contingencia")
    return [Oportunidade(
        detector=ID, titulo="Rubricas genéricas e contingência sem destinação definida",
        racional=(f"{plural(len(lst), 'linha genérica soma', 'linhas genéricas somam')} {brl(soma)} ({pct(peso)} do orçamento) sem "
                  "destinação específica. Verba sem dono e sem regra de liberação costuma ser consumida "
                  "mesmo sem necessidade."),
        acao=("Exigir detalhamento de cada rubrica genérica; reclassificar o que for identificável; manter a "
              "contingência como percentual formal com regra de liberação pela diretoria."),
        linhas=ctx.linhas_oportunidade(lst, cat.faixa), categoria="contingencia",
        confianca="media", esforco="baixo", horizonte="curto",
        evidencias=[f"Linha {x.linha_origem}: {x.rotulo} — {brl(x.orcado)} ({pct(x.orcado / ctx.total)})"
                    for x in sorted(lst, key=lambda x: -x.orcado)],
        indicador=cat.indicador,
    )]
