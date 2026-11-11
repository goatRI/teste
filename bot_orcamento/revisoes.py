"""Controle de revisões do relatório (Rev. 00, 01, ...), como em documento de engenharia.

Cada emissão grava, em ``historico_revisoes.json`` na pasta de saída, um resumo do que o
relatório dizia. A próxima emissão compara com a anterior e lista as alterações. Se nada
mudou (mesmo arquivo, mesmas premissas, mesma versão do bot), não abre revisão nova:
reemite a mesma.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .analise import Analise
from .util import agora_iso, brl, pct


def resumo_analise(a: Analise) -> dict:
    prem = json.dumps(a.premissas, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "arquivo": a.meta["arquivo"], "hash": a.meta["hash"], "aba": a.meta["aba"],
        "versao_bot": a.meta["versao_bot"],
        "hash_premissas": hashlib.sha256(prem.encode()).hexdigest()[:16],
        "premissas": {k: v for k, v in a.premissas.items() if not isinstance(v, (dict, list))},
        "total": round(a.total, 2), "n_linhas": len(a.estrutura.itens),
        "oportunidades": {o.titulo: round(o.economia("base"), 2) for o in a.oportunidades},
        "cenarios": {c.id: round(c.economia, 2) for c in a.cenarios},
        "skills": sorted(f"{s['nome']}:{s['tipo']}" for s in a.skills),
        "hash_parecer": hashlib.sha256((a.parecer or {}).get("texto", "").encode()).hexdigest()[:16]
        if a.parecer else None,
    }


def comparar(ant: dict, atual: dict) -> list[str]:
    alt: list[str] = []
    if ant.get("hash") != atual["hash"]:
        if ant.get("arquivo") != atual["arquivo"]:
            alt.append(f"Base de dados trocada: {ant.get('arquivo')} → {atual['arquivo']}.")
        else:
            alt.append(f"Arquivo de origem alterado (conteúdo novo de {atual['arquivo']}).")
    if abs(ant.get("total", 0) - atual["total"]) > 0.005:
        d = atual["total"] - ant.get("total", 0)
        alt.append(f"Total analisado: {brl(ant.get('total'))} → {brl(atual['total'])} ({'+' if d > 0 else ''}{brl(d)}).")
    if ant.get("n_linhas") != atual["n_linhas"]:
        alt.append(f"Linhas analisadas: {ant.get('n_linhas')} → {atual['n_linhas']}.")
    if ant.get("hash_premissas") != atual["hash_premissas"]:
        mud = [k for k in atual["premissas"] if ant.get("premissas", {}).get(k) != atual["premissas"][k]]
        alt.append("Premissas alteradas" + (f": {', '.join(mud[:6])}." if mud else " (faixas/categorias)."))
    if ant.get("versao_bot") != atual["versao_bot"]:
        alt.append(f"Motor do bot atualizado: v{ant.get('versao_bot')} → v{atual['versao_bot']}.")
    if ant.get("skills") != atual["skills"]:
        novas = sorted(set(atual["skills"]) - set(ant.get("skills", [])))
        if novas:
            alt.append("Skills novas usadas: " + ", ".join(novas) + ".")
    if ant.get("hash_parecer") != atual.get("hash_parecer"):
        if not atual.get("hash_parecer"):
            alt.append("Parecer do analista removido.")
        elif not ant.get("hash_parecer"):
            alt.append("Parecer do analista incluído.")
        else:
            alt.append("Parecer do analista atualizado.")
    ops_a, ops_n = ant.get("oportunidades", {}), atual["oportunidades"]
    novas = [t for t in ops_n if t not in ops_a]
    saiu = [t for t in ops_a if t not in ops_n]
    if novas:
        alt.append(f"{len(novas)} oportunidade(s) nova(s): " + "; ".join(novas[:4]) + ("…" if len(novas) > 4 else "") + ".")
    if saiu:
        alt.append(f"{len(saiu)} oportunidade(s) removida(s): " + "; ".join(saiu[:4]) + ("…" if len(saiu) > 4 else "") + ".")
    b_a, b_n = ant.get("cenarios", {}).get("base"), atual["cenarios"].get("base")
    if b_a is not None and b_n is not None and abs(b_a - b_n) > 0.005:
        alt.append(f"Economia do cenário base: {brl(b_a)} → {brl(b_n)}"
                   + (f" ({pct(b_n / b_a - 1, 1, True)})." if b_a else "."))
    return alt or ["Sem alteração de resultado em relação à revisão anterior."]


class Historico:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.entradas: list[dict] = []
        if self.caminho.exists():
            try:
                self.entradas = json.loads(self.caminho.read_text(encoding="utf-8")).get("revisoes", [])
            except (json.JSONDecodeError, AttributeError):
                self.entradas = []

    def preparar(self, a: Analise, descricao: str | None = None) -> dict:
        """Monta a revisão desta emissão (ainda sem status de verificação)."""
        atual = resumo_analise(a)
        ult = self.entradas[-1] if self.entradas else None
        if ult and ult.get("resumo") == atual and not descricao:
            entrada = dict(ult)
            entrada["data"] = agora_iso()
            entrada["reemissao"] = True
            return entrada
        rev = (ult["rev"] + 1) if ult else 0
        return {
            "rev": rev, "data": agora_iso(),
            "descricao": descricao or ("Emissão inicial" if rev == 0 else "Reemissão com alterações"),
            "alteracoes": comparar(ult["resumo"], atual) if ult else
            [f"Primeira análise de {a.meta['arquivo']} ({len(a.estrutura.itens)} linhas, {brl(a.total)})."],
            "elaborado": f"{a.meta['bot']} v{a.meta['versao_bot']}", "verificado": "", "status": "pendente",
            "resumo": atual, "reemissao": False,
        }

    def linha_do_tempo(self, entrada: dict) -> list[dict]:
        """Histórico como ficará após registrar ``entrada`` (para o relatório)."""
        outras = [e for e in self.entradas if e["rev"] != entrada["rev"]]
        return sorted(outras + [entrada], key=lambda e: e["rev"])

    def registrar(self, entrada: dict) -> None:
        self.entradas = self.linha_do_tempo(entrada)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(json.dumps({"revisoes": self.entradas}, ensure_ascii=False, indent=2),
                                encoding="utf-8")
