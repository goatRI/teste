"""Cenários de adaptação do orçamento.

Regra de combinação (a mesma usada pelo simulador do relatório, em JavaScript):
para cada linha, as reduções das oportunidades selecionadas se combinam como
``1 - Π(1 - r_i)`` — duas alavancas de 10% resultam em 19%, não 20% — limitadas ao
teto por linha (``teto_reducao_linha``), exceto quando uma oportunidade permite zerar a
linha (duplicidade).
"""

from __future__ import annotations

from types import ModuleType

from .modelo import Cenario, Linha, Oportunidade
from .util import pct, plural

PESO_CONF = {"alta": 1.0, "media": 0.8, "baixa": 0.6}
PESO_ESF = {"baixo": 1.0, "medio": 1.3, "alto": 1.7}


def aplicar(itens: list[Linha], oportunidades: list[Oportunidade], selecao: dict[str, str],
            teto: float) -> dict[int, float]:
    fator = {x.id: 1.0 for x in itens}
    total_ok = {x.id: False for x in itens}
    for op in oportunidades:
        nivel = selecao.get(op.id)
        if not nivel:
            continue
        for lo in op.linhas:
            if lo.linha_id not in fator:
                continue
            fator[lo.linha_id] *= (1.0 - lo.taxas.get(nivel, 0.0))
            if op.permite_total:
                total_ok[lo.linha_id] = True
    valores = {}
    for x in itens:
        red = 1.0 - fator[x.id]
        red = min(red, 1.0 if total_ok[x.id] else teto)
        valores[x.id] = round(x.orcado * (1.0 - red), 2) if x.orcado > 0 else x.orcado
    return valores


def _cenario(cid, nome, desc, itens, ops, selecao, teto, **kw) -> Cenario:
    valores = aplicar(itens, ops, selecao, teto)
    tot_o = round(sum(x.orcado for x in itens), 2)
    tot_a = round(sum(valores.values()), 2)
    return Cenario(cid, nome, desc, selecao, valores, tot_o, tot_a, **kw)


def eh_discricionaria(op: Oportunidade, taxonomia) -> bool:
    if op.detector in ("rubricas_genericas", "estimativas_sem_base"):
        return True
    return bool(op.categoria) and taxonomia.get(op.categoria).discricionaria


