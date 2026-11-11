"""Alavancas por categoria: aplica a faixa de referência de cada categoria de custo."""

from __future__ import annotations

from ..modelo import Oportunidade
from ..util import brl, pct, plural

ID = "alavancas_categoria"
NOME = "Alavancas por categoria de custo"
DESCRICAO = ("Para cada categoria relevante, aplica a faixa de redução de referência e as ações típicas "
             "(renegociação, eficiência, política de consumo).")
REQUER: list[str] = []

# categorias tratadas por detectores específicos (evita dupla contagem)
TRATADAS_EM_OUTRO = {"contingencia", "horas_extras", "nao_classificado"}


def detectar(ctx) -> list[Oportunidade]:
    ops = []
    total = ctx.total or 1.0
    for cid, linhas in ctx.por_categoria().items():
        if cid in TRATADAS_EM_OUTRO:
            continue
        cat = ctx.taxonomia.get(cid)
        if cat.protegida or cat.faixa[1] <= 0:
            continue
        soma = sum(x.orcado for x in linhas if x.orcado > 0)
        if soma < ctx.premissas["peso_minimo_categoria"] * total:
            continue
        # linha que já executa acima do orçado não recebe corte de verba (vira risco, não economia)
        estouro = [x for x in linhas if x.orcado > 0 and ctx.em_estouro(x)]
        positivas = [x for x in linhas if x.orcado > 0 and x not in estouro]
        if not positivas or sum(x.orcado for x in positivas) < ctx.premissas["peso_minimo_categoria"] * total:
            continue
        fornecedores = {x.fornecedor for x in positivas if x.fornecedor}
        topo = sorted(positivas, key=lambda x: -x.orcado)[:5]
        c, b, a = cat.faixa
        racional = (f"{cat.nome} soma {brl(soma)} ({pct(soma / total)} do orçamento) em "
                    f"{plural(len(positivas), 'linha', 'linhas')}"
                    f"{' e ' + plural(len(fornecedores), 'fornecedor', 'fornecedores') if fornecedores else ''}. "
                    f"Faixa de referência de redução para esta categoria: {pct(c, 0)} a {pct(a, 0)} "
                    f"(base {pct(b, 0)})."
                    + (f" {plural(len(estouro), 'linha em risco de estouro ficou fora', 'linhas em risco de estouro ficaram fora')}"
                       " do corte (ver Riscos)." if estouro else ""))
        ops.append(Oportunidade(
            detector=ID, titulo=cat.alavanca, racional=racional,
            acao="; ".join(cat.acoes) + ".",
            linhas=ctx.linhas_oportunidade(positivas, cat.faixa), categoria=cid,
            confianca=cat.confianca, esforco=cat.esforco, horizonte=cat.horizonte,
            evidencias=[f"Linha {x.linha_origem}: {x.rotulo} — {brl(x.orcado)}" for x in topo],
            indicador=cat.indicador,
        ))
    return ops
