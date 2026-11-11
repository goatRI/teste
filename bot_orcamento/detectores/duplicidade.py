"""Possíveis duplicidades: descrições equivalentes com o mesmo valor."""

from __future__ import annotations

from difflib import SequenceMatcher

from ..modelo import Oportunidade
from ..util import brl, normalizar

ID = "duplicidades"
NOME = "Possíveis duplicidades"
DESCRICAO = "Linhas com descrição equivalente e mesmo valor podem ser o mesmo gasto orçado duas vezes."
REQUER: list[str] = []

PARADAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "com", "por", "no", "na"}


def _chave(desc: str) -> str:
    toks = [t for t in normalizar(desc).split() if t not in PARADAS]
    return " ".join(sorted(toks))


def detectar(ctx) -> list[Oportunidade]:
    lim = ctx.premissas["similaridade_duplicidade"]
    itens = sorted((x for x in ctx.itens if x.orcado > 0), key=lambda x: x.orcado)
    chaves = {x.id: _chave(x.descricao) for x in itens}
    pares = []
    usados: set[int] = set()
    for i, a in enumerate(itens):
        for b in itens[i + 1:]:
            if b.orcado > a.orcado * 1.01:
                break
            if a.id in usados or b.id in usados:
                continue
            if a.centro_custo and b.centro_custo and a.centro_custo != b.centro_custo:
                continue
            if a.fornecedor and b.fornecedor and a.fornecedor != b.fornecedor:
                continue
            sim = SequenceMatcher(None, chaves[a.id], chaves[b.id]).ratio()
            if sim >= lim:
                pares.append((a, b, sim))
                usados.update({a.id, b.id})
    ops = []
    for a, b, sim in pares:
        prim, dup = sorted((a, b), key=lambda x: x.linha_origem)
        igual = abs(a.orcado - b.orcado) < 0.01
        ops.append(Oportunidade(
            detector=ID, titulo=f"Possível duplicidade: {dup.descricao}",
            racional=(f"As linhas {prim.linha_origem} ('{prim.descricao}') e {dup.linha_origem} "
                      f"('{dup.descricao}') têm descrição equivalente (similaridade {sim:.0%}) e "
                      f"{'o mesmo valor' if igual else 'valores praticamente iguais'} ({brl(dup.orcado)})."),
            acao=("Confirmar com o responsável se as duas linhas cobrem o mesmo gasto; se sim, excluir a "
                  "duplicada. Se forem gastos distintos, renomear para deixar a diferença explícita."),
            linhas=ctx.linhas_oportunidade([dup], (0.5, 1.0, 1.0)), categoria=dup.categoria,
            confianca="alta" if (sim >= 0.95 and igual) else "media", esforco="baixo", horizonte="curto",
            evidencias=[f"Linha {prim.linha_origem}: {prim.rotulo} — {brl(prim.orcado)}",
                        f"Linha {dup.linha_origem}: {dup.rotulo} — {brl(dup.orcado)}"],
            indicador="Linhas duplicadas eliminadas", permite_total=True,
        ))
    return ops
