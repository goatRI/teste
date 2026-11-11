"""Picos mensais atípicos e concentração de gasto em dezembro (fim de exercício)."""

from __future__ import annotations

import statistics

from ..modelo import Oportunidade
from ..taxonomia import TERMOS_SAZONAIS, contem_termo
from ..util import MESES_NOME, brl, normalizar, plural

ID = "picos_mensais"
NOME = "Picos mensais e gasto de fim de ano"
DESCRICAO = ("Meses muito acima do padrão da própria linha e dezembro inflado (\"gastar para não perder\") "
             "sem sazonalidade conhecida.")
REQUER = ["meses"]


def detectar(ctx) -> list[Oportunidade]:
    p = ctx.premissas
    dez_l, dez_t, dez_n, dez_e = [], {}, {}, []
    pico_l, pico_t, pico_n, pico_e = [], {}, {}, []
    for lin in ctx.itens:
        if lin.protegida or lin.orcado <= 0 or len(lin.meses) < 6:
            continue
        if contem_termo(normalizar(lin.descricao), TERMOS_SAZONAIS):
            continue
        vals = lin.meses
        if 12 in vals and len(vals) >= 12:
            outros = [v for k, v in vals.items() if k != 12]
            media = sum(outros) / len(outros)
            if media > 0 and vals[12] > p["fator_dezembro"] * media:
                exc = vals[12] - media
                if exc >= 0.0002 * ctx.total:
                    dez_l.append(lin)
                    dez_t[lin.id] = (0.25 * exc / lin.orcado, 0.5 * exc / lin.orcado, exc / lin.orcado)
                    dez_n[lin.id] = f"dezembro {vals[12] / media:.1f}× a média"
                    dez_e.append(f"Linha {lin.linha_origem}: {lin.rotulo} — dezembro {brl(vals[12])} vs. média "
                                 f"{brl(media)} nos demais meses")
                    continue
        positivos = [v for v in vals.values() if v > 0]
        if len(positivos) < 6:
            continue
        for mes, v in sorted(vals.items(), key=lambda kv: -kv[1])[:1]:
            outros = [x for k, x in vals.items() if k != mes]
            med = statistics.median(outros)
            dp = statistics.pstdev(outros)
            media = sum(outros) / len(outros)
            if med > 0 and v > media + p["sigma_pico"] * dp and v > 1.5 * med:
                exc = v - med
                if exc < 0.0002 * ctx.total:
                    continue
                pico_l.append(lin)
                pico_t[lin.id] = (0.25 * exc / lin.orcado, 0.5 * exc / lin.orcado, exc / lin.orcado)
                pico_n[lin.id] = f"{MESES_NOME[mes - 1].lower()} {v / med:.1f}× a mediana"
                pico_e.append(f"Linha {lin.linha_origem}: {lin.rotulo} — {MESES_NOME[mes - 1].lower()} "
                              f"{brl(v)} vs. mediana {brl(med)}")
    ops = []
    if dez_l:
        ops.append(Oportunidade(
            detector=ID, titulo=f"Gasto concentrado em dezembro em {plural(len(dez_l), 'linha', 'linhas')}",
            racional=("Dezembro muito acima da média dos outros meses, sem sazonalidade conhecida, é o padrão "
                      "clássico de \"gastar para não perder verba\" no fim do exercício."),
            acao=("Exigir pedido e justificativa para gastos de dezembro acima da média; bloquear antecipação "
                  "de compras do ano seguinte; distribuir a verba pelo ano ou reduzi-la ao patamar médio."),
            linhas=ctx.linhas_oportunidade(dez_l, dez_t, dez_n), confianca="media", esforco="baixo",
            horizonte="curto", evidencias=dez_e[:12], indicador="Participação de dezembro no gasto anual",
        ))
    if pico_l:
        ops.append(Oportunidade(
            detector=ID, titulo=f"Picos mensais atípicos em {plural(len(pico_l), 'linha', 'linhas')}",
            racional=("Um mês muito acima do padrão da própria linha costuma esconder compra antecipada, "
                      "evento pontual superestimado ou erro de digitação."),
            acao=("Validar a causa de cada pico (parada programada? contrato anual?). Se não houver causa "
                  "documentada, trazer o mês para o patamar da mediana."),
            linhas=ctx.linhas_oportunidade(pico_l, pico_t, pico_n), confianca="media", esforco="baixo",
            horizonte="curto", evidencias=pico_e[:12], indicador="Desvio do mês frente à mediana da linha",
        ))
    return ops
