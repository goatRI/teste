"""Execução orçamentária: folga (subexecução) vira economia; estouro vira risco."""

from __future__ import annotations

from ..modelo import Alerta, Oportunidade
from ..util import MESES_NOME, brl, pct, plural

ID = "execucao_orcamentaria"
NOME = "Execução orçado × realizado"
DESCRICAO = ("Linhas executando abaixo do ritmo orçado liberam verba (folga); linhas acima do ritmo "
             "são riscos de estouro para o realinhamento.")
REQUER = ["realizado"]


def _ritmo(lin, meses_real: list[int]) -> tuple[float, float, float] | None:
    """(orçado no período comparável, realizado no período, orçado restante)."""
    if lin.realizado is None or lin.orcado <= 0:
        return None
    if lin.meses_realizado and lin.meses:
        ms = sorted(lin.meses_realizado)
        orc_p = sum(lin.meses.get(m, 0.0) for m in ms)
        real_p = sum(lin.meses_realizado.values())
        return orc_p, real_p, lin.orcado - orc_p
    if meses_real and lin.meses:  # realizado parcial sem detalhe por linha
        orc_p = sum(lin.meses.get(m, 0.0) for m in meses_real)
        return orc_p, lin.realizado, lin.orcado - orc_p
    return lin.orcado, lin.realizado, 0.0


def detectar(ctx) -> list[Oportunidade]:
    p = ctx.premissas
    margem = p["margem_realinhamento"]
    meses_real = ctx.leitura.meses_com_realizado
    periodo = ""
    if meses_real and len(meses_real) < 12:
        periodo = f" até {MESES_NOME[max(meses_real) - 1].lower()}"
    folgas, taxas, notas, evid = [], {}, {}, []
    for lin in ctx.itens:
        r = _ritmo(lin, meses_real)
        if not r:
            continue
        orc_p, real_p, restante = r
        if orc_p <= 0:
            continue
        exe = real_p / orc_p
        if exe < 1 - p["limiar_subexecucao"]:
            nao_gasto = orc_p - real_p
            eco_c = 0.5 * nao_gasto + 0.5 * restante * max(0.0, 1 - exe * (1 + 2 * margem))
            eco_b = nao_gasto + restante * max(0.0, 1 - exe * (1 + margem))
            eco_a = nao_gasto + restante * max(0.0, 1 - exe)
            if restante == 0:
                eco_c = 0.5 * max(0.0, orc_p - real_p * (1 + margem))
                eco_b = max(0.0, orc_p - real_p * (1 + margem))
                eco_a = max(0.0, orc_p - real_p)
            if eco_b <= 0:
                continue
            folgas.append(lin)
            taxas[lin.id] = (eco_c / lin.orcado, eco_b / lin.orcado, eco_a / lin.orcado)
            notas[lin.id] = f"executou {pct(exe)} do previsto{periodo}"
            evid.append(f"Linha {lin.linha_origem}: {lin.rotulo} — executou {pct(exe)} do orçado{periodo} "
                        f"({brl(real_p)} de {brl(orc_p)})")
        elif exe > 1 + p["limiar_estouro"]:
            projetado = real_p + restante * exe
            excesso = projetado - lin.orcado
            ctx.alertar(Alerta(
                titulo=f"Risco de estouro: {lin.rotulo}",
                detalhe=(f"Executou {pct(exe)} do orçado{periodo} ({brl(real_p)} de {brl(orc_p)}). "
                         f"No ritmo atual o ano fecha em {brl(projetado)}, {brl(excesso)} acima do orçado."),
                severidade="alta" if excesso > 0.002 * ctx.total else "media", origem=ID,
                linhas=[lin.id], valor=excesso))
    if not folgas:
        return []
    return [Oportunidade(
        detector=ID,
        titulo=f"Folga orçamentária: {plural(len(folgas), 'linha', 'linhas')} abaixo do ritmo orçado",
        racional=("Estas linhas estão gastando bem menos que o orçado no mesmo período. A verba não usada "
                  f"pode ser devolvida e o restante do ano realinhado ao ritmo real (+{pct(margem, 0)} de margem)."),
        acao=("Confirmar com cada gestor se o ritmo menor é estrutural (escopo cancelado, preço menor) ou "
              "apenas atraso; se estrutural, reduzir a verba e realocar para linhas em risco de estouro."),
        linhas=ctx.linhas_oportunidade(folgas, taxas, notas), categoria=None,
        confianca="alta", esforco="baixo", horizonte="curto", evidencias=evid[:12],
        indicador="Execução acumulada (%) por linha frente ao orçado do período",
    )]
