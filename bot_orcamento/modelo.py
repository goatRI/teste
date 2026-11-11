"""Modelo de dados do bot: linha de orçamento, oportunidade, cenário, verificação."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

NIVEIS = ("conservador", "base", "agressivo")


@dataclass
class Linha:
    """Uma linha do orçamento depois de lida e entendida."""

    id: int
    linha_origem: int  # nº da linha na planilha/arquivo (1 = primeira linha)
    descricao: str
    aba: str = ""
    codigo: str | None = None
    centro_custo: str | None = None
    fornecedor: str | None = None
    contrato: str | None = None
    unidade: str | None = None
    categoria_origem: str | None = None
    grupo: str | None = None
    natureza: str | None = None  # OPEX / CAPEX quando informado
    quantidade: float | None = None
    preco_unitario: float | None = None
    orcado: float = 0.0
    realizado: float | None = None
    projetado: float | None = None
    ano_anterior: float | None = None
    meses: dict[int, float] = field(default_factory=dict)
    meses_realizado: dict[int, float] = field(default_factory=dict)
    observacao: str | None = None
    negrito: bool = False
    # preenchidos pela leitura da estrutura / classificação
    tipo: str = "item"  # item | subtotal | total
    motivo_tipo: str = ""
    nivel: int = 0
    categoria: str = "nao_classificado"
    categoria_conf: str = "baixa"
    categoria_termo: str = ""
    comportamento: str = "fixo"
    protegida: bool = False
    discricionaria: bool = False

    @property
    def rotulo(self) -> str:
        return f"{self.codigo} · {self.descricao}" if self.codigo else self.descricao

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["meses"] = {str(k): v for k, v in self.meses.items()}
        d["meses_realizado"] = {str(k): v for k, v in self.meses_realizado.items()}
        return d


@dataclass
class LinhaOportunidade:
    """Quanto uma oportunidade reduz de uma linha específica, por nível."""

    linha_id: int
    base: float  # valor da linha sobre o qual a taxa incide
    taxas: dict[str, float]  # conservador/base/agressivo → fração 0..1
    nota: str = ""

    def economia(self, nivel: str) -> float:
        return self.base * self.taxas.get(nivel, 0.0)


@dataclass
class Oportunidade:
    detector: str
    titulo: str
    racional: str
    acao: str
    linhas: list[LinhaOportunidade]
    categoria: str | None = None
    confianca: str = "media"  # alta | media | baixa
    esforco: str = "medio"  # baixo | medio | alto
    horizonte: str = "medio"  # curto (0-3m) | medio (3-6m) | longo (6-12m)
    evidencias: list[str] = field(default_factory=list)
    indicador: str = ""
    permite_total: bool = False  # pode zerar a linha (ex.: duplicidade)
    id: str = ""
    prioridade: float = 0.0

    def economia(self, nivel: str) -> float:
        return sum(lo.economia(nivel) for lo in self.linhas)

    @property
    def base_afetada(self) -> float:
        return sum(lo.base for lo in self.linhas)

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["economia"] = {n: self.economia(n) for n in NIVEIS}
        d["base_afetada"] = self.base_afetada
        return d


@dataclass
class Alerta:
    """Risco ou ponto de atenção (não é economia)."""

    titulo: str
    detalhe: str
    severidade: str = "media"  # alta | media | baixa
    origem: str = ""
    linhas: list[int] = field(default_factory=list)
    valor: float | None = None


@dataclass
class Cenario:
    id: str
    nome: str
    descricao: str
    selecao: dict[str, str]  # id oportunidade → nível
    valores: dict[int, float]  # linha_id → valor adaptado
    total_original: float = 0.0
    total_adaptado: float = 0.0
    nota: str = ""
    recomendado: bool = False
    meta_atingida: bool | None = None

    @property
    def economia(self) -> float:
        return self.total_original - self.total_adaptado

    @property
    def economia_pct(self) -> float:
        return self.economia / self.total_original if self.total_original else 0.0


@dataclass
class Verificacao:
    """Item do checklist de revisão do relatório."""

    id: str
    nome: str
    status: str  # ok | alerta | falha | pulado
    detalhe: str = ""
    grupo: str = "Conteúdo"
