"""Orquestra a análise completa: ler → entender → detectar → priorizar → cenários → resumo."""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import NOME_BOT, __version__
from .cenarios import PESO_CONF, PESO_ESF, construir_cenarios
from .config import carregar_premissas
from .detectores import Contexto, carregar_plugins, executar_detectores, pastas_padrao
from .estrutura import Estrutura, analisar_estrutura
from .leitura import Leitura, ler_orcamento
from .modelo import Alerta, Cenario, Oportunidade
from .taxonomia import Taxonomia
from .util import brl, brl_curto, pct, slug

ORDEM_SEVERIDADE = {"alta": 0, "media": 1, "baixa": 2, "info": 3}


@dataclass
class Analise:
    meta: dict
    leitura: Leitura
    estrutura: Estrutura
    premissas: dict
    taxonomia: Taxonomia
    oportunidades: list[Oportunidade]
    alertas: list[Alerta]
    cenarios: list[Cenario]
    detectores: list[dict]
    skills: list[dict]
    por_categoria: list[dict]
    pareto: dict
    mix: dict
    insights: list[str]
    resumo: str
    parecer: dict | None = None
    descartadas: list[dict] = field(default_factory=list)

    def cenario(self, cid: str) -> Cenario:
        return next(c for c in self.cenarios if c.id == cid)

    @property
    def total(self) -> float:
        return self.estrutura.total_itens


def _hash_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _titulo(leitura: Leitura, titulo: str | None) -> str:
    if titulo:
        return titulo
    t = leitura.titulo_detectado
    if t:
        return re.sub(r"\s+", " ", t).strip()
    return Path(leitura.arquivo).stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _por_categoria(estr: Estrutura, tax: Taxonomia, cenarios: list[Cenario]) -> list[dict]:
    out: dict[str, dict] = {}
    total = estr.total_itens or 1.0
    for x in estr.itens:
        cat = tax.get(x.categoria)
        d = out.setdefault(x.categoria, {
            "id": x.categoria, "nome": cat.nome, "n": 0, "orcado": 0.0, "ano_anterior": 0.0, "orcado_comp": 0.0,
            "tem_ant": False, "realizado": 0.0, "tem_real": False, "comportamento": cat.comportamento,
            "discricionaria": cat.discricionaria, "protegida": cat.protegida,
            "adaptado": {c.id: 0.0 for c in cenarios},
        })
        d["n"] += 1
        d["orcado"] += x.orcado
        if x.ano_anterior is not None:
            d["ano_anterior"] += x.ano_anterior
            d["orcado_comp"] += x.orcado  # só linhas com histórico: comparação like-for-like
            d["tem_ant"] = True
        if x.realizado is not None:
            d["realizado"] += x.realizado
            d["tem_real"] = True
        for c in cenarios:
            d["adaptado"][c.id] += c.valores.get(x.id, x.orcado)
    lst = sorted(out.values(), key=lambda d: -d["orcado"])
    for d in lst:
        d["pct"] = d["orcado"] / total
        d["economia"] = {k: d["orcado"] - v for k, v in d["adaptado"].items()}
        d["var_aa"] = (d["orcado_comp"] / d["ano_anterior"] - 1) if d["tem_ant"] and d["ano_anterior"] > 0 else None
        d["n_sem_hist"] = 0
    return lst


def _pareto(estr: Estrutura) -> dict:
    vals = sorted((x.orcado for x in estr.itens if x.orcado > 0), reverse=True)
    total = sum(vals)
    if not vals or total <= 0:
        return {"n": 0, "n80": 0, "pontos": []}
    acum, n80, pontos = 0.0, None, []
    for i, v in enumerate(vals, start=1):
        acum += v
        if n80 is None and acum >= 0.8 * total - 1e-6:
            n80 = i
        pontos.append((i / len(vals), acum / total))
    return {"n": len(vals), "n80": n80 or len(vals), "pct_linhas_80": (n80 or len(vals)) / len(vals),
            "pontos": pontos}