def construir_cenarios(itens: list[Linha], ops: list[Oportunidade], premissas: dict, taxonomia,
                       tem_realizado: bool = False, meses_real: list[int] | None = None,
                       extras: list[ModuleType] | None = None) -> list[Cenario]:
    teto = premissas["teto_reducao_linha"]
    meta = premissas["meta_reducao"]
    total = sum(x.orcado for x in itens)
    cen: list[Cenario] = []

    sel = {o.id: "conservador" for o in ops if o.confianca in ("alta", "media")}
    cen.append(_cenario("conservador", "Conservador",
                        "Só oportunidades de confiança alta/média, no limite inferior das faixas.",
                        itens, ops, sel, teto))
    cen.append(_cenario("base", "Base (recomendado)",
                        "Todas as oportunidades no valor central das faixas — plano de trabalho sugerido.",
                        itens, ops, {o.id: "base" for o in ops}, teto, recomendado=True))
    cen.append(_cenario("agressivo", "Agressivo",
                        "Todas as oportunidades no limite superior das faixas — exige patrocínio forte.",
                        itens, ops, {o.id: "agressivo" for o in ops}, teto))
    qw = {o.id: "base" for o in ops if o.esforco == "baixo" and o.horizonte == "curto"}
    cen.append(_cenario("quick_wins", "Ganhos rápidos (0–3 meses)",
                        "Apenas ações de baixo esforço e prazo curto, no valor central.",
                        itens, ops, qw, teto))
    bz = {}
    for o in ops:
        if eh_discricionaria(o, taxonomia):
            bz[o.id] = "agressivo"
        elif o.confianca in ("alta", "media"):
            bz[o.id] = "conservador"
    cen.append(_cenario("base_zero", "Base zero nos discricionários",
                        "Despesas discricionárias (viagens, eventos, consultorias, genéricas) no limite superior; "
                        "demais no conservador.", itens, ops, bz, teto))

    # meta: menor conjunto de ações (por prioridade) que atinge a meta
    alvo = meta * total
    ordem = sorted(ops, key=lambda o: -o.prioridade)
    sel_m: dict[str, str] = {}
    atingida = False
    for nivel in ("base", "agressivo"):
        for o in ordem:
            if total - sum(aplicar(itens, ops, sel_m, teto).values()) >= alvo:
                atingida = True
                break
            sel_m[o.id] = nivel
        if atingida:
            break
    if not atingida:
        atingida = total - sum(aplicar(itens, ops, sel_m, teto).values()) >= alvo
    c_meta = _cenario("meta", f"Meta de {pct(meta, 0)}",
                      f"Menor conjunto de ações, em ordem de prioridade, para reduzir {pct(meta, 0)} do total.",
                      itens, ops, sel_m, teto, meta_atingida=atingida)
    if not atingida:
        c_meta.nota = (f"Mesmo com todas as oportunidades no limite superior a meta de {pct(meta, 0)} não é "
                       "atingida: será preciso rever escopo/volume, não só preço.")
    else:
        c_meta.nota = f"{plural(len(sel_m), 'oportunidade necessária', 'oportunidades necessárias')} para atingir a meta."
    cen.append(c_meta)

    # corte linear (comparativo)
    valores = {x.id: (round(x.orcado * (1 - meta), 2) if (x.orcado > 0 and not x.protegida) else x.orcado)
               for x in itens}
    cl = Cenario("linear", f"Corte linear de {pct(meta, 0)} (comparativo)",
                 f"Mesmo percentual em todas as linhas não protegidas. Só para comparação: corta igual linhas "
                 "eficientes e ineficientes.", {}, valores, round(total, 2), round(sum(valores.values()), 2))
    cl.nota = ("Não recomendado como estratégia única: penaliza linhas já eficientes, preserva as folgas "
               "maiores e costuma ser revertido ao longo do ano.")
    cen.append(cl)

    if tem_realizado:
        margem = premissas["margem_realinhamento"]
        valores = {}
        for x in itens:
            v = x.orcado
            if x.realizado is not None and x.orcado > 0:
                if x.meses_realizado and x.meses:
                    orc_p = sum(x.meses.get(m, 0.0) for m in x.meses_realizado)
                    real_p = sum(x.meses_realizado.values())
                elif meses_real and x.meses:
                    orc_p = sum(x.meses.get(m, 0.0) for m in meses_real)
                    real_p = x.realizado
                else:
                    orc_p, real_p = x.orcado, x.realizado
                if orc_p > 0:
                    exe = real_p / orc_p
                    proj = real_p + (x.orcado - orc_p) * exe
                    if exe < 1 - premissas["limiar_subexecucao"]:
                        v = min(x.orcado, proj * (1 + margem))
                    elif exe > 1 + premissas["limiar_estouro"]:
                        v = proj
            valores[x.id] = round(v, 2)
        cr = Cenario("realinhamento", "Realinhamento ao realizado",
                     "Linhas com folga voltam ao ritmo real (+margem) e linhas em estouro recebem o valor projetado.",
                     {}, valores, round(total, 2), round(sum(valores.values()), 2))
        cr.nota = "Mostra o orçamento 'honesto' pelo ritmo atual: libera folgas e cobre os estouros previstos."
        cen.append(cr)

    for mod in extras or []:
        sel_x = {}
        for o in ops:
            try:
                n = mod.selecionar(o)
            except Exception:
                n = None
            if n in ("conservador", "base", "agressivo"):
                sel_x[o.id] = n
        cen.append(_cenario(f"skill_{mod.ID}", mod.NOME, getattr(mod, "DESCRICAO", "Cenário de skill."),
                            itens, ops, sel_x, teto))
    return cen
