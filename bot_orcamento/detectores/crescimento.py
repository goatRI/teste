"""Crescimento acima da inflação frente ao ano anterior; linhas novas sem histórico."""

from __future__ import annotations

from ..modelo import Alerta, Oportunidade
from ..util import brl, pct, plural

ID = "crescimento_acima_inflacao"
NOME = "Crescimento acima da inflação"
DESCRICAO = ("Linhas que crescem mais que a inflação + tolerância exigem justificativa; sem ela, "
             "voltam ao valor do ano anterior corrigido.")
REQUER = ["ano_anterior"]


def detectar(ctx) -> list[Oportunidade]:
    p = ctx.premissas
    ipca, tol = p["ipca"], p["tolerancia_crescimento_pp"]
    limite = ipca + tol
    sel, taxas, notas, evid = [], {}, {}, []
    novas = []
    for lin in ctx.itens:
        if lin.protegida or lin.orcado <= 0:
            continue
        if lin.ano_anterior is None or lin.ano_anterior <= 0:
            if lin.ano_anterior is None and ctx.estrutura.tem.get("ano_anterior"):
                novas.append(lin)
            continue
        g = lin.orcado / lin.ano_anterior - 1
        if g <= limite:
            continue
        eco_c = lin.orcado - lin.ano_anterior * (1 + limite)
        eco_b = lin.orcado - lin.ano_anterior * (1 + ipca)
        eco_a = lin.orcado - lin.ano_anterior
        if eco_c < 0.0005 * ctx.total and eco_b < 0.001 * ctx.total:
            continue
        sel.append(lin)
        taxas[lin.id] = (eco_c / lin.orcado, eco_b / lin.orcado, eco_a / lin.orcado)
        notas[lin.id] = f"{pct(g, 1, True)} sobre o ano anterior"
        evid.append(f"Linha {lin.linha_origem}: {lin.rotulo} — {brl(lin.ano_anterior)} → {brl(lin.orcado)} "
                    f"({pct(g, 1, True)})")
    if novas:
        soma = sum(x.orcado for x in novas)
        ctx.alertar(Alerta(
            titulo=f"{plural(len(novas), 'linha nova', 'linhas novas')} sem histórico no ano anterior",
            detalhe=(f"Somam {brl(soma)}. Sem base de comparação, exigem justificativa (business case) "
                     "antes da aprovação: " + "; ".join(x.rotulo for x in novas[:6])
                     + ("…" if len(novas) > 6 else "") + "."),
            severidade="media" if soma > 0.01 * ctx.total else "baixa", origem=ID,
            linhas=[x.id for x in novas], valor=soma))
    if not sel:
        return []
    sel_ord = sorted(sel, key=lambda x: -(x.orcado * taxas[x.id][1]))
    return [Oportunidade(
        detector=ID,
        titulo=f"Crescimento acima da inflação em {plural(len(sel), 'linha', 'linhas')}",
        racional=(f"Estas linhas crescem mais que a inflação de referência ({pct(ipca)}) somada à tolerância "
                  f"de {pct(tol, 0)}. Sem justificativa de volume ou escopo, o valor deve voltar ao ano "
                  "anterior corrigido pela inflação (cenário base) ou ser congelado (agressivo)."),
        acao=("Pedir a cada responsável a memória de cálculo do aumento (volume, preço, escopo novo); "
              "aprovar apenas o que tiver justificativa e devolver o restante ao patamar do ano anterior."),
        linhas=ctx.linhas_oportunidade(sel_ord, taxas, notas), categoria=None,
        confianca="media", esforco="baixo", horizonte="curto", evidencias=[evid[sel.index(x)] for x in sel_ord][:12],
        indicador="Crescimento nominal por linha × inflação",
    )]
