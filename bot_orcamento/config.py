"""Premissas da análise. Todas podem ser sobrescritas por um JSON (``--config``).

As faixas de redução por categoria são referências usuais de programas de redução de
custos — NÃO são fatos sobre o seu orçamento. O relatório lista cada premissa usada para
que o leitor saiba de onde vem cada número e possa ajustá-las.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PREMISSAS_PADRAO: dict[str, Any] = {
    # inflação de referência para comparar crescimento contra o ano anterior
    "ipca": 0.045,
    # crescimento tolerado acima da inflação antes de virar oportunidade (pontos percentuais)
    "tolerancia_crescimento_pp": 0.05,
    # realizado abaixo de (1 - x) do orçado = folga orçamentária
    "limiar_subexecucao": 0.15,
    # realizado acima de (1 + x) do orçado = risco de estouro
    "limiar_estouro": 0.10,
    # margem de segurança ao realinhar uma linha ao ritmo real
    "margem_realinhamento": 0.05,
    # meta de redução usada no cenário "Meta" e no comparativo de corte linear
    "meta_reducao": 0.10,
    # redução máxima acumulada numa mesma linha (exceto duplicidades)
    "teto_reducao_linha": 0.60,
    # horas extras acima deste % da folha (salários) viram oportunidade
    "limite_horas_extras": 0.05,
    # oportunidade só entra no relatório se a economia base passar deste % do total
    "economia_minima_pct_total": 0.0005,
    # categoria só recebe alavanca se pesar mais que este % do total
    "peso_minimo_categoria": 0.003,
    # picos mensais: mês > média + k·desvio, e dezembro > fator × média dos demais
    "sigma_pico": 2.2,
    "fator_dezembro": 1.6,
    # similaridade mínima de descrição para suspeita de duplicidade (0..1)
    "similaridade_duplicidade": 0.86,
    # estimativas sem memória de cálculo: valor mínimo e múltiplo "redondo"
    "estimativa_valor_minimo": 100_000.0,
    "estimativa_multiplo": 50_000.0,
    # rubricas genéricas (diversos/outros/contingência) acima deste % do total
    "participacao_generica": 0.01,
    # categorias protegidas: não recebem corte linear nem alavanca automática
    "protegidas": ["ssma", "impostos", "depreciacao", "financeiras"],
    # sobrescritas de faixa por categoria: {"viagens": [0.1, 0.2, 0.3]}
    "faixas": {},
    # palavras-chave extras por categoria: {"combustiveis": ["arla 32"]}
    "palavras_extras": {},
}

DESCRICAO_PREMISSAS = {
    "ipca": "Inflação de referência para comparar o crescimento contra o ano anterior",
    "tolerancia_crescimento_pp": "Crescimento tolerado acima da inflação antes de sinalizar",
    "limiar_subexecucao": "Execução abaixo do orçado que caracteriza folga orçamentária",
    "limiar_estouro": "Execução acima do orçado que caracteriza risco de estouro",
    "margem_realinhamento": "Margem de segurança ao realinhar uma linha ao ritmo real",
    "meta_reducao": "Meta de redução do cenário Meta e do comparativo de corte linear",
    "teto_reducao_linha": "Redução máxima acumulada numa linha (exceto duplicidades)",
    "limite_horas_extras": "Teto saudável de horas extras sobre a folha de salários",
    "economia_minima_pct_total": "Corte de materialidade: economia mínima para listar oportunidade",
    "peso_minimo_categoria": "Peso mínimo da categoria no total para receber alavanca",
    "sigma_pico": "Desvios-padrão acima da média para caracterizar pico mensal",
    "fator_dezembro": "Dezembro acima deste múltiplo da média caracteriza gasto de fim de ano",
    "similaridade_duplicidade": "Similaridade mínima de descrição para suspeita de duplicidade",
    "estimativa_valor_minimo": "Valor mínimo para avaliar estimativa sem memória de cálculo",
    "estimativa_multiplo": "Múltiplo 'redondo' que indica estimativa por arredondamento",
    "participacao_generica": "Peso a partir do qual rubricas genéricas exigem detalhamento",
}

PERCENTUAIS = {
    "ipca", "tolerancia_crescimento_pp", "limiar_subexecucao", "limiar_estouro",
    "margem_realinhamento", "meta_reducao", "teto_reducao_linha", "limite_horas_extras",
    "economia_minima_pct_total", "peso_minimo_categoria", "participacao_generica",
    "similaridade_duplicidade",
}
MONETARIOS = {"estimativa_valor_minimo", "estimativa_multiplo"}


def carregar_premissas(caminho: str | Path | None = None, **sobrescritas: Any) -> dict[str, Any]:
    p = copy.deepcopy(PREMISSAS_PADRAO)
    if caminho:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        for k, v in dados.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k].update(v)
            else:
                p[k] = v
    for k, v in sobrescritas.items():
        if v is not None:
            p[k] = v
    return p
