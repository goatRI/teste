"""Camada opcional de IA (Claude, via API da Anthropic). Ativada com ``--ia``.

Faz duas coisas — e NUNCA altera números:
1. classifica linhas que a taxonomia não reconheceu (escolhendo entre as categorias existentes);
2. redige o parecer executivo a partir dos resultados já calculados pelo motor.

O parecer passa pela revisão do HTML: todo valor em R$ citado nele é conferido contra a
análise (verificação V20). Requer ``pip install anthropic`` e credencial (ANTHROPIC_API_KEY
ou ``ant auth login``). Os dados do orçamento são enviados à API — use só se isso for permitido.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .util import brl_curto, pct

MODELO = os.environ.get("BOT_ORCAMENTO_MODELO", "claude-opus-5-5")
LOTE = 150


def disponivel() -> tuple[bool, str]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "pacote 'anthropic' não instalado (pip install anthropic)"
    tem_cred = any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")) \
        or (Path.home() / ".config" / "anthropic").exists()
    if not tem_cred:
        return False, "sem credencial da API (defina ANTHROPIC_API_KEY ou rode 'ant auth login')"
    return True, ""


def _chamar(system: str, prompt: str, schema: dict, esforco: str = "medium", client: Any = None,
            log=print) -> dict | None:
    """Uma chamada com saída estruturada (JSON Schema). Devolve None em recusa/erro."""
    import anthropic

    client = client or anthropic.Anthropic()
    kwargs = dict(model=MODELO, max_tokens=16000, system=system,
                  messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": esforco, "format": {"type": "json_schema", "schema": schema}})
    try:
        try:
            # fallback no servidor: se o modelo recusar, a API reencaminha para outro modelo
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                               **kwargs)
        except TypeError:  # SDK antigo sem 'fallbacks'
            resp = client.messages.create(**kwargs)
    except anthropic.RateLimitError:
        log("IA: limite de requisições atingido; seguindo sem IA.")
        return None
    except anthropic.APIStatusError as e:
        log(f"IA: erro da API ({e.status_code}); seguindo sem IA.")
        return None
    except anthropic.APIConnectionError:
        log("IA: sem conexão com a API; seguindo sem IA.")
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        log(f"IA: resposta interrompida ({resp.stop_reason}); seguindo sem IA.")
        return None
    texto = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
    if not texto:
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log("IA: resposta fora do formato esperado; ignorada.")
        return None


SYSTEM_CLASSIFICAR = (
    "Você classifica linhas de orçamento empresarial brasileiro em categorias de custo. "
    "Use apenas os ids de categoria fornecidos. Se a descrição for genérica demais, use 'contingencia'; "
    "se for impossível saber, use 'nao_classificado'. Responda só com o JSON pedido."
)


def classificar_nao_classificados(estrutura, taxonomia, client: Any = None, log=print) -> int:
    linhas = [x for x in estrutura.itens if x.categoria == "nao_classificado"]
    if not linhas:
        return 0
    ids = [c.id for c in taxonomia.categorias] + ["nao_classificado"]
    cats_txt = "\n".join(f"- {c.id}: {c.nome}" for c in taxonomia.categorias)
    schema = {
        "type": "object", "additionalProperties": False, "required": ["classificacoes"],
        "properties": {"classificacoes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "categoria"],
            "properties": {"id": {"type": "integer"}, "categoria": {"type": "string", "enum": ids}}}}},
    }
    n = 0
    por_id = {x.id: x for x in linhas}
    for i in range(0, len(linhas), LOTE):
        lote = linhas[i:i + LOTE]
        itens = [{"id": x.id, "descricao": x.descricao, "grupo": x.grupo, "categoria_no_arquivo": x.categoria_origem,
                  "centro_custo": x.centro_custo} for x in lote]
        r = _chamar(SYSTEM_CLASSIFICAR, f"Categorias:\n{cats_txt}\n\nLinhas:\n{json.dumps(itens, ensure_ascii=False)}",
                    schema, "low", client, log)
        for c in (r or {}).get("classificacoes", []):
            lin = por_id.get(c.get("id"))
            if lin is None or c.get("categoria") in (None, "nao_classificado"):
                continue
            cat = taxonomia.get(c["categoria"])
            lin.categoria, lin.categoria_conf, lin.categoria_termo = cat.id, "media", "classificado por IA"
            lin.comportamento, lin.protegida, lin.discricionaria = cat.comportamento, cat.protegida, cat.discricionaria
            n += 1
    if n:
        restantes = [x for x in estrutura.itens if x.categoria == "nao_classificado"]
        total = estrutura.total_itens or 1.0
        estrutura.cobertura_classificacao = 1 - sum(x.orcado for x in restantes) / total
        estrutura.qualidade = [q for q in estrutura.qualidade if q["tipo"] != "nao_classificado"]
        if restantes:
            estrutura.qualidade.append({"tipo": "nao_classificado", "severidade": "baixa",
                                        "linhas": [x.linha_origem for x in restantes][:30],
                                        "mensagem": f"{len(restantes)} linha(s) seguem sem categoria após a IA."})
        estrutura.qualidade.append({"tipo": "classificado_ia", "severidade": "info",
                                    "linhas": [x.linha_origem for x in linhas if x.categoria_termo == "classificado por IA"][:30],
                                    "mensagem": f"{n} linha(s) classificadas por IA (confiança média) — confira na tabela de linhas."})
    return n


SYSTEM_PARECER = (
    "Você é um analista sênior de orçamento e custos escrevendo para a diretoria, em português do Brasil. "
    "Escreva com objetividade, sem jargão de consultoria. Use SOMENTE os números fornecidos no JSON, "
    "exatamente no formato em que aparecem (ex.: 'R$ 17,2 mi', 'R$ 2.006.000,00', '10,6%'); não calcule "
    "valores novos nem invente fatos. Aponte prioridades, riscos e próximos passos práticos."
)


def _resumo_para_ia(a) -> dict:
    base = a.cenario("base")
    return {
        "titulo": a.meta["titulo"], "data_base": a.meta["data_base"],
        "total_orcado": brl_curto(a.total),
        "cenarios": [{"nome": c.nome, "economia": brl_curto(c.economia), "percentual": pct(c.economia_pct),
                      "nota": c.nota} for c in a.cenarios],
        "economia_base": brl_curto(base.economia),
        "maiores_categorias": [{"nome": d["nome"], "orcado": brl_curto(d["orcado"]), "participacao": pct(d["pct"])}
                               for d in a.por_categoria[:8]],
        "oportunidades": [{"id": o.id, "titulo": o.titulo, "economia_base": brl_curto(o.economia("base")),
                           "faixa": f"{brl_curto(o.economia('conservador'))} a {brl_curto(o.economia('agressivo'))}",
                           "confianca": o.confianca, "esforco": o.esforco, "prazo": o.horizonte,
                           "racional": o.racional} for o in a.oportunidades[:12]],
        "riscos": [{"titulo": al.titulo, "detalhe": al.detalhe} for al in a.alertas[:8]],
        "observacoes": a.insights,
        "qualidade_dos_dados": [q["mensagem"] for q in a.estrutura.qualidade][:6],
    }


def gerar_parecer(a, client: Any = None, log=print) -> dict | None:
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["resumo", "destaques", "riscos", "proximos_passos"],
        "properties": {"resumo": {"type": "string"}, "destaques": {"type": "array", "items": {"type": "string"}},
                       "riscos": {"type": "array", "items": {"type": "string"}},
                       "proximos_passos": {"type": "array", "items": {"type": "string"}}},
    }
    prompt = ("Redija o parecer executivo desta análise orçamentária: um parágrafo de resumo (até 90 palavras), "
              "3 a 5 destaques, até 4 riscos e 3 a 5 próximos passos (com quem/quando quando fizer sentido).\n\n"
              + json.dumps(_resumo_para_ia(a), ensure_ascii=False, indent=1))
    r = _chamar(SYSTEM_PARECER, prompt, schema, "medium", client, log)
    if not r:
        return None
    md = [r["resumo"].strip(), "", "### Destaques"] + [f"- {d}" for d in r["destaques"]]
    if r["riscos"]:
        md += ["", "### Riscos"] + [f"- {x}" for x in r["riscos"]]
    md += ["", "### Próximos passos"] + [f"- {x}" for x in r["proximos_passos"]]
    return {"texto": "\n".join(md), "origem": f"Redigido por Claude ({MODELO}) a partir dos números do motor",
            "aviso": "texto gerado por IA — revise antes de distribuir"}
