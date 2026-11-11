"""Revisão automática do relatório: lê o ARQUIVO HTML FINAL e confere tudo.

Não confia no objeto em memória: abre o .html gravado, extrai os números exibidos
(``data-check``), o JSON embutido e o texto visível, e confere:

* estrutura: HTML bem formado, seções obrigatórias, autocontido, tamanho;
* números: cada valor exibido × dado, cenários recalculados de forma independente a partir
  do JSON, coerência (conservador ≤ base ≤ agressivo), totais × soma das linhas;
* texto: nada de NaN/None/undefined/{{ }}, moeda no formato pt-BR, rodapé com fonte;
* navegador (Chromium/Playwright, se disponível): sem erro de JS, simulador recalcula igual
  ao cenário base, troca de cenário funciona, sem rolagem horizontal no celular;
  gera screenshots para a leitura visual.

Uso isolado: ``python -m bot_orcamento revisar relatorio.html [--fonte planilha.xlsx]``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .modelo import Verificacao
from .util import brl, ler_brl, normalizar, pct

SECOES = ["resumo", "estrutura", "raio-x", "oportunidades", "cenarios", "simulador", "plano", "riscos",
          "premissas", "revisoes"]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr", "path", "circle", "line", "rect", "stop"}
ARTEFATOS = [r"\bNaN\b", r"\bnan\b", r"\bNone\b", r"\bundefined\b", r"\bnull\b", r"\{\{", r"\}\}",
             r"\{%", r"%\}", r"\bInfinity\b", r"\[object Object\]", r"R\$ -?0,00 mi"]
RX_MOEDA = re.compile(r"R\$\s?[-+]?[\d.,]+(?:\s(?:mi|mil|bi)\b)?")
RX_MOEDA_OK = re.compile(r"^R\$ -?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?(?: (?:mi|mil|bi))?$")


class _Leitor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pilha: list[str] = []
        self.erros: list[str] = []
        self.checks: list[dict] = []
        self._cap: list[dict] = []
        self.secoes: list[str] = []
        self.scripts_src: list[str] = []
        self.links: list[dict] = []
        self.imgs: list[dict] = []
        self.svgs: list[dict] = []
        self.titulo = ""
        self.lang = ""
        self.charset = False
        self.texto: list[str] = []
        self.texto_conteudo: list[str] = []  # tudo menos a seção de revisões (que cita os próprios testes)
        self._revisoes_prof = -1
        self.rodape: list[str] = []
        self.parecer: list[str] = []
        self.data_json = ""
        self.tabelas: dict[str, bool] = {}
        self.n_acao = 0
        self.n_op_cards = 0
        self.ids: list[str] = []
        self.sem_rotulo: list[str] = []
        self._em = {"script": 0, "style": 0, "title": 0, "footer": 0, "parecer": 0}
        self._script_data = False
        self._tabela_atual: list[str] = []
        self._parecer_prof = -1

    # -------------------------------------------------- tags
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang", "")
        if tag == "meta" and ("charset" in a):
            self.charset = True
        if tag == "section" and a.get("id"):
            self.secoes.append(a["id"])
            if a["id"] == "revisoes":
                self._revisoes_prof = len(self.pilha) + 1
        if tag == "script":
            self._em["script"] += 1
            if a.get("src"):
                self.scripts_src.append(a["src"])
            self._script_data = a.get("id") == "DATA"
        if tag == "style":
            self._em["style"] += 1
        if tag == "title" and not self.titulo and not self.svgs:  # só o <title> do documento, não os de SVG
            self._em["title"] += 1
        if tag == "footer":
            self._em["footer"] += 1
        if tag == "link":
            self.links.append(a)
        if tag == "img":
            self.imgs.append(a)
        if tag == "svg":
            self.svgs.append(a)
        if tag in ("select", "input") and a.get("type") not in ("hidden", "file") and not a.get("aria-label") \
                and not a.get("id"):
            self.sem_rotulo.append(tag)
        if tag == "table":
            tid = a.get("id") or f"_t{len(self.tabelas)}"
            self.tabelas[tid] = False
            self._tabela_atual.append(tid)
        if tag == "tfoot" and self._tabela_atual:
            self.tabelas[self._tabela_atual[-1]] = True
        cls = a.get("class", "").split()
        if "acao" in cls:
            self.n_acao += 1
        if "op-card" in cls:
            self.n_op_cards += 1
        if tag not in VOID:
            self.pilha.append(tag)
            if "parecer" in cls and self._parecer_prof < 0:
                self._parecer_prof = len(self.pilha)
                self._em["parecer"] = 1
            if "data-check" in a:
                self._cap.append({"attrs": a, "texto": [], "prof": len(self.pilha)})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if tag == "script":
            self._em["script"] = max(0, self._em["script"] - 1)
            self._script_data = False
        if tag == "style":
            self._em["style"] = max(0, self._em["style"] - 1)
        if tag == "title":
            self._em["title"] = max(0, self._em["title"] - 1)
        if tag == "footer":
            self._em["footer"] = max(0, self._em["footer"] - 1)
        if tag == "table" and self._tabela_atual:
            self._tabela_atual.pop()
        if not self.pilha:
            self.erros.append(f"</{tag}> sem abertura")
            return
        if self.pilha[-1] == tag:
            self.pilha.pop()
        elif tag in self.pilha:
            while self.pilha and self.pilha[-1] != tag:
                self.erros.append(f"<{self.pilha.pop()}> não fechado antes de </{tag}>")
            self.pilha.pop()
        else:
            self.erros.append(f"</{tag}> sem abertura correspondente")
            return
        while self._cap and len(self.pilha) < self._cap[-1]["prof"]:
            c = self._cap.pop()
            self.checks.append({"chave": c["attrs"].get("data-check"), "valor": c["attrs"].get("data-valor"),
                                "fmt": c["attrs"].get("data-fmt", "brl"), "texto": "".join(c["texto"]).strip(),
                                "id": c["attrs"].get("id")})
        if self._revisoes_prof >= 0 and len(self.pilha) < self._revisoes_prof:
            self._revisoes_prof = -1
        if self._parecer_prof >= 0 and len(self.pilha) < self._parecer_prof:
            self._parecer_prof = -1
            self._em["parecer"] = 0

    def handle_data(self, data: str) -> None:
        if self._em["script"]:
            if self._script_data:
                self.data_json += data
            return
        if self._em["style"]:
            return
        if self._em["title"]:
            self.titulo += data
        self.texto.append(data)
        if self._revisoes_prof < 0:
            self.texto_conteudo.append(data)
        if self._em["footer"]:
            self.rodape.append(data)
        if self._em["parecer"]:
            self.parecer.append(data)
        for c in self._cap:
            c["texto"].append(data)


# ------------------------------------------------------------------ recálculo independente


def _recalcular(dados: dict, selecao: dict[str, str]) -> float:
    niv = ["conservador", "base", "agressivo"]
    teto = dados["premissas"]["teto_reducao_linha"]
    fator = {lin["id"]: 1.0 for lin in dados["linhas"]}
    total_ok = {lin["id"]: False for lin in dados["linhas"]}
    for o in dados["oportunidades"]:
        n = selecao.get(o["id"])
        if n not in niv:
            continue
        k = niv.index(n) + 1
        for r in o["l"]:
            if r[0] in fator:
                fator[r[0]] *= (1.0 - r[k])
                if o["pt"]:
                    total_ok[r[0]] = True
    soma = 0.0
    for lin in dados["linhas"]:
        red = min(1.0 - fator[lin["id"]], 1.0 if total_ok[lin["id"]] else teto)
        soma += round(lin["orc"] * (1.0 - red), 2) if lin["orc"] > 0 else lin["orc"]
    return soma


def _esperados(dados: dict) -> dict[str, float]:
    esp: dict[str, float] = {}
    soma = sum(lin["orc"] for lin in dados["linhas"])
    esp["total_orcado"] = soma
    if dados["totais"].get("declarado") is not None:
        esp["total_declarado"] = dados["totais"]["declarado"]
    esp["n_linhas"] = len(dados["linhas"])
    esp["n_oportunidades"] = len(dados["oportunidades"])
    for c in dados["cenarios"]:
        esp[f"cenario:{c['id']}:economia"] = c["economia"]
        esp[f"cenario:{c['id']}:adaptado"] = c["total_adaptado"]
        esp[f"cenario:{c['id']}:pct"] = c["pct"]
        if c["id"] == "base":
            esp["sim:economia"] = c["economia"]
    for o in dados["oportunidades"]:
        for n, v in o["eco"].items():
            esp[f"op:{o['id']}:{n}"] = v
    cats: dict[str, float] = {}
    for lin in dados["linhas"]:
        cats[lin["cat"]] = cats.get(lin["cat"], 0.0) + lin["orc"]
    for k, v in cats.items():
        esp[f"cat:{k}:orcado"] = v
    return esp


def _tolerancia_exibicao(texto: str, fmt: str) -> float:
    if fmt == "pct":
        return 0.0006
    if fmt == "int":
        return 0.5
    t = texto.strip()
    for suf, mult in ((" bi", 1e9), (" mi", 1e6), (" mil", 1e3)):
        if t.endswith(suf):
            casas = len(t[: -len(suf)].split(",")[1]) if "," in t else 0
            return 0.51 * mult * 10 ** (-casas)
    return 0.0051 if fmt == "brl" else 0.51


def _ler_exibido(texto: str, fmt: str) -> float | None:
    t = texto.strip()
    if fmt == "int":
        try:
            return float(t.replace(".", ""))
        except ValueError:
            return None
    return ler_brl(t)


# ------------------------------------------------------------------ verificações estáticas


def revisar_html(caminho: str | Path, total_esperado: float | None = None) -> list[Verificacao]:
    caminho = Path(caminho)
    html = caminho.read_text(encoding="utf-8")
    p = _Leitor()
    p.feed(html)
    p.close()
    V: list[Verificacao] = []

    def add(id_, nome, status, detalhe="", grupo="Estrutura do HTML"):
        V.append(Verificacao(id_, nome, status, detalhe, grupo))

    # ---- estrutura
    erros = p.erros + [f"<{t}> não fechado no fim do arquivo" for t in p.pilha if t not in ("html", "body")]
    add("V01", "HTML bem formado (todas as tags abertas são fechadas)", "ok" if not erros else "falha",
        "Nenhum erro de aninhamento." if not erros else f"{len(erros)} problema(s): " + "; ".join(erros[:4]))
    cab_ok = html.lstrip().lower().startswith("<!doctype html>") and p.lang.lower() == "pt-br" and p.charset \
        and p.titulo.strip()
    add("V02", "Cabeçalho do documento (doctype, idioma pt-BR, charset, título)", "ok" if cab_ok else "falha",
        f"lang='{p.lang}', título='{p.titulo.strip()[:70]}'")
    faltando = [s for s in SECOES if s not in p.secoes]
    fora_ordem = [s for s in SECOES if s in p.secoes] != [s for s in p.secoes if s in SECOES]
    add("V03", "Seções obrigatórias presentes e na ordem", "falha" if faltando else ("alerta" if fora_ordem else "ok"),
        "Faltando: " + ", ".join(faltando) if faltando else f"{len(SECOES)} seções: " + " → ".join(SECOES))
    externos = [s for s in p.scripts_src] + [i.get("src", "") for i in p.imgs if i.get("src", "").startswith("http")]
    css_ext = [lk.get("href", "") for lk in p.links if lk.get("rel") == "stylesheet"
               and not lk.get("href", "").startswith("https://fonts.googleapis.com")]
    add("V04", "Arquivo autocontido (abre sem internet)", "falha" if (externos or css_ext) else "ok",
        "Só as fontes vêm do Google Fonts e degradam para fontes do sistema sem internet."
        if not (externos or css_ext) else "Dependências externas: " + ", ".join((externos + css_ext)[:4]))
    dados: dict[str, Any] | None = None
    try:
        dados = json.loads(p.data_json)
        n_lin = len(dados["linhas"])
        ok_n = n_lin == dados["totais"]["n_itens"]
        add("V05", "Dados embutidos (JSON) válidos e completos", "ok" if ok_n else "falha",
            f"{n_lin} linhas, {len(dados['oportunidades'])} oportunidades, {len(dados['cenarios'])} cenários.")
    except Exception as e:
        add("V05", "Dados embutidos (JSON) válidos e completos", "falha", f"JSON inválido: {e}")
    caminhos = sorted(set(re.findall(r"(?:[A-Za-z]:\\\\Users\\\\[^\\\"<]+|[A-Za-z]:\\Users\\[^\\\"<]+|/home/[^/\"<\s]+|/Users/[^/\"<\s]+)", html)))
    add("V06b", "Sem caminhos locais ou nomes de usuário da máquina no arquivo", "falha" if caminhos else "ok",
        "Nenhum caminho de pasta pessoal encontrado." if not caminhos else "Encontrado: " + ", ".join(caminhos[:3]))
    tam = caminho.stat().st_size
    add("V06", "Tamanho do arquivo", "ok" if tam < 5e6 else ("alerta" if tam < 16e6 else "falha"),
        f"{tam / 1024:.0f} KB")
    if dados is None:
        return V

    # ---- números
    G = "Números"
    soma = sum(lin["orc"] for lin in dados["linhas"])
    tot_checks = [c for c in p.checks if c["chave"] == "total_orcado"]
    difs = [c for c in tot_checks if abs(float(c["valor"]) - soma) > 0.011]
    det = f"Soma das {len(dados['linhas'])} linhas = {brl(soma)}; {len(tot_checks)} ocorrência(s) no HTML."
    if total_esperado is not None and abs(total_esperado - soma) > 0.011:
        difs.append({"valor": total_esperado})
        det += f" Recalculado da fonte: {brl(total_esperado)} (DIFERENTE)."
    elif total_esperado is not None:
        det += " Confere com a releitura independente do arquivo de origem."
    add("V07", "Total exibido = soma das linhas do orçamento", "ok" if tot_checks and not difs else "falha", det, G)
    dec = dados["totais"].get("declarado")
    if dec is not None:
        ok = abs(soma - dec) <= max(1.0, 0.001 * abs(dec))
        add("V08", "Soma dos itens confere com o total declarado no arquivo", "ok" if ok else "alerta",
            f"Itens {brl(soma)} × declarado {brl(dec)}" + ("" if ok else " — divergência vem do arquivo de origem."), G)
    else:
        add("V08", "Soma dos itens confere com o total declarado no arquivo", "pulado",
            "O arquivo não tem linha de total geral.", G)
    tol_cen = 0.05 + 0.006 * len(dados["linhas"])
    ruins = []
    for c in dados["cenarios"]:
        if c["por_oportunidade"]:
            rec = _recalcular(dados, c["selecao"])
        else:
            vals = {int(k): v for k, v in c["v"].items()}
            rec = sum(vals.get(lin["id"], lin["orc"]) for lin in dados["linhas"])
        if abs(rec - c["total_adaptado"]) > tol_cen:
            ruins.append(f"{c['nome']}: recalculado {brl(rec)} × exibido {brl(c['total_adaptado'])}")
        if abs((c["total_original"] - c["total_adaptado"]) - c["economia"]) > 0.02:
            ruins.append(f"{c['nome']}: economia ≠ original − adaptado")
        if c["total_original"] and abs(c["economia"] / c["total_original"] - c["pct"]) > 1e-5:
            ruins.append(f"{c['nome']}: % de redução inconsistente")
    add("V09", "Cenários recalculados de forma independente a partir dos dados", "ok" if not ruins else "falha",
        f"{len(dados['cenarios'])} cenários recalculados linha a linha." if not ruins else "; ".join(ruins[:4]), G)
    esp = _esperados(dados)
    erros_v, sem_ref = [], 0
    for c in p.checks:
        try:
            val = float(c["valor"])
        except (TypeError, ValueError):
            erros_v.append(f"{c['chave']}: data-valor inválido")
            continue
        exib = _ler_exibido(c["texto"], c["fmt"])
        if exib is None:
            erros_v.append(f"{c['chave']}: texto '{c['texto']}' ilegível")
        elif abs(exib - val) > _tolerancia_exibicao(c["texto"], c["fmt"]):
            erros_v.append(f"{c['chave']}: exibe '{c['texto']}' mas o valor é {val}")
        ref = esp.get(c["chave"])
        if ref is None:
            sem_ref += 1
        elif abs(ref - val) > (1e-6 if c["fmt"] == "pct" else 0.011):
            erros_v.append(f"{c['chave']}: HTML {val} × dados {ref:.2f}")
    add("V10", "Cada número exibido confere com os dados", "ok" if not erros_v else "falha",
        f"{len(p.checks)} valores conferidos (texto exibido × valor × dado de origem)." if not erros_v
        else f"{len(erros_v)} divergência(s): " + "; ".join(erros_v[:4]), G)
    eco = {c["id"]: c["economia"] for c in dados["cenarios"]}
    ordem_ok = eco.get("conservador", 0) <= eco.get("base", 0) + 0.01 <= eco.get("agressivo", 0) + 0.02
    add("V11", "Ordem lógica: conservador ≤ base ≤ agressivo", "ok" if ordem_ok else "falha",
        f"{brl(eco.get('conservador'))} ≤ {brl(eco.get('base'))} ≤ {brl(eco.get('agressivo'))}", G)
    probl = []
    for c in dados["cenarios"]:
        if c["id"] != "realinhamento" and not (-0.01 <= c["economia"] <= soma + 0.01):
            probl.append(f"cenário {c['nome']} fora de [0, total]")
    base_lin = {lin["id"]: lin["orc"] for lin in dados["linhas"]}
    for o in dados["oportunidades"]:
        e = o["eco"]
        if not (-0.01 <= e["conservador"] <= e["base"] + 0.01 <= e["agressivo"] + 0.02):
            probl.append(f"{o['id']}: faixa fora de ordem")
        if e["agressivo"] > sum(base_lin.get(r[0], 0) for r in o["l"]) + 0.01:
            probl.append(f"{o['id']}: economia maior que a base afetada")
    add("V12", "Economias dentro dos limites (≥ 0 e ≤ valor afetado)", "ok" if not probl else "falha",
        "Todas as oportunidades e cenários dentro dos limites." if not probl else "; ".join(probl[:4]), G)
    cat_vals = [float(c["valor"]) for c in p.checks if c["chave"].startswith("cat:")]
    if cat_vals:
        ok = abs(sum(cat_vals) - soma) <= 0.02 * max(1, len(cat_vals))
        add("V13", "Soma das categorias = total", "ok" if ok else "falha",
            f"{len(cat_vals)} categorias somam {brl(sum(cat_vals))}.", G)
    ids_op = [o["id"] for o in dados["oportunidades"]]
    completo = p.n_acao == len(ids_op) == p.n_op_cards and len(set(ids_op)) == len(ids_op) \
        and all(i in p.ids for i in ids_op)
    add("V14", "Cada oportunidade tem cartão, ação recomendada e âncora própria", "ok" if completo else "falha",
        f"{len(ids_op)} oportunidades, {p.n_op_cards} cartões, {p.n_acao} ações recomendadas.", G)

    # ---- texto e formatação
    G = "Texto e formatação"
    visivel = " ".join(p.texto)
    conteudo = " ".join(p.texto_conteudo)
    achados = []
    for rx in ARTEFATOS:
        m = re.search(rx, conteudo)
        if m:
            ini = max(0, m.start() - 30)
            achados.append(f"marcador inválido em “…{conteudo[ini:m.start()].strip()} ⟨?⟩ {conteudo[m.end():m.end() + 30].strip()}…”")
    add("V15", "Sem valores nulos, não numéricos ou marcadores de template no texto", "ok" if not achados else "falha",
        "Nenhum artefato de geração no texto visível." if not achados else "; ".join(achados[:3]), G)
    moedas = RX_MOEDA.findall(visivel)
    ruins_m = sorted({m for m in moedas if not RX_MOEDA_OK.match(m.strip().rstrip(".,"))})
    add("V16", "Valores monetários no padrão pt-BR (R$ 1.234,56)", "ok" if not ruins_m else "falha",
        f"{len(moedas)} valores em reais conferidos." if not ruins_m else "Fora do padrão: " + ", ".join(ruins_m[:5]), G)
    rod = " ".join(p.rodape)
    ok_rod = "Fonte:" in rod and "data-base" in rod and dados["meta"]["arquivo"] in rod
    add("V17", "Rodapé cita fonte, data-base e revisão", "ok" if ok_rod and "Rev." in rod else "falha",
        rod.strip()[:140], G)
    svg_sem = [s for s in p.svgs if not (s.get("role") == "img" and s.get("aria-label"))]
    add("V18", "Acessibilidade básica (gráficos e campos rotulados)",
        "ok" if not svg_sem and not p.sem_rotulo else "alerta",
        f"{len(p.svgs)} gráfico(s) SVG com descrição; campos de formulário rotulados."
        if not svg_sem and not p.sem_rotulo else f"{len(svg_sem)} SVG sem aria-label; {len(p.sem_rotulo)} campo(s) sem rótulo.", G)
    obrig = [t for t in ("tab-ops", "tab-linhas") if t in p.tabelas]
    sem_tf = [t for t in obrig if not p.tabelas[t]]
    add("V19", "Tabelas de valores têm linha de total", "ok" if not sem_tf else "falha",
        f"{sum(1 for v in p.tabelas.values() if v)} tabela(s) com total." if not sem_tf else "Sem total: " + ", ".join(sem_tf), G)
    if p.parecer:
        texto_par = " ".join(p.parecer)
        conhecidos = list(esp.values()) + [o["eco"][n] for o in dados["oportunidades"] for n in o["eco"]] \
            + [lin["orc"] for lin in dados["linhas"]]
        citados = [m for m in RX_MOEDA.findall(texto_par)]
        sem_base = []
        for m in citados:
            v = ler_brl(m.strip().rstrip(".,"))
            if v is None:
                continue
            tol = _tolerancia_exibicao(m.strip().rstrip(".,"), "brl_curto")
            if not any(abs(v - k) <= max(tol, 0.011) for k in conhecidos):
                sem_base.append(m)
        add("V20", "Valores citados no parecer existem na análise", "ok" if not sem_base else "alerta",
            f"{len(citados)} valor(es) citados conferidos." if not sem_base
            else "Sem correspondência nos dados: " + ", ".join(sem_base[:5]) + " — revisar o texto do parecer.", G)
    return V


# ------------------------------------------------------------------ navegador

JS_PRONTO = "() => document.documentElement.getAttribute('data-pronto') === '1'"
JS_SIM = "() => { const e = document.getElementById('sim-eco'); return e ? parseFloat(e.getAttribute('data-valor')) : null; }"
JS_CENARIO = """() => {
  const ch = document.querySelector('#chips-cen .chip[data-cen="agressivo"]'); if (!ch) return null; ch.click();
  const d = document.querySelector('.cen-det[data-cen="agressivo"]'); const b = document.querySelector('.cen-det[data-cen="base"]');
  const ok = !!d && getComputedStyle(d).display !== 'none' && (!b || getComputedStyle(b).display === 'none');
  const v = document.querySelector('#chips-cen .chip[data-cen="base"]'); if (v) v.click(); return ok; }"""
JS_SIM_MUDA = """() => {
  const s = document.querySelector('.sim-sel'); const e = document.getElementById('sim-eco'); if (!s || !e) return null;
  const antes = parseFloat(e.getAttribute('data-valor')); s.value = 'fora'; s.dispatchEvent(new Event('change'));
  const depois = parseFloat(e.getAttribute('data-valor')); s.value = 'base'; s.dispatchEvent(new Event('change'));
  return {antes, depois, volta: parseFloat(e.getAttribute('data-valor'))}; }"""
JS_VAZIAS = "() => Array.from(document.querySelectorAll('section.secao')).filter(s => s.innerText.trim().length < 80).map(s => s.id)"
JS_MOBILE = "() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})"

_JS_NODE = r"""
const { chromium } = require('playwright');
(async () => {
  const [,, arquivo, shotDesk, shotMob, pdfPath, exe] = process.argv;
  const out = {erros: [], console: [], externas: 0};
  const browser = await chromium.launch(exe ? {executablePath: exe} : {});
  const offline = async (page) => {
    await page.route('**/*', r => { if (r.request().url().startsWith('file:')) return r.continue(); out.externas++; return r.abort(); });
  };
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    page.on('pageerror', e => out.erros.push(String(e)));
    page.on('console', m => { if (m.type() === 'error' && !/ERR_FAILED|net::/.test(m.text())) out.console.push(m.text()); });
    await offline(page);
    await page.goto('file://' + arquivo, {waitUntil: 'load', timeout: 60000});
    await page.waitForTimeout(600);
    out.pronto = await page.evaluate(@@PRONTO@@);
    out.sim = await page.evaluate(@@SIM@@);
    out.cenario_ok = await page.evaluate(@@CENARIO@@);
    out.sim_muda = await page.evaluate(@@SIM_MUDA@@);
    out.vazias = await page.evaluate(@@VAZIAS@@);
    if (shotDesk) await page.screenshot({path: shotDesk, fullPage: true});
    if (pdfPath) { await page.emulateMedia({media: 'print'}); await page.pdf({path: pdfPath, format: 'A4', landscape: true, printBackground: true, margin: {top: '10mm', bottom: '10mm', left: '10mm', right: '10mm'}}); }
    const m = await browser.newPage({viewport: {width: 390, height: 844}});
    m.on('pageerror', e => out.erros.push('celular: ' + String(e)));
    await offline(m);
    await m.goto('file://' + arquivo, {waitUntil: 'load', timeout: 60000});
    await m.waitForTimeout(400);
    out.mobile = await m.evaluate(@@MOBILE@@);
    if (shotMob) await m.screenshot({path: shotMob, fullPage: false});
  } finally { await browser.close(); }
  console.log('@@RESULTADO@@' + JSON.stringify(out));
})().catch(e => { console.log('@@RESULTADO@@' + JSON.stringify({fatal: String(e)})); });
""".replace("@@PRONTO@@", JS_PRONTO).replace("@@SIM@@", JS_SIM).replace("@@CENARIO@@", JS_CENARIO) \
   .replace("@@SIM_MUDA@@", JS_SIM_MUDA).replace("@@VAZIAS@@", JS_VAZIAS).replace("@@MOBILE@@", JS_MOBILE)


def _executavel_chromium() -> str:
    for c in (os.environ.get("BOT_ORCAMENTO_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if c and Path(c).exists():
            return c
    return ""


def _navegador_node(arquivo: Path, shot_d: str, shot_m: str, pdf: str) -> dict | None:
    if not shutil.which("node"):
        return None
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "revisar.js"
        script.write_text(_JS_NODE, encoding="utf-8")
        try:
            r = subprocess.run(["node", str(script), str(arquivo.resolve()), shot_d, shot_m, pdf, ""],
                               capture_output=True, text=True, timeout=180)
        except (subprocess.TimeoutExpired, OSError):
            return None
        saida = r.stdout + r.stderr
        if "Cannot find module 'playwright'" in saida:
            return None
        m = re.search(r"@@RESULTADO@@(.*)", r.stdout)
        if not m:
            return {"fatal": saida.strip()[-400:]}
        return json.loads(m.group(1))


def _navegador_python(arquivo: Path, shot_d: str, shot_m: str, pdf: str) -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    out: dict[str, Any] = {"erros": [], "console": [], "externas": 0}
    url = arquivo.resolve().as_uri()

    def offline(page):
        def rota(r):
            if r.request.url.startswith("file:"):
                return r.continue_()
            out["externas"] += 1
            return r.abort()
        page.route("**/*", rota)

    try:
        with sync_playwright() as pw:
            exe = _executavel_chromium()
            try:
                b = pw.chromium.launch()
            except Exception:
                b = pw.chromium.launch(executable_path=exe) if exe else None
            if b is None:
                return None
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.on("pageerror", lambda e: out["erros"].append(str(e)))
            offline(pg)
            pg.goto(url, wait_until="load", timeout=60000)
            pg.wait_for_timeout(600)
            out["pronto"] = pg.evaluate(JS_PRONTO)
            out["sim"] = pg.evaluate(JS_SIM)
            out["cenario_ok"] = pg.evaluate(JS_CENARIO)
            out["sim_muda"] = pg.evaluate(JS_SIM_MUDA)
            out["vazias"] = pg.evaluate(JS_VAZIAS)
            if shot_d:
                pg.screenshot(path=shot_d, full_page=True)
            if pdf:
                pg.emulate_media(media="print")
                pg.pdf(path=pdf, format="A4", landscape=True, print_background=True)
            mb = b.new_page(viewport={"width": 390, "height": 844})
            offline(mb)
            mb.goto(url, wait_until="load", timeout=60000)
            mb.wait_for_timeout(400)
            out["mobile"] = mb.evaluate(JS_MOBILE)
            if shot_m:
                mb.screenshot(path=shot_m)
            b.close()
    except Exception as e:  # pragma: no cover - depende do ambiente
        return {"fatal": f"{type(e).__name__}: {e}"}
    return out


def revisar_navegador(caminho: str | Path, economia_base: float, total: float, pasta_shots: str | Path | None = None,
                      pdf: str | Path | None = None) -> list[Verificacao]:
    caminho = Path(caminho)
    G = "Navegador"
    shot_d = shot_m = ""
    if pasta_shots:
        Path(pasta_shots).mkdir(parents=True, exist_ok=True)
        shot_d = str(Path(pasta_shots) / "relatorio-desktop.png")
        shot_m = str(Path(pasta_shots) / "relatorio-celular.png")
    res = _navegador_python(caminho, shot_d, shot_m, str(pdf or ""))
    if res is None or res.get("fatal"):
        res2 = _navegador_node(caminho, shot_d, shot_m, str(pdf or ""))
        res = res2 if res2 is not None else res
    if res is None:
        return [Verificacao("V21", "Renderização no navegador", "pulado",
                            "Playwright não disponível (pip install playwright ou npm i playwright).", G)]
    if res.get("fatal"):
        return [Verificacao("V21", "Renderização no navegador", "alerta",
                            "Não foi possível abrir o navegador: " + str(res["fatal"])[:200], G)]
    V = []
    erros = res.get("erros", []) + res.get("console", [])
    V.append(Verificacao("V21", "Abre no navegador sem erro de JavaScript (offline)",
                         "ok" if not erros and res.get("pronto") else "falha",
                         "Página carregada sem internet; script concluído." if not erros and res.get("pronto")
                         else "; ".join(erros[:3]) or "script não concluiu", G))
    sim = res.get("sim")
    tol = max(1.0, 1e-6 * abs(total))
    ok = sim is not None and abs(sim - economia_base) <= tol
    V.append(Verificacao("V22", "Simulador recalcula no navegador igual ao cenário base", "ok" if ok else "falha",
                         f"Navegador: {brl(sim) if sim is not None else '—'} × Python: {brl(economia_base)}", G))
    sm = res.get("sim_muda")
    cen_ok = res.get("cenario_ok")
    inter_ok = (cen_ok in (True, None)) and (sm is None or (sm["depois"] <= sm["antes"] and abs(sm["volta"] - sm["antes"]) < 0.02))
    V.append(Verificacao("V23", "Interatividade (troca de cenário e simulação)", "ok" if inter_ok else "alerta",
                         "Troca de cenário e desligar/religar oportunidade funcionam." if inter_ok
                         else f"cenário={cen_ok}, simulação={sm}", G))
    mob = res.get("mobile") or {}
    ok_m = mob and mob.get("scroll", 0) <= mob.get("client", 0) + 1
    V.append(Verificacao("V24", "Layout no celular (390 px) sem rolagem horizontal", "ok" if ok_m else "alerta",
                         f"largura do conteúdo {mob.get('scroll')} px × tela {mob.get('client')} px", G))
    vaz = res.get("vazias") or []
    V.append(Verificacao("V25", "Nenhuma seção renderizada vazia", "ok" if not vaz else "falha",
                         "Todas as seções têm conteúdo." if not vaz else "Vazias: " + ", ".join(vaz), G))
    if shot_d:
        V.append(Verificacao("V26", "Capturas de tela para leitura visual", "ok" if Path(shot_d).exists() else "alerta",
                             f"{Path(shot_d).name} e {Path(shot_m).name} gravados em {Path(shot_d).parent.name}/", G))
    return V


def resumo_status(verificacoes: list[Verificacao]) -> str:
    f = sum(1 for v in verificacoes if v.status == "falha")
    a = sum(1 for v in verificacoes if v.status == "alerta")
    if f:
        return "reprovado"
    return "ressalvas" if a else "aprovado"


def assinatura(verificacoes: list[Verificacao]) -> list[tuple[str, str]]:
    return [(v.id, v.status) for v in verificacoes]


def texto_checklist(verificacoes: list[Verificacao]) -> str:
    sim = {"ok": "✔", "alerta": "!", "falha": "✘", "pulado": "–"}
    return "\n".join(f"  {sim.get(v.status, '?')} {v.id} {v.nome} — {v.detalhe}" for v in verificacoes)


__all__ = ["revisar_html", "revisar_navegador", "resumo_status", "texto_checklist", "normalizar", "pct"]