def _mix(estr: Estrutura) -> dict:
    total = estr.total_itens or 1.0
    m = {"fixo": 0.0, "variavel": 0.0, "semi": 0.0, "discricionario": 0.0, "protegido": 0.0}
    for x in estr.itens:
        m[x.comportamento] = m.get(x.comportamento, 0.0) + x.orcado
        if x.discricionaria:
            m["discricionario"] += x.orcado
        if x.protegida:
            m["protegido"] += x.orcado
    return {k: {"valor": v, "pct": v / total} for k, v in m.items()}


def _insights(a_estr: Estrutura, por_cat: list[dict], pareto: dict, mix: dict, premissas: dict,
              meses_real: list[int]) -> list[str]:
    ins = []
    if pareto.get("n"):
        ins.append(f"{pareto['n80']} de {pareto['n']} linhas ({pct(pareto['pct_linhas_80'])}) concentram 80% "
                   "do orçamento — é onde negociação e revisão de escopo rendem mais.")
    if len(por_cat) >= 3:
        top = por_cat[:3]
        ins.append(f"As três maiores categorias — {top[0]['nome']}, {top[1]['nome']} e {top[2]['nome']} — "
                   f"somam {pct(sum(d['pct'] for d in top))} do total.")
    ins.append(f"Perfil de custo: {pct(mix['fixo']['pct'])} fixo, {pct(mix['semi']['pct'])} semivariável e "
               f"{pct(mix['variavel']['pct'])} variável; {pct(mix['discricionario']['pct'])} é discricionário e "
               f"{pct(mix['protegido']['pct'])} está em categorias protegidas (sem corte automático).")
    comp = [x for x in a_estr.itens if x.ano_anterior and x.ano_anterior > 0]
    if comp:
        o = sum(x.orcado for x in comp)
        a = sum(x.ano_anterior for x in comp)
        g = o / a - 1
        ins.append(f"Nas {len(comp)} linhas com histórico, o orçamento cresce {pct(g, 1, True)} sobre o ano "
                   f"anterior ({brl_curto(a)} → {brl_curto(o)}), frente a uma inflação de referência de "
                   f"{pct(premissas['ipca'])}.")
    reais = [x for x in a_estr.itens if x.realizado is not None and x.orcado > 0]
    if reais:
        if meses_real and len(meses_real) < 12:
            orc_p = sum(sum(x.meses.get(m, 0.0) for m in meses_real) for x in reais)
        else:
            orc_p = sum(x.orcado for x in reais)
        real = sum(x.realizado for x in reais)
        if orc_p:
            periodo = f" nos meses {min(meses_real)}–{max(meses_real)}" if meses_real and len(meses_real) < 12 else ""
            ins.append(f"Execução de {pct(real / orc_p)} do orçado{periodo} ({brl_curto(real)} de {brl_curto(orc_p)}).")
    return ins


