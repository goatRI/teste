"""Monta o HTML do relatório a partir da ``Analise``.

Todo número que importa sai marcado como
``<span data-check="chave" data-valor="123.45" data-fmt="brl">R$ 123,45</span>`` para que o
revisor (``revisor.py``) leia o HTML final e confira cada valor contra os dados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from ..analise import Analise
from ..config import DESCRICAO_PREMISSAS, MONETARIOS, PERCENTUAIS
from ..leitura import ROTULO_CAMPO, _col_letra
from ..modelo import NIVEIS, Verificacao
from ..util import MESES_NOME, brl, brl_curto, data_br, num, pct, plural
from . import graficos

PASTA_TEMPLATES = Path(__file__).parent / "templates"
NOME_NIVEL = {"conservador": "Conservador", "base": "Base", "agressivo": "Agressivo"}
NOME_HORIZONTE = {"curto": "0–3 meses", "medio": "3–6 meses", "longo": "6–12 meses"}
NOME_ESFORCO = {"baixo": "Baixo", "medio": "Médio", "alto": "Alto"}
NOME_CONF = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
NOME_SEV = {"alta": "alta", "media": "média", "baixa": "baixa", "info": "info"}
CENARIOS_TABELA = ["conservador", "base", "agressivo", "meta"]


def fmt_valor(v: float | None, fmt: str) -> str:
    if fmt == "brl":
        return brl(v)
    if fmt == "brl_curto":
        return brl_curto(v)
    if fmt == "pct":
        return pct(v)
    if fmt == "int":
        return num(v, 0)
    return str(v)


def marcado(chave: str, valor: float | None, fmt: str = "brl", classe: str = "") -> Markup:
    if valor is None:
        return Markup('<span class="num">—</span>')
    casas = 6 if fmt == "pct" else 2
    return Markup(
        f'<span class="num {escape(classe)}" data-check="{escape(chave)}" data-valor="{valor:.{casas}f}" '
        f'data-fmt="{fmt}">{escape(fmt_valor(valor, fmt))}</span>'
    )


def status_geral(verificacoes: list[Verificacao] | None) -> dict:
    if verificacoes is None:
        return {"id": "pendente", "rotulo": "Em revisão", "curto": "Em revisão", "classe": "b-none", "falhas": 0,
                "alertas": 0, "ok": 0}
    falhas = sum(1 for v in verificacoes if v.status == "falha")
    alertas = sum(1 for v in verificacoes if v.status == "alerta")
    ok = sum(1 for v in verificacoes if v.status == "ok")
    if falhas:
        return {"id": "reprovado", "rotulo": f"Reprovado na revisão ({falhas} falha(s))", "curto": "Reprovado",
                "classe": "b-bad",
                "falhas": falhas, "alertas": alertas, "ok": ok}
    if alertas:
        return {"id": "ressalvas", "rotulo": f"Aprovado com ressalvas ({alertas} alerta(s))", "curto": "Com ressalvas",
                "classe": "b-wait",
                "falhas": 0, "alertas": alertas, "ok": ok}
    return {"id": "aprovado", "rotulo": "Aprovado na revisão automática", "curto": "Aprovado", "classe": "b-ok",
            "falhas": 0, "alertas": 0, "ok": ok}


def _md_para_html(md: str) -> Markup:
    """Markdown mínimo e seguro para o parecer (parágrafos, listas, negrito, títulos ###)."""
    import re

    out, lista = [], False
    for bruto in md.strip().splitlines():
        ln = str(escape(bruto.strip()))
        ln = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", ln)
        if ln.startswith(("- ", "* ")):
            if not lista:
                out.append("<ul>")
                lista = True
            out.append(f"<li>{ln[2:]}</li>")
            continue
        if lista:
            out.append("</ul>")
            lista = False
        if not ln:
            continue
        if ln.startswith("#"):
            out.append(f"<h4>{ln.lstrip('#').strip()}</h4>")
        else:
            out.append(f"<p>{ln}</p>")
    if lista:
        out.append("</ul>")
    return Markup("".join(out))


def dados_embutidos(a: Analise, revisao: dict | None, verificacoes: list[Verificacao] | None) -> dict:
    itens = a.estrutura.itens
    return {
        "meta": a.meta,
        "totais": {"orcado": round(a.total, 2), "declarado": a.estrutura.total_declarado,
                   "n_itens": len(itens), "n_agregadoras": len(a.estrutura.agregadoras)},
        "premissas": {"teto_reducao_linha": a.premissas["teto_reducao_linha"],
                      "meta_reducao": a.premissas["meta_reducao"]},
        "categorias": {c["id"]: c["nome"] for c in a.por_categoria},
        "linhas": [{"id": x.id, "lo": x.linha_origem, "cod": x.codigo, "desc": x.descricao, "cat": x.categoria,
                    "cc": x.centro_custo, "orc": x.orcado, "prot": x.protegida} for x in itens],
        "oportunidades": [{
            "id": o.id, "titulo": o.titulo, "cat": o.categoria, "det": o.detector, "conf": o.confianca,
            "esf": o.esforco, "hor": o.horizonte, "pt": o.permite_total,
            "eco": {n: round(o.economia(n), 2) for n in NIVEIS},
            "l": [[lo.linha_id, lo.taxas["conservador"], lo.taxas["base"], lo.taxas["agressivo"]]
                  for lo in o.linhas],
        } for o in a.oportunidades],
        "cenarios": [{
            "id": c.id, "nome": c.nome, "total_original": c.total_original, "total_adaptado": c.total_adaptado,
            "economia": round(c.economia, 2), "pct": round(c.economia_pct, 6), "selecao": c.selecao,
            "por_oportunidade": bool(c.selecao) or c.id in ("conservador", "base", "agressivo", "quick_wins",
                                                             "base_zero", "meta"),
            "v": {str(x.id): c.valores[x.id] for x in itens if abs(c.valores.get(x.id, x.orcado) - x.orcado) > 0.004},
        } for c in a.cenarios],
        "revisao": {"rev": revisao.get("rev") if revisao else None,
                    "status": status_geral(verificacoes)["id"],
                    "verificacoes": [v.__dict__ for v in (verificacoes or [])]},
    }


def contexto(a: Analise, revisao: dict, historico: list[dict], verificacoes: list[Verificacao] | None,
             parecer: dict | None = None) -> dict[str, Any]:
    estr = a.estrutura
    cen = {c.id: c for c in a.cenarios}
    cat_nome = {c["id"]: c["nome"] for c in a.por_categoria}
    itens_por_id = {x.id: x for x in estr.itens}

    # mapeamento de colunas
    mapa = []
    for c in a.leitura.mapeamento.colunas:
        if not c.rotulo.startswith("(coluna") or c.campo:
            mapa.append({"letra": _col_letra(c.indice), "rotulo": c.rotulo,
                         "campo": ROTULO_CAMPO.get(c.campo or "", "— não usada") if c.campo else "— não usada",
                         "usada": bool(c.campo) and c.campo not in ("ignorar",),
                         "exemplo": c.exemplo, "motivo": c.motivo})
    # oportunidades com detalhes por linha
    ops = []
    for o in a.oportunidades:
        det = []
        for lo in sorted(o.linhas, key=lambda lo: -lo.economia("base")):
            x = itens_por_id.get(lo.linha_id)
            if x is None:
                continue
            det.append({"linha": x, "base": lo.base, "taxa": lo.taxas["base"], "eco": lo.economia("base"),
                        "nota": lo.nota})
        ops.append({"o": o, "eco": {n: o.economia(n) for n in NIVEIS}, "det": det,
                    "cat_nome": cat_nome.get(o.categoria or "", a.taxonomia.nome(o.categoria) if o.categoria else "Várias")})
    plano = {h: [d for d in ops if d["o"].horizonte == h] for h in ("curto", "medio", "longo")}

    # tabela de linhas com cenários
    linhas_tab = []
    for x in estr.itens:
        linhas_tab.append({"x": x, "cat": cat_nome.get(x.categoria, x.categoria),
                           "v": {cid: cen[cid].valores.get(x.id, x.orcado) for cid in CENARIOS_TABELA if cid in cen}})
    top_linhas = sorted(estr.itens, key=lambda x: -x.orcado)[:15]

    premissas_tab = []
    for k, desc in DESCRICAO_PREMISSAS.items():
        v = a.premissas.get(k)
        if k in PERCENTUAIS:
            txt = pct(v, 2 if abs(v) < 0.01 else 1) if k != "similaridade_duplicidade" else f"{v:.0%}"
        elif k in MONETARIOS:
            txt = brl(v, 0)
        else:
            txt = num(v, 1)
        premissas_tab.append({"chave": k, "descricao": desc, "valor": txt})
    presentes = {c["id"] for c in a.por_categoria}
    faixas = []
    for c in a.taxonomia.categorias:
        if c.id in presentes:
            faixas.append({"c": c, "orcado": next(d["orcado"] for d in a.por_categoria if d["id"] == c.id)})
    faixas.sort(key=lambda d: -d["orcado"])

    meses_real = a.leitura.meses_com_realizado
    graf_mensal = graficos.colunas_mensais(estr.meses, estr.meses_realizado or None) if estr.meses else ""
    graf_pareto = graficos.curva_pareto(a.pareto.get("pontos", []), a.pareto.get("n80", 0), a.pareto.get("n", 0))
    max_cat = max((d["orcado"] for d in a.por_categoria), default=1.0) or 1.0
    max_eco_cen = max((c.economia for c in a.cenarios), default=1.0) or 1.0

    st = status_geral(verificacoes)
    dados = dados_embutidos(a, revisao, verificacoes)
    dados_json = json.dumps(dados, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
    return {
        "a": a, "estr": estr, "meta": a.meta, "cen": cen, "cenarios": a.cenarios, "ops": ops, "plano": plano,
        "mapa": mapa, "linhas_tab": linhas_tab, "top_linhas": top_linhas, "cat_nome": cat_nome,
        "premissas_tab": premissas_tab, "faixas": faixas, "graf_mensal": Markup(graf_mensal),
        "graf_pareto": Markup(graf_pareto), "max_cat": max_cat, "max_eco_cen": max_eco_cen,
        "revisao": revisao, "historico": historico, "verificacoes": verificacoes, "status": st,
        "dados_json": Markup(dados_json), "NIVEIS": NIVEIS, "NOME_NIVEL": NOME_NIVEL,
        "NOME_HORIZONTE": NOME_HORIZONTE, "NOME_ESFORCO": NOME_ESFORCO, "NOME_CONF": NOME_CONF, "NOME_SEV": NOME_SEV,
        "CENARIOS_TABELA": [c for c in CENARIOS_TABELA if c in cen], "MESES_NOME": MESES_NOME,
        "meses_real": meses_real, "parecer": parecer,
        "parecer_html": _md_para_html(parecer["texto"]) if parecer and parecer.get("texto") else None,
        "storage_key": f"bot_orcamento_{a.meta['slug']}_v1",
    }


def _ambiente() -> Environment:
    env = Environment(loader=FileSystemLoader(str(PASTA_TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(brl=brl, brl_curto=brl_curto, pct=pct, num=num, data_br=data_br)
    env.globals.update(v=marcado, pct=pct, brl=brl, brl_curto=brl_curto, num=num, plural=plural)
    return env


def renderizar(a: Analise, revisao: dict, historico: list[dict], verificacoes: list[Verificacao] | None,
               parecer: dict | None = None) -> str:
    env = _ambiente()
    tpl = env.get_template("relatorio.html.j2")
    return tpl.render(**contexto(a, revisao, historico, verificacoes, parecer))
