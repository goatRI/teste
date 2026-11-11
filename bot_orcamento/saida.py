"""Exporta a análise em JSON (para o agente Claude, integrações e auditoria)."""

from __future__ import annotations

import json
from pathlib import Path

from .analise import Analise
from .leitura import ROTULO_CAMPO
from .modelo import NIVEIS, Verificacao


def analise_para_dict(a: Analise, revisao: dict | None = None, verificacoes: list[Verificacao] | None = None) -> dict:
    estr = a.estrutura
    m = a.leitura.mapeamento
    return {
        "meta": a.meta,
        "resumo": a.resumo,
        "insights": a.insights,
        "leitura": {
            "arquivo": Path(a.leitura.arquivo).name, "aba": a.leitura.aba, "linha_cabecalho": a.leitura.linha_cabecalho,
            "formato": m.formato, "ano_referencia": m.ano_referencia,
            "colunas": [{"indice": c.indice, "rotulo": c.rotulo, "campo": c.campo,
                         "campo_legivel": ROTULO_CAMPO.get(c.campo or "", None), "motivo": c.motivo}
                        for c in m.colunas],
            "abas_avaliadas": a.leitura.abas_avaliadas, "avisos": a.leitura.avisos,
        },
        "estrutura": {
            "total_itens": estr.total_itens, "total_declarado": estr.total_declarado,
            "conciliacao": estr.conciliacao, "hierarquia": estr.hierarquia, "grupos": estr.grupos,
            "qualidade": estr.qualidade, "tem": estr.tem, "cobertura_classificacao": estr.cobertura_classificacao,
            "agregadoras": [{"linha_origem": x.linha_origem, "descricao": x.descricao, "tipo": x.tipo,
                             "motivo": x.motivo_tipo, "valor": x.orcado} for x in estr.agregadoras],
        },
        "por_categoria": a.por_categoria,
        "oportunidades": [{**o.para_dict(), "economia": {n: o.economia(n) for n in NIVEIS}} for o in a.oportunidades],
        "alertas": [al.__dict__ for al in a.alertas],
        "cenarios": [{"id": c.id, "nome": c.nome, "descricao": c.descricao, "nota": c.nota,
                      "total_original": c.total_original, "total_adaptado": c.total_adaptado,
                      "economia": c.economia, "economia_pct": c.economia_pct, "selecao": c.selecao,
                      "recomendado": c.recomendado} for c in a.cenarios],
        "detectores": [{k: v for k, v in d.items() if k != "traceback"} for d in a.detectores],
        "skills": [{k: (Path(v).name if k == "pasta" else v) for k, v in sk.items()} for sk in a.skills],
        "premissas": a.premissas,
        "linhas": [x.para_dict() for x in estr.itens],
        "revisao": revisao and {k: v for k, v in revisao.items() if k != "resumo"},
        "verificacoes": [v.__dict__ for v in (verificacoes or [])],
        "parecer": a.parecer,
    }


def exportar_json(a: Analise, destino: str | Path, revisao: dict | None = None,
                  verificacoes: list[Verificacao] | None = None) -> Path:
    destino = Path(destino)
    destino.write_text(json.dumps(analise_para_dict(a, revisao, verificacoes), ensure_ascii=False, indent=2,
                                  default=str), encoding="utf-8")
    return destino