def analisar(caminho: str | Path, aba: str | None = None, mapa: dict[str, str] | None = None,
             premissas: dict | None = None, titulo: str | None = None,
             pastas_skills: list[str | Path] | None = None, ia: bool = False,
             data_base: str | None = None, log=print) -> Analise:
    caminho = str(caminho)
    premissas = premissas or carregar_premissas()
    plugins = carregar_plugins(pastas_padrao() if pastas_skills is None else pastas_skills)
    leitura = ler_orcamento(caminho, aba=aba, mapa=mapa)
    taxonomia = Taxonomia(premissas, plugins.categorias_extras)
    estrutura = analisar_estrutura(leitura, taxonomia)

    if ia:
        from . import ia as ia_mod

        ok, motivo = ia_mod.disponivel()
        if ok:
            n = ia_mod.classificar_nao_classificados(estrutura, taxonomia, log=log)
            if n:
                log(f"IA classificou {n} linha(s) que a taxonomia não reconheceu.")
        else:
            log(f"IA indisponível ({motivo}); seguindo só com o motor determinístico.")

    ctx = Contexto(estrutura.itens, estrutura, leitura, premissas, taxonomia)
    oportunidades, registro = executar_detectores(ctx, plugins.detectores)

    # materialidade e prioridade
    minimo = premissas["economia_minima_pct_total"] * estrutura.total_itens
    validas, descartadas = [], []
    for o in oportunidades:
        if o.economia("base") < minimo:
            descartadas.append({"titulo": o.titulo, "detector": o.detector, "economia_base": o.economia("base")})
        else:
            o.prioridade = o.economia("base") * PESO_CONF.get(o.confianca, 0.6) / PESO_ESF.get(o.esforco, 1.3)
            validas.append(o)
    validas.sort(key=lambda o: -o.prioridade)
    for i, o in enumerate(validas, start=1):
        o.id = f"OP-{i:02d}"
    for r in registro:
        r["n_validas"] = sum(1 for o in validas if o.detector == r["id"])

    cenarios = construir_cenarios(estrutura.itens, validas, premissas, taxonomia,
                                  tem_realizado=estrutura.tem.get("realizado", False),
                                  meses_real=leitura.meses_com_realizado, extras=plugins.cenarios_extras)
    por_cat = _por_categoria(estrutura, taxonomia, cenarios)
    pareto = _pareto(estrutura)
    mix = _mix(estrutura)
    insights = _insights(estrutura, por_cat, pareto, mix, premissas, leitura.meses_com_realizado)
    alertas = sorted(ctx.alertas, key=lambda a: (ORDEM_SEVERIDADE.get(a.severidade, 9), -(a.valor or 0)))

    t = _titulo(leitura, titulo)
    ano = leitura.mapeamento.ano_referencia
    db = data_base or (str(ano) if ano else _dt.date.today().strftime("%m/%Y"))
    base = next(c for c in cenarios if c.id == "base")
    cons = next(c for c in cenarios if c.id == "conservador")
    agr = next(c for c in cenarios if c.id == "agressivo")
    top = validas[:3]
    resumo = (f"O orçamento de {brl_curto(estrutura.total_itens)} tem potencial de redução de "
              f"{brl_curto(base.economia)} ({pct(base.economia_pct)}) no cenário base, numa faixa de "
              f"{brl_curto(cons.economia)} (conservador) a {brl_curto(agr.economia)} (agressivo).")
    if top:
        resumo += " As maiores alavancas: " + "; ".join(
            f"{o.titulo} ({brl_curto(o.economia('base'))})" for o in top) + "."
    if not validas:
        resumo = (f"O orçamento de {brl_curto(estrutura.total_itens)} não apresentou oportunidades acima do "
                  "corte de materialidade com os dados disponíveis.")

    meta = {
        "titulo": t, "slug": slug(t), "arquivo": Path(caminho).name,
        "hash": _hash_arquivo(caminho), "aba": leitura.aba, "data_base": db,
        "gerado_em": _dt.datetime.now().replace(microsecond=0).isoformat(),
        "bot": NOME_BOT, "versao_bot": __version__, "formato": leitura.formato_arquivo,
        "ano_referencia": ano,
    }
    return Analise(meta=meta, leitura=leitura, estrutura=estrutura, premissas=premissas, taxonomia=taxonomia,
                   oportunidades=validas, alertas=alertas, cenarios=cenarios, detectores=registro,
                   skills=plugins.skills, por_categoria=por_cat, pareto=pareto, mix=mix, insights=insights,
                   resumo=resumo, descartadas=descartadas)


def resumo_texto(a: Analise) -> str:
    """Resumo para o terminal."""
    linhas = [f"{a.meta['titulo']} — {a.meta['arquivo']} (aba {a.meta['aba']})",
              f"Total analisado: {brl(a.total)} em {len(a.estrutura.itens)} linhas "
              f"({len(a.estrutura.agregadoras)} subtotais/totais excluídos) · conciliação: "
              f"{a.estrutura.conciliacao['status']}", a.resumo, "", "Cenários:"]
    for c in a.cenarios:
        linhas.append(f"  {c.nome:<42} {brl(c.economia):>22}  {pct(c.economia_pct):>7}")
    linhas.append("")
    linhas.append("Top oportunidades:")
    for o in a.oportunidades[:8]:
        linhas.append(f"  {o.id} {o.titulo[:70]:<70} {brl(o.economia('base')):>20}  [{o.confianca}/{o.esforco}]")
    return "\n".join(linhas)
