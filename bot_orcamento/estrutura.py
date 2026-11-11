"""Entendimento da estrutura: itens × subtotais, hierarquia, conciliação e qualidade dos dados.

Somar subtotais junto com itens é o erro mais comum em análise de orçamento — dobra o
valor. Aqui cada linha recebe ``tipo`` (item, subtotal, total) e um motivo legível.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .leitura import Leitura
from .modelo import Linha
from .taxonomia import Taxonomia
from .util import brl, normalizar, pct

_RX_TOTAL = re.compile(r"^(sub ?total|total|totais|soma|somatorio|resultado|tot)\b")


def _tol(v: float) -> float:
    return max(1.0, abs(v) * 0.001)


def _segmentos(cod: str | None) -> tuple[str, ...]:
    if not cod:
        return ()
    return tuple(p for p in re.split(r"[.\-/ ]+", cod.strip()) if p)


@dataclass
class Estrutura:
    itens: list[Linha]
    agregadoras: list[Linha]
    total_itens: float
    total_declarado: float | None
    linha_total_declarado: int | None
    conciliacao: dict
    grupos: list[dict]
    hierarquia: str
    qualidade: list[dict] = field(default_factory=list)
    subtotais_conferidos: list[dict] = field(default_factory=list)
    meses: dict[int, float] = field(default_factory=dict)
    meses_realizado: dict[int, float] = field(default_factory=dict)
    cobertura_classificacao: float = 0.0
    total_realizado: float | None = None
    total_ano_anterior: float | None = None
    total_projetado: float | None = None
    tem: dict[str, bool] = field(default_factory=dict)


def _marcar_por_palavra(linhas: list[Linha]) -> None:
    for lin in linhas:
        n = normalizar(lin.descricao)
        if _RX_TOTAL.match(n) or (not lin.codigo and n in ("total", "total geral", "geral")):
            lin.tipo = "total" if ("geral" in n or n == "total") else "subtotal"
            lin.motivo_tipo = "descrição indica total/subtotal"


def _marcar_por_codigo(linhas: list[Linha], qualidade: list[dict], conferidos: list[dict]) -> None:
    com_cod = [lin for lin in linhas if lin.codigo and lin.tipo == "item"]
    segs = {lin.id: _segmentos(lin.codigo) for lin in com_cod}
    por_seg = defaultdict(list)
    for lin in com_cod:
        por_seg[segs[lin.id]].append(lin)
    filhos: dict[int, list[Linha]] = defaultdict(list)
    for lin in com_cod:
        s = segs[lin.id]
        for k in range(len(s) - 1, 0, -1):
            pai = por_seg.get(s[:k])
            if pai:
                filhos[pai[0].id].append(lin)
                break
    for pid, fs in filhos.items():
        pai = next(x for x in com_cod if x.id == pid)
        pai.tipo = "subtotal"
        pai.motivo_tipo = f"código {pai.codigo} agrupa {len(fs)} conta(s)"
        soma = sum(f.orcado for f in fs)
        ok = abs(soma - pai.orcado) <= _tol(pai.orcado)
        conferidos.append({"linha_origem": pai.linha_origem, "rotulo": pai.rotulo, "declarado": pai.orcado,
                           "calculado": soma, "ok": ok})
        if not ok:
            qualidade.append({"tipo": "subtotal_divergente", "severidade": "alta", "linhas": [pai.linha_origem],
                              "mensagem": f"Conta agregadora '{pai.rotulo}' ({brl(pai.orcado)}) difere da soma "
                                          f"das contas filhas ({brl(soma)})."})
        for f in fs:
            if not f.grupo:
                f.grupo = pai.descricao


def _marcar_por_soma(leitura: Leitura, linhas: list[Linha], conferidos: list[dict]) -> None:
    """Linha em negrito (ou sem código entre itens com código) cujo valor = soma do bloco acima."""
    fronteiras = {c["linha_origem"] for c in leitura.cabecalhos_grupo} | set(leitura.linhas_vazias)
    ordenadas = sorted(linhas, key=lambda x: x.linha_origem)
    itens_tem_codigo = sum(1 for x in ordenadas if x.codigo) >= 0.6 * max(1, len(ordenadas))
    ultimo_valorado = max((x.linha_origem for x in ordenadas if x.orcado), default=-1)
    for i, lin in enumerate(ordenadas):
        candidata = lin.tipo != "item" or lin.negrito or (itens_tem_codigo and not lin.codigo) \
            or lin.linha_origem == ultimo_valorado
        if not candidata:
            continue
        # soma do bloco contíguo acima até a fronteira anterior
        bloco = 0.0
        n_bloco = 0
        for j in range(i - 1, -1, -1):
            ant = ordenadas[j]
            if ant.tipo != "item":
                break
            bloco += ant.orcado
            n_bloco += 1
            if ant.linha_origem in fronteiras or (ant.linha_origem - 1) in fronteiras:
                break
        anteriores_itens = sum(x.orcado for x in ordenadas[:i] if x.tipo == "item")
        anteriores_sub = sum(x.orcado for x in ordenadas[:i] if x.tipo == "subtotal")
        if n_bloco >= 2 and abs(bloco - lin.orcado) <= _tol(lin.orcado):
            if lin.tipo == "item":
                lin.tipo = "subtotal"
                lin.motivo_tipo = f"valor igual à soma das {n_bloco} linhas acima"
            conferidos.append({"linha_origem": lin.linha_origem, "rotulo": lin.rotulo, "declarado": lin.orcado,
                               "calculado": bloco, "ok": True})
        elif i > 1 and abs(anteriores_itens - lin.orcado) <= _tol(lin.orcado):
            lin.tipo = "total"
            lin.motivo_tipo = lin.motivo_tipo or "valor igual à soma de todos os itens acima"
        elif anteriores_sub and abs(anteriores_sub - lin.orcado) <= _tol(lin.orcado):
            lin.tipo = "total"
            lin.motivo_tipo = lin.motivo_tipo or "valor igual à soma dos subtotais acima"
        elif lin.tipo == "subtotal" and n_bloco >= 1:
            conferidos.append({"linha_origem": lin.linha_origem, "rotulo": lin.rotulo, "declarado": lin.orcado,
                               "calculado": bloco, "ok": False})


def analisar_estrutura(leitura: Leitura, taxonomia: Taxonomia) -> Estrutura:
    linhas = leitura.linhas
    qualidade: list[dict] = []
    conferidos: list[dict] = []
    _marcar_por_palavra(linhas)
    _marcar_por_codigo(linhas, qualidade, conferidos)
    _marcar_por_soma(leitura, linhas, conferidos)

    itens = [x for x in linhas if x.tipo == "item"]
    agreg = [x for x in linhas if x.tipo != "item"]
    total_itens = sum(x.orcado for x in itens)

    # dupla contagem não detectada: um item vale a soma dos demais
    if itens and not any(x.tipo == "total" for x in agreg):
        maior = max(itens, key=lambda x: x.orcado)
        resto = total_itens - maior.orcado
        if len(itens) > 3 and abs(resto - maior.orcado) <= _tol(maior.orcado):
            maior.tipo, maior.motivo_tipo = "total", "valor igual à soma de todas as demais linhas"
            itens.remove(maior)
            agreg.append(maior)
            total_itens = resto

    # total declarado: a linha "total" de maior valor
    totais = [x for x in agreg if x.tipo == "total"]
    total_decl = max(totais, key=lambda x: x.orcado) if totais else None
    if total_decl is not None:
        dif = total_itens - total_decl.orcado
        ok = abs(dif) <= _tol(total_decl.orcado)
        conc = {"status": "ok" if ok else "divergente", "diferenca": dif,
                "detalhe": ("Soma dos itens confere com o total declarado na linha "
                            f"{total_decl.linha_origem}." if ok else
                            f"Soma dos itens ({brl(total_itens)}) difere do total declarado "
                            f"({brl(total_decl.orcado)}) em {brl(dif)}.")}
        if not ok:
            qualidade.append({"tipo": "total_divergente", "severidade": "alta", "linhas": [total_decl.linha_origem],
                              "mensagem": conc["detalhe"] + " Verifique linhas fora do padrão ou subtotais."})
    else:
        conc = {"status": "sem_total", "diferenca": None,
                "detalhe": "O arquivo não traz linha de total geral; o total foi calculado pela soma dos itens."}

    # classificação
    for lin in itens:
        cid, conf, termo = taxonomia.classificar(lin.descricao, lin.categoria_origem, lin.grupo)
        cat = taxonomia.get(cid)
        lin.categoria, lin.categoria_conf, lin.categoria_termo = cid, conf, termo
        lin.comportamento = cat.comportamento
        lin.protegida = cat.protegida
        lin.discricionaria = cat.discricionaria
        if lin.natureza and normalizar(lin.natureza) == "capex" and cid != "capex":
            lin.categoria_conf = "media"
    nao_cls = [x for x in itens if x.categoria == "nao_classificado"]
    cobertura = 1 - (sum(x.orcado for x in nao_cls) / total_itens) if total_itens else 1.0
    if nao_cls:
        qualidade.append({"tipo": "nao_classificado", "severidade": "media" if cobertura < 0.95 else "baixa",
                          "linhas": [x.linha_origem for x in nao_cls][:30],
                          "mensagem": f"{len(nao_cls)} linha(s) sem categoria reconhecida "
                                      f"({pct(1 - cobertura)} do valor). Elas não recebem alavanca de categoria; "
                                      "use --ia, uma skill de taxonomia ou 'palavras_extras' nas premissas."})

    # qualidade dos dados
    zeradas = [x for x in itens if not x.orcado]
    if zeradas:
        qualidade.append({"tipo": "linhas_zeradas", "severidade": "baixa", "linhas": [x.linha_origem for x in zeradas][:30],
                          "mensagem": f"{len(zeradas)} linha(s) com orçado zero ou vazio."})
    negativas = [x for x in itens if x.orcado < 0]
    if negativas:
        qualidade.append({"tipo": "negativos", "severidade": "media", "linhas": [x.linha_origem for x in negativas],
                          "mensagem": f"{len(negativas)} linha(s) com valor negativo (estorno/crédito?) — "
                                      "conferir se não são recuperações que deveriam ficar fora do custo."})
    cods = Counter(x.codigo for x in itens if x.codigo)
    rep = [c for c, n in cods.items() if n > 1]
    if rep and not leitura.mapeamento.formato == "longo":
        qualidade.append({"tipo": "codigo_repetido", "severidade": "baixa",
                          "linhas": [x.linha_origem for x in itens if x.codigo in rep][:30],
                          "mensagem": f"{len(rep)} código(s) repetido(s) em mais de uma linha "
                                      f"(ex.: {', '.join(rep[:4])})."})
    m = leitura.mapeamento
    if m.meses and not m.orcado_calculado:
        incons = []
        for x in itens:
            if x.meses:
                s = sum(x.meses.values())
                if abs(s - x.orcado) > max(1.0, 0.005 * abs(x.orcado)):
                    incons.append(x)
        if incons:
            qualidade.append({"tipo": "meses_x_total", "severidade": "alta",
                              "linhas": [x.linha_origem for x in incons][:30],
                              "mensagem": f"{len(incons)} linha(s) em que a soma dos meses difere da coluna de total."})
    if leitura.mapeamento.realizado_calculado and leitura.meses_com_realizado and len(leitura.meses_com_realizado) < 12:
        meses_txt = f"{min(leitura.meses_com_realizado)}–{max(leitura.meses_com_realizado)}"
        qualidade.append({"tipo": "realizado_parcial", "severidade": "info", "linhas": [],
                          "mensagem": f"Realizado disponível apenas para os meses {meses_txt}: a execução é comparada "
                                      "com o orçado dos mesmos meses."})
    for c in conferidos:
        if not c["ok"] and not any(q["tipo"] == "subtotal_divergente" and c["linha_origem"] in q["linhas"] for q in qualidade):
            qualidade.append({"tipo": "subtotal_divergente", "severidade": "media", "linhas": [c["linha_origem"]],
                              "mensagem": f"Subtotal '{c['rotulo']}' ({brl(c['declarado'])}) não bate com a soma "
                                          f"do bloco ({brl(c['calculado'])})."})

    # grupos
    for x in itens:
        if not x.grupo and x.categoria_origem:
            x.grupo = x.categoria_origem
    acum: dict[str, dict] = {}
    for x in itens:
        g = x.grupo or "Sem grupo"
        d = acum.setdefault(g, {"nome": g, "n": 0, "total": 0.0, "primeira_linha": x.linha_origem})
        d["n"] += 1
        d["total"] += x.orcado
    grupos = sorted(acum.values(), key=lambda d: d["primeira_linha"])
    for d in grupos:
        d["pct"] = d["total"] / total_itens if total_itens else 0.0

    if any(x.motivo_tipo.startswith("código") for x in agreg):
        prof = max((len(_segmentos(x.codigo)) for x in linhas if x.codigo), default=0)
        hier = f"Plano de contas hierárquico pelo código ({prof} níveis)"
    elif leitura.cabecalhos_grupo and any(x.grupo for x in itens):
        hier = f"Grupos por linhas de título ({len([g for g in grupos if g['nome'] != 'Sem grupo'])} grupos)"
        if any(x.tipo == "subtotal" for x in agreg):
            hier += " com subtotais"
    elif any(x.categoria_origem for x in itens):
        hier = "Lista com coluna de categoria/grupo"
    else:
        hier = "Lista simples de contas"
    if leitura.mapeamento.formato == "longo":
        hier = "Lançamentos (formato longo) consolidados por conta"

    meses: dict[int, float] = defaultdict(float)
    meses_r: dict[int, float] = defaultdict(float)
    for x in itens:
        for k, v in x.meses.items():
            meses[k] += v
        for k, v in x.meses_realizado.items():
            meses_r[k] += v

    def soma_opc(attr: str) -> float | None:
        vals = [getattr(x, attr) for x in itens if getattr(x, attr) is not None]
        return sum(vals) if vals else None

    tem = {
        "realizado": any(x.realizado is not None for x in itens),
        "ano_anterior": any(x.ano_anterior is not None for x in itens),
        "meses": any(x.meses for x in itens),
        "meses_realizado": any(x.meses_realizado for x in itens),
        "fornecedor": any(x.fornecedor for x in itens),
        "centro_custo": any(x.centro_custo for x in itens),
        "preco_unitario": any(x.preco_unitario is not None and x.quantidade is not None for x in itens),
        "projetado": any(x.projetado is not None for x in itens),
    }
    return Estrutura(
        itens=itens, agregadoras=agreg, total_itens=total_itens,
        total_declarado=total_decl.orcado if total_decl else None,
        linha_total_declarado=total_decl.linha_origem if total_decl else None,
        conciliacao=conc, grupos=grupos, hierarquia=hier, qualidade=qualidade,
        subtotais_conferidos=conferidos, meses=dict(sorted(meses.items())),
        meses_realizado=dict(sorted(meses_r.items())), cobertura_classificacao=cobertura,
        total_realizado=soma_opc("realizado"), total_ano_anterior=soma_opc("ano_anterior"),
        total_projetado=soma_opc("projetado"), tem=tem,
    )
