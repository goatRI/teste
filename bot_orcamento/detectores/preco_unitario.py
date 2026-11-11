"""Dispersão de preço unitário: o mesmo item comprado a preços diferentes."""

from __future__ import annotations

from ..modelo import Oportunidade
from ..util import brl, normalizar, num, pct

ID = "dispersao_preco_unitario"
NOME = "Dispersão de preço unitário"
DESCRICAO = "Mesmo item (mesma unidade) com preços unitários diferentes: equalizar pelo menor preço negociado."
REQUER = ["preco_unitario"]

PARADAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "com", "lote", "complementar",
           "reposicao", "emergencial", "adicional", "extra"}


def _chave(lin) -> tuple[str, str]:
    toks = [t for t in normalizar(lin.descricao).split() if t not in PARADAS]
    return normalizar(lin.unidade or ""), " ".join(toks[:3])


def detectar(ctx) -> list[Oportunidade]:
    grupos: dict[tuple, list] = {}
    for lin in ctx.itens:
        if lin.quantidade and lin.preco_unitario and lin.quantidade > 0 and lin.preco_unitario > 0:
            grupos.setdefault(_chave(lin), []).append(lin)
    ops = []
    for (un, item), lst in grupos.items():
        if len(lst) < 2:
            continue
        pmin = min(x.preco_unitario for x in lst)
        pmax = max(x.preco_unitario for x in lst)
        if pmax / pmin - 1 < 0.05:
            continue
        qtd = sum(x.quantidade for x in lst)
        pmed = sum(x.quantidade * x.preco_unitario for x in lst) / qtd
        caros = [x for x in lst if x.preco_unitario > pmin]
        taxas, notas = {}, {}
        for x in caros:
            eco_a = x.quantidade * (x.preco_unitario - pmin)
            eco_b = x.quantidade * max(0.0, x.preco_unitario - pmed)
            if eco_b <= 0:
                eco_b = 0.5 * eco_a
            taxas[x.id] = (0.5 * eco_b / x.orcado, eco_b / x.orcado, eco_a / x.orcado)
            notas[x.id] = f"{brl(x.preco_unitario)}/{x.unidade or 'un'} vs. menor {brl(pmin)}"
        base = caros[0]
        ops.append(Oportunidade(
            detector=ID, titulo=f"Equalização de preço unitário — {base.descricao.split('—')[0].strip()}",
            racional=(f"O mesmo item aparece em {len(lst)} linhas com preço unitário de {brl(pmin)} a "
                      f"{brl(pmax)} por {un or 'unidade'} ({pct(pmax / pmin - 1, 1, True)}). "
                      f"Preço médio ponderado: {brl(pmed)} para {num(qtd)} {un or 'un'}."),
            acao=("Negociar a equalização do preço com o fornecedor mais caro ou concentrar o volume no "
                  "fornecedor de menor preço (acordo-quadro com volume anual)."),
            linhas=ctx.linhas_oportunidade(caros, taxas, notas), categoria=base.categoria,
            confianca="alta", esforco="baixo", horizonte="curto",
            evidencias=[f"Linha {x.linha_origem}: {x.rotulo} — {num(x.quantidade)} {x.unidade or ''} × "
                        f"{brl(x.preco_unitario)}{' · ' + x.fornecedor if x.fornecedor else ''}" for x in lst],
            indicador="Preço unitário pago × menor preço negociado",
        ))
    return ops
