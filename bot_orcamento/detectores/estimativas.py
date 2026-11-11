"""Estimativas sem memória de cálculo: valor redondo, sem quantidade × preço e rateio linear."""

from __future__ import annotations

from ..modelo import Oportunidade
from ..util import brl, plural

ID = "estimativas_sem_base"
NOME = "Estimativas sem memória de cálculo"
DESCRICAO = ("Valores redondos, sem quantidade × preço e divididos igualmente pelos 12 meses indicam "
             "estimativa \"de cima para baixo\" — candidatos a orçamento base zero.")
REQUER: list[str] = []


def _redondo(v: float, multiplo: float) -> bool:
    return v >= multiplo and abs(v / multiplo - round(v / multiplo)) < 1e-6


def _rateio_linear(meses: dict[int, float]) -> bool:
    vals = [v for v in meses.values()]
    if len(vals) < 12:
        return False
    return max(vals) - min(vals) <= max(1.0, 0.002 * max(vals))


def detectar(ctx) -> list[Oportunidade]:
    p = ctx.premissas
    sel, notas = [], {}
    for lin in ctx.itens:
        if lin.protegida or lin.categoria == "contingencia" or lin.orcado < p["estimativa_valor_minimo"]:
            continue
        if lin.quantidade and lin.preco_unitario:
            continue
        if not _redondo(lin.orcado, p["estimativa_multiplo"]):
            continue
        if lin.meses and not _rateio_linear(lin.meses):
            continue
        sel.append(lin)
        notas[lin.id] = "valor redondo" + (" com rateio linear" if lin.meses else "")
    if not sel:
        return []
    soma = sum(x.orcado for x in sel)
    return [Oportunidade(
        detector=ID, titulo=f"Estimativas sem memória de cálculo em {plural(len(sel), 'linha', 'linhas')}",
        racional=(f"{plural(len(sel), 'linha', 'linhas')} somando {brl(soma)} com valor redondo (múltiplo de "
                  f"{brl(p['estimativa_multiplo'], 0)}), sem quantidade × preço"
                  + (" e com o mesmo valor em todos os meses" if any(x.meses for x in sel) else "")
                  + ". É o padrão de verba estimada sem base, que tende a carregar folga."),
        acao=("Aplicar orçamento base zero nestas linhas: exigir memória de cálculo (quantidade, preço, "
              "contrato de referência) e aprovar apenas o valor justificado."),
        linhas=ctx.linhas_oportunidade(sel, (0.03, 0.07, 0.12), notas), confianca="baixa",
        esforco="baixo", horizonte="curto",
        evidencias=[f"Linha {x.linha_origem}: {x.rotulo} — {brl(x.orcado)} ({notas[x.id]})" for x in sel][:12],
        indicador="% do orçamento com memória de cálculo",
    )]
