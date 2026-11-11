"""Detectores de oportunidade: nativos + os trazidos por skills.

Contrato de um detector (módulo Python):

    ID = "meu_detector"                 # único, sem espaços
    NOME = "Nome legível"
    DESCRICAO = "O que procura e por que gera economia"
    REQUER = ["fornecedor"]             # chaves de ctx.estrutura.tem (opcional)

    def detectar(ctx) -> list[Oportunidade]:
        ...

O detector pode registrar riscos com ``ctx.alertar(Alerta(...))``. Um detector que levanta
exceção não derruba o bot: vira "erro" na tabela de detectores do relatório.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Callable

from ..estrutura import Estrutura
from ..leitura import Leitura, registrar_leitor
from ..modelo import NIVEIS, Alerta, Linha, LinhaOportunidade, Oportunidade
from ..taxonomia import Taxonomia

NATIVOS = [
    "categoria", "horas_extras", "execucao", "crescimento", "duplicidade", "preco_unitario",
    "fornecedores", "sazonalidade", "estimativas", "genericos",
]


@dataclass
class InfoDetector:
    id: str
    nome: str
    descricao: str
    requer: list[str]
    funcao: Callable[["Contexto"], list[Oportunidade]]
    origem: str = "nativo"


@dataclass
class Contexto:
    itens: list[Linha]
    estrutura: Estrutura
    leitura: Leitura
    premissas: dict
    taxonomia: Taxonomia
    alertas: list[Alerta] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.estrutura.total_itens

    def por_categoria(self) -> dict[str, list[Linha]]:
        d: dict[str, list[Linha]] = {}
        for lin in self.itens:
            d.setdefault(lin.categoria, []).append(lin)
        return d

    def alertar(self, alerta: Alerta) -> None:
        self.alertas.append(alerta)

    def execucao(self, lin: Linha) -> float | None:
        """Realizado ÷ orçado do mesmo período (None se a linha não tem realizado)."""
        if lin.realizado is None or lin.orcado <= 0:
            return None
        meses_real = self.leitura.meses_com_realizado
        if lin.meses_realizado and lin.meses:
            orc_p = sum(lin.meses.get(m, 0.0) for m in lin.meses_realizado)
            real_p = sum(lin.meses_realizado.values())
        elif meses_real and lin.meses:
            orc_p, real_p = sum(lin.meses.get(m, 0.0) for m in meses_real), lin.realizado
        else:
            orc_p, real_p = lin.orcado, lin.realizado
        return real_p / orc_p if orc_p > 0 else None

    def em_estouro(self, lin: Linha) -> bool:
        e = self.execucao(lin)
        return e is not None and e > 1 + self.premissas["limiar_estouro"]

    @staticmethod
    def linhas_oportunidade(linhas: list[Linha], taxas: tuple[float, float, float] | dict[int, tuple],
                            notas: dict[int, str] | None = None) -> list[LinhaOportunidade]:
        """Monta a lista por linha. ``taxas`` única para todas ou por id de linha."""
        out = []
        for lin in linhas:
            t = taxas[lin.id] if isinstance(taxas, dict) else taxas
            t = tuple(max(0.0, min(1.0, float(x))) for x in t)
            out.append(LinhaOportunidade(lin.id, lin.orcado, dict(zip(NIVEIS, t)), (notas or {}).get(lin.id, "")))
        return out


def _info_de_modulo(mod: ModuleType, origem: str) -> InfoDetector:
    for attr in ("ID", "NOME", "detectar"):
        if not hasattr(mod, attr):
            raise AttributeError(f"detector sem atributo obrigatório '{attr}'")
    return InfoDetector(mod.ID, mod.NOME, getattr(mod, "DESCRICAO", ""), list(getattr(mod, "REQUER", [])),
                        mod.detectar, origem)


def _importar_arquivo(caminho: Path, nome_mod: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(nome_mod, caminho)
    if spec is None or spec.loader is None:
        raise ImportError(f"não foi possível importar {caminho}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome_mod] = mod
    spec.loader.exec_module(mod)
    return mod


def pastas_padrao(extras: list[str | Path] | None = None) -> list[Path]:
    """Pastas de skills: .claude/skills do repositório do bot + as passadas explicitamente.

    O diretório atual NÃO entra: skills são código Python executado pelo bot, e rodar o bot
    de dentro de uma pasta compartilhada não pode executar código de terceiros sem querer.
    """
    raiz = Path(__file__).resolve().parents[2]
    pastas = [Path(p) for p in (extras or [])] + [raiz / ".claude" / "skills"]
    vistas, out = set(), []
    for p in pastas:
        r = p.resolve()
        if r not in vistas:
            vistas.add(r)
            out.append(r)
    return out


@dataclass
class Plugins:
    detectores: list[InfoDetector]
    categorias_extras: list[dict]
    cenarios_extras: list[ModuleType]
    skills: list[dict]  # {nome, tipo, pasta, status, erro}


def carregar_plugins(pastas_skills: list[str | Path] | None = None) -> Plugins:
    detectores = [_info_de_modulo(importlib.import_module(f"{__name__}.{n}"), "nativo") for n in NATIVOS]
    categorias: list[dict] = []
    cenarios: list[ModuleType] = []
    skills: list[dict] = []
    for pasta in pastas_skills or []:
        pasta = Path(pasta)
        if not pasta.is_dir():
            continue
        for sk in sorted(p for p in pasta.iterdir() if p.is_dir()):
            arquivos = {
                "detector": sk / "detector.py", "leitor": sk / "leitor.py",
                "taxonomia": sk / "categorias.json", "cenario": sk / "cenario.py",
            }
            presentes = [t for t, a in arquivos.items() if a.exists()]
            if not presentes:
                continue
            for tipo in presentes:
                reg = {"nome": sk.name, "tipo": tipo, "pasta": str(sk), "status": "carregada", "erro": ""}
                try:
                    nome_mod = f"skill_{sk.name.replace('-', '_')}_{tipo}"
                    if tipo == "detector":
                        info = _info_de_modulo(_importar_arquivo(arquivos[tipo], nome_mod), f"skill:{sk.name}")
                        if any(d.id == info.id for d in detectores):
                            raise ValueError(f"ID de detector repetido: {info.id}")
                        detectores.append(info)
                    elif tipo == "leitor":
                        mod = _importar_arquivo(arquivos[tipo], nome_mod)
                        registrar_leitor(sk.name, mod.pode_ler, mod.ler)
                    elif tipo == "taxonomia":
                        dados = json.loads(arquivos[tipo].read_text(encoding="utf-8"))
                        categorias.extend(dados if isinstance(dados, list) else dados.get("categorias", []))
                    elif tipo == "cenario":
                        mod = _importar_arquivo(arquivos[tipo], nome_mod)
                        for attr in ("ID", "NOME", "selecionar"):
                            if not hasattr(mod, attr):
                                raise AttributeError(f"cenário sem atributo '{attr}'")
                        cenarios.append(mod)
                except Exception as e:  # skill quebrada vira aviso
                    reg["status"] = "erro"
                    reg["erro"] = f"{type(e).__name__}: {e}"
                skills.append(reg)
    return Plugins(detectores, categorias, cenarios, skills)


def executar_detectores(ctx: Contexto, detectores: list[InfoDetector]) -> tuple[list[Oportunidade], list[dict]]:
    oportunidades: list[Oportunidade] = []
    registro: list[dict] = []
    for d in detectores:
        faltando = [r for r in d.requer if not ctx.estrutura.tem.get(r)]
        if faltando:
            registro.append({"id": d.id, "nome": d.nome, "origem": d.origem, "descricao": d.descricao,
                             "status": "pulado", "n": 0,
                             "motivo": "o arquivo não traz: " + ", ".join(faltando)})
            continue
        try:
            ops = d.funcao(ctx) or []
            for o in ops:
                o.detector = o.detector or d.id
            oportunidades.extend(ops)
            registro.append({"id": d.id, "nome": d.nome, "origem": d.origem, "descricao": d.descricao,
                             "status": "executado", "n": len(ops), "motivo": ""})
        except Exception as e:
            registro.append({"id": d.id, "nome": d.nome, "origem": d.origem, "descricao": d.descricao,
                             "status": "erro", "n": 0,
                             "motivo": f"{type(e).__name__}: {e}",
                             "traceback": traceback.format_exc(limit=3)})
    return oportunidades, registro
