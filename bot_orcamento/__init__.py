"""Bot de Orçamento — lê, entende e propõe adaptações de redução de custos em orçamentos.

Uso rápido:
    python -m bot_orcamento analisar caminho/do/orcamento.xlsx

O motor é determinístico (os números saem sempre do mesmo cálculo). A camada de IA
(opcional, ``--ia``) só escreve texto e classifica linhas ambíguas: ela nunca altera valores.
"""

__version__ = "1.0.0"
NOME_BOT = "Bot de Orçamento"
