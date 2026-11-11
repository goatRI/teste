"""Horas extras acima do patamar saudável sobre a folha de salários."""

from __future__ import annotations

from ..modelo import Oportunidade
from ..taxonomia import contem_termo
from ..util import brl, normalizar, pct, plural

ID = "horas_extras"
NOME = "Horas extras sobre a folha"
DESCRICAO = "Compara horas extras com a folha de salários; acima do teto vira oportunidade de escala/controle."
REQUER: list[str] = []

TERMOS_FOLHA = ["salari*", "ordenado*", "folha*", "remunerac*"]


def detectar(ctx) -> list[Oportunidade]:
    he = [x for x in ctx.itens if x.categoria == "horas_extras" and x.orcado > 0]
    if not he:
        return []
    folha = [x for x in ctx.itens if x.categoria == "pessoal"
             and contem_termo(normalizar(x.descricao), TERMOS_FOLHA)]
    base_txt = "salários"
    if not folha:
        folha = [x for x in ctx.itens if x.categoria == "pessoal"]
        base_txt = "custo de pessoal"
    soma_folha = sum(x.orcado for x in folha)
    soma_he = sum(x.orcado for x in he)
    if soma_folha <= 0:
        return []
    razao = soma_he / soma_folha
    limite = ctx.premissas["limite_horas_extras"]
    if razao <= limite:
        return []
    exc_base = soma_he - limite * soma_folha
    exc_agr = soma_he - min(limite, 0.03) * soma_folha
    taxas = (0.5 * exc_base / soma_he, exc_base / soma_he, exc_agr / soma_he)
    return [Oportunidade(
        detector=ID,
        titulo="Horas extras acima do patamar saudável",
        racional=(f"Horas extras somam {brl(soma_he)}, {pct(razao)} dos {base_txt} ({brl(soma_folha)}). "
                  f"O teto adotado é {pct(limite, 0)}: o excesso é de {brl(exc_base)}. "
                  "HE recorrente em patamar alto costuma indicar dimensionamento de turno inadequado."),
        acao=("Revisar escalas e dimensionamento de equipes; exigir aprovação prévia para HE; "
              "implantar banco de horas; acompanhar HE por centro de custo semanalmente."),
        linhas=ctx.linhas_oportunidade(he, taxas), categoria="horas_extras",
        confianca="alta", esforco="medio", horizonte="curto",
        evidencias=[f"Linha {x.linha_origem}: {x.rotulo} — {brl(x.orcado)}" for x in he]
        + [f"Base de comparação: {plural(len(folha), 'linha', 'linhas')} de {base_txt}"],
        indicador=f"% de horas extras sobre {base_txt} (meta ≤ {pct(limite, 0)})",
    )]
