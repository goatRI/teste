"""Leitura de orçamentos: XLSX/XLSM, CSV/TXT, PDF (tabelas), JSON e ODS/XLS (se houver leitor).

Etapas:
1. carregar a "grade" bruta de cada aba (sem supor onde está o cabeçalho);
2. escolher a aba e a linha de cabeçalho pela pontuação dos rótulos reconhecidos;
3. mapear cada coluna para um campo (código, descrição, orçado, realizado, meses...)
   usando o rótulo E o conteúdo da coluna;
4. transformar as linhas em ``Linha`` — ou pivotar, se o arquivo for de lançamentos (formato longo).

Nada é estimado aqui: o que não está no arquivo fica vazio e vira aviso.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .modelo import Linha
from .util import MESES_EN, MESES_PT, ano_em, normalizar, para_numero, texto, vazio

MESES_COMPLETOS = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                   "setembro", "outubro", "novembro", "dezembro"]
CAMPOS_NUMERICOS = {"orcado", "realizado", "projetado", "ano_anterior", "total", "ano",
                    "quantidade", "preco_unitario", "mes"}
CAMPOS_TEXTO = {"codigo", "descricao", "conta", "centro_custo", "fornecedor", "contrato", "unidade",
                "categoria_origem", "natureza", "observacao", "cenario", "competencia"}

ROTULO_CAMPO = {
    "codigo": "Código da conta", "descricao": "Descrição", "centro_custo": "Centro de custo",
    "fornecedor": "Fornecedor", "contrato": "Contrato/pedido", "unidade": "Unidade",
    "categoria_origem": "Categoria/grupo do arquivo", "natureza": "Natureza (OPEX/CAPEX)",
    "observacao": "Observação", "quantidade": "Quantidade", "preco_unitario": "Preço unitário",
    "orcado": "Orçado", "realizado": "Realizado", "projetado": "Projetado/forecast",
    "ano_anterior": "Ano anterior", "mes": "Mês (orçado)", "mes_realizado": "Mês (realizado)",
    "mes_anterior": "Mês (ano anterior)", "cenario": "Cenário (orçado/realizado)",
    "competencia": "Competência", "ignorar": "Ignorada (coluna derivada)",
    "orcado_anterior": "Orçado de ano anterior",
}


# ------------------------------------------------------------------ estruturas


@dataclass
class Grade:
    nome: str
    valores: list[list[Any]]
    negrito: list[bool]
    recuo: list[int]
    formulas_sem_valor: int = 0

    @property
    def n_linhas(self) -> int:
        return len(self.valores)

    @property
    def n_colunas(self) -> int:
        return max((len(r) for r in self.valores), default=0)

    def celula(self, r: int, c: int) -> Any:
        linha = self.valores[r]
        return linha[c] if c < len(linha) else None


@dataclass
class Coluna:
    indice: int
    rotulo: str
    campo: str | None
    ano: int | None = None
    mes: int | None = None
    motivo: str = ""
    exemplo: str = ""


@dataclass
class Mapeamento:
    colunas: list[Coluna]
    campos: dict[str, int] = field(default_factory=dict)
    meses: dict[int, int] = field(default_factory=dict)
    meses_realizado: dict[int, int] = field(default_factory=dict)
    meses_anterior: dict[int, int] = field(default_factory=dict)
    ano_referencia: int | None = None
    orcado_calculado: bool = False
    realizado_calculado: bool = False
    formato: str = "largo"  # largo | longo


@dataclass
class Leitura:
    arquivo: str
    formato_arquivo: str
    aba: str
    linha_cabecalho: int  # 1-based
    mapeamento: Mapeamento
    linhas: list[Linha]
    cabecalhos_grupo: list[dict] = field(default_factory=list)
    abas_avaliadas: list[dict] = field(default_factory=list)
    titulo_detectado: str = ""
    avisos: list[str] = field(default_factory=list)
    linhas_vazias: list[int] = field(default_factory=list)  # nº de linha (1-based) em branco
    meses_com_realizado: list[int] = field(default_factory=list)


# ------------------------------------------------------------------ carregar grades


def _col_letra(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _grades_xlsx(caminho: Path) -> list[Grade]:
    import openpyxl

    wb = openpyxl.load_workbook(caminho, data_only=True)
    try:
        wb_f = openpyxl.load_workbook(caminho, data_only=False)
    except Exception:  # pragma: no cover - arquivos estranhos
        wb_f = None
    grades = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        max_r, max_c = ws.max_row or 0, ws.max_column or 0
        valores, negrito, recuo = [], [], []
        sem_valor = 0
        wsf = wb_f[ws.title] if wb_f else None
        for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_r, min_col=1, max_col=max_c), start=1):
            vals = []
            b = False
            ind = 0
            achou_texto = False
            for c_idx, cell in enumerate(row, start=1):
                v = cell.value
                if v is None and wsf is not None:
                    vf = wsf.cell(row=r_idx, column=c_idx).value
                    if isinstance(vf, str) and vf.startswith("="):
                        sem_valor += 1
                vals.append(v)
                if not achou_texto and isinstance(v, str) and v.strip():
                    achou_texto = True
                    try:
                        b = bool(cell.font and cell.font.bold)
                        ind = int(cell.alignment.indent or 0) if cell.alignment else 0
                    except Exception:  # pragma: no cover
                        pass
                    ind += len(v) - len(v.lstrip(" "))
            valores.append(vals)
            negrito.append(b)
            recuo.append(ind)
        grades.append(Grade(ws.title, valores, negrito, recuo, sem_valor))
    return grades


def _grades_pandas_excel(caminho: Path, engine: str | None) -> list[Grade]:
    import pandas as pd

    abas = pd.read_excel(caminho, sheet_name=None, header=None, engine=engine)
    grades = []
    for nome, df in abas.items():
        valores = [[None if vazio(v) else v for v in linha] for linha in df.itertuples(index=False)]
        grades.append(Grade(str(nome), valores, [False] * len(valores), [0] * len(valores)))
    return grades


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", errors="replace")


def _detectar_separador(texto_: str) -> str:
    amostra = [ln for ln in texto_.splitlines()[:40] if ln.strip()]
    melhor, melhor_pts = ";", -1.0
    for sep in [";", "\t", ",", "|"]:
        contagens = [ln.count(sep) for ln in amostra]
        if not contagens or max(contagens) == 0:
            continue
        moda = max(set(contagens), key=contagens.count)
        consist = contagens.count(moda) / len(contagens)
        pts = consist * 10 + min(moda, 30) * 0.1
        if sep == "," and ";" in texto_:
            pts -= 1  # pt-BR: vírgula costuma ser decimal
        if pts > melhor_pts:
            melhor, melhor_pts = sep, pts
    return melhor


def _grades_csv(caminho: Path) -> list[Grade]:
    txt = _decodificar(caminho.read_bytes())
    sep = _detectar_separador(txt)
    leitor = csv.reader(io.StringIO(txt), delimiter=sep)
    valores = [[c if c.strip() else None for c in linha] for linha in leitor]
    recuo = [0] * len(valores)
    for i, linha in enumerate(valores):
        for c in linha:
            if isinstance(c, str) and c.strip():
                recuo[i] = len(c) - len(c.lstrip(" "))
                break
    return [Grade(caminho.stem, valores, [False] * len(valores), recuo)]


def _grades_pdf(caminho: Path) -> list[Grade]:
    import pdfplumber

    valores: list[list[Any]] = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            tabelas = pagina.extract_tables() or []
            if tabelas:
                for t in tabelas:
                    valores.extend([[c if c not in ("", None) else None for c in linha] for linha in t])
            else:
                for ln in (pagina.extract_text() or "").splitlines():
                    partes = [p for p in re.split(r"\s{2,}", ln.strip()) if p]
                    if partes:
                        valores.append(partes)
    return [Grade("PDF", valores, [False] * len(valores), [0] * len(valores))]


def _grades_json(caminho: Path) -> list[Grade]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(dados, dict):
        dados = dados.get("linhas") or dados.get("itens") or dados.get("dados") or []
    if not dados or not isinstance(dados, list):
        return []
    chaves: list[str] = []
    for d in dados:
        for k in d:
            if k not in chaves:
                chaves.append(k)
    valores = [list(chaves)] + [[d.get(k) for k in chaves] for d in dados]
    return [Grade(caminho.stem, valores, [False] * len(valores), [0] * len(valores))]


LEITORES_EXTRAS: list[tuple[str, Callable[[Path], bool], Callable[[Path], list[Grade]]]] = []


def registrar_leitor(nome: str, pode_ler: Callable[[Path], bool], ler: Callable[[Path], Any]) -> None:
    """Usado por skills do tipo ``leitor``. ``ler`` pode devolver Grade(s) ou DataFrame."""

    def _adaptar(p: Path) -> list[Grade]:
        r = ler(p)
        if r is None:
            return []
        if isinstance(r, Grade):
            return [r]
        if isinstance(r, list) and r and isinstance(r[0], Grade):
            return r
        try:  # DataFrame
            import pandas as pd

            if isinstance(r, pd.DataFrame):
                vals = [list(map(str, r.columns))] + [list(x) for x in r.itertuples(index=False)]
                return [Grade(nome, vals, [False] * len(vals), [0] * len(vals))]
        except ImportError:  # pragma: no cover
            pass
        raise TypeError(f"Leitor {nome} devolveu tipo não suportado: {type(r)}")

    LEITORES_EXTRAS.append((nome, pode_ler, _adaptar))


def carregar_grades(caminho: str | Path) -> tuple[list[Grade], str]:
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    for nome, pode, ler in LEITORES_EXTRAS:
        try:
            if pode(p):
                return ler(p), f"skill:{nome}"
        except Exception as e:  # skill quebrada não derruba o bot
            raise RuntimeError(f"Leitor da skill '{nome}' falhou: {e}") from e
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _grades_xlsx(p), "xlsx"
    if ext in (".csv", ".txt", ".tsv"):
        return _grades_csv(p), "csv"
    if ext == ".pdf":
        return _grades_pdf(p), "pdf"
    if ext == ".json":
        return _grades_json(p), "json"
    if ext == ".xls":
        try:
            return _grades_pandas_excel(p, None), "xls"
        except ImportError as e:
            raise RuntimeError("Arquivo .xls exige o pacote 'xlrd' (pip install xlrd) "
                               "ou salve como .xlsx.") from e
    if ext == ".ods":
        try:
            return _grades_pandas_excel(p, "odf"), "ods"
        except ImportError as e:
            raise RuntimeError("Arquivo .ods exige o pacote 'odfpy' (pip install odfpy) "
                               "ou salve como .xlsx.") from e
    raise RuntimeError(f"Formato não suportado: {ext}. Crie uma skill do tipo 'leitor' para ele "
                       "(python -m bot_orcamento nova-skill <nome> --tipo leitor).")


# ------------------------------------------------------------------ rótulos de coluna

_TOK_MES = {m: i + 1 for i, m in enumerate(MESES_PT)}
_TOK_MES.update({m: i + 1 for i, m in enumerate(MESES_EN)})
_TOK_MES.update({m: i + 1 for i, m in enumerate(MESES_COMPLETOS)})
_TOK_MES.update({"sept": 9, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
                 "january": 1, "february": 2, "october": 10, "november": 11, "december": 12,
                 "september": 9})
_QUAL_REAL = {"real", "realizado", "realizada", "actual", "act", "executado", "exec", "incorrido"}
_QUAL_ANT = {"ly", "anterior"}


def _mes_de(valor: Any) -> tuple[int, int | None, str] | None:
    """(mês, ano, qualificador) se o rótulo for de mês."""
    if isinstance(valor, (_dt.datetime, _dt.date)):
        return valor.month, valor.year, "orcado"
    n = normalizar(valor)
    if not n:
        return None
    toks = n.split()
    qual = "orcado"
    if any(t in _QUAL_REAL for t in toks):
        qual = "realizado"
    elif any(t in _QUAL_ANT for t in toks):
        qual = "anterior"
    m = re.fullmatch(r"(0?[1-9]|1[0-2])[ ]((?:19|20)?\d{2})", n)
    if m:
        ano = int(m.group(2))
        return int(m.group(1)), (ano + 2000 if ano < 100 else ano), qual
    m = re.fullmatch(r"((?:19|20)\d{2})[ ](0?[1-9]|1[0-2])", n)
    if m:
        return int(m.group(2)), int(m.group(1)), qual
    meses = [t for t in toks if t in _TOK_MES]
    if len(meses) != 1:
        return None
    outros = [t for t in toks if t not in _TOK_MES]
    permitidos = _QUAL_REAL | _QUAL_ANT | {"orc", "orcado", "orcamento", "budget", "bgt", "plan",
                                           "plano", "previsto", "de", "valor", "r", "mes", "prev"}
    ano = None
    for t in outros:
        if re.fullmatch(r"\d{2}|\d{4}", t):
            ano = int(t) + (2000 if len(t) == 2 else 0)
        elif t not in permitidos:
            return None
    return _TOK_MES[meses[0]], ano, qual


_REGRAS: list[tuple[str, str]] = [
    ("ignorar", r"%|\b(var|variacao|desvio|diferenca|dif|delta|saldo|atingimento|ating|share|av|ah|"
                r"acumulado|acum|ytd|media|indice|ranking)\b"),
    ("preco_unitario", r"\b(preco|valor|custo|vl|vlr)\s*(unit|unitario|unitaria|un|medio)\b|\bunitari|"
                       r"\bpu\b|\bp unit\b|^preco$"),
    ("quantidade", r"\b(qtd|qtde|qt|quant|quantidade|qty|volume)\b"),
    ("unidade", r"^(un|und|unid|unidade|um|u m|uom|unit|unid medida|unidade de medida)$"),
    ("centro_custo", r"centro de custo|centro custo|\bcc\b|\bc custo\b|\bccusto\b|departamento|\bdepto\b|"
                     r"\bsetor\b|\barea\b|gerencia|diretoria|unidade de negocio|\bfrente\b|\bfilial\b|"
                     r"\bunidade\b|\bprojeto\b|\bfazenda\b|\bplanta\b"),
    ("fornecedor", r"fornecedor|prestador|contratad|\bempresa\b|vendor|supplier|parceiro|favorecido|credor"),
    ("contrato", r"\bcontrato\b|\bpedido\b|ordem de compra|\boc\b"),
    ("cenario", r"^(cenario|tipo|versao|tipo de valor|tipo valor|natureza do valor|orc real|real orc|"
                r"base|tipo de lancamento)$"),
    ("competencia", r"^(competencia|mes|periodo|data|mes ano|ano mes|mes referencia|referencia|"
                    r"data lancamento|data de lancamento|dt|mes competencia)$|\bcompetencia\b"),
    ("natureza", r"\bnatureza\b|capex opex|opex capex|tipo de gasto|tipo de investimento"),
    ("categoria_origem", r"\bcategoria\b|\bgrupo\b|\bclasse\b|\bfamilia\b|\bpacote\b|\bmacro\b|"
                         r"tipo de custo|tipo de despesa|subgrupo|agrupamento|\bsubcategoria\b"),
    ("descricao", r"descri|historico|\bnome\b|rubrica|^despesa$|^despesas$|titulo|especificac|discrimina|"
                  r"^item$|detalhamento|^desc$|^conta descricao$|^servico$|^material$"),
    ("conta", r"\bconta\b|plano de contas"),
    ("codigo", r"\bcodigo\b|\bcod\b|\bwbs\b|\beap\b|^n$|^no$|^n o$|^num$|^numero$|^id$|^ref$|"
               r"classificacao contabil|^cc conta$"),
    ("observacao", r"\bobs\b|observ|comentario|justificativa|premissa|memoria de calculo|^nota$|^notas$"),
    ("projetado", r"projetad|forecast|\bfcst\b|previsao de fechamento|tendencia|\bfc\b|"
                  r"estimativa de fechamento|\bproj\b"),
    ("ano_anterior", r"ano anterior|\bly\b|last year|\ba 1\b|exercicio anterior"),
    ("realizado", r"realizad|\breal\b|actual|\bact\b|executad|incorrid|^gasto$|^gastos$|consumid|"
                  r"\bexecucao\b"),
    ("orcado", r"orcad|orcament|budget|\bbgt\b|\bbud\b|planejad|\bplano\b|previst|\borc\b|\bplan\b"),
    ("total", r"\btotal\b|\bvalor\b|montante|\banual\b|\bano\b|\bvlr\b|\bvl\b|\bsoma\b|\bcusto\b|\bdespesa\b"),
    ("ano", r"^(19|20)\d{2}$"),
]
_REGRAS_RX = [(c, re.compile(rx)) for c, rx in _REGRAS]


def classificar_rotulo(valor: Any) -> Coluna:
    """Classifica um rótulo de cabeçalho isolado (sem olhar o conteúdo)."""
    rot = texto(valor) or ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and 1900 <= float(valor) <= 2100:
        return Coluna(-1, rot, "ano", ano=int(valor), motivo="cabeçalho é um ano")
    mes = _mes_de(valor)
    if mes:
        m, ano, qual = mes
        campo = {"orcado": "mes", "realizado": "mes_realizado", "anterior": "mes_anterior"}[qual]
        return Coluna(-1, rot, campo, ano=ano, mes=m, motivo=f"rótulo de mês ({qual})")
    n = normalizar(valor)
    if not n:
        return Coluna(-1, rot, None)
    for campo, rx in _REGRAS_RX:
        if rx.search(n):
            return Coluna(-1, rot, campo, ano=ano_em(rot), motivo=f"rótulo casa com '{campo}'")
    return Coluna(-1, rot, None, ano=ano_em(rot))


# ------------------------------------------------------------------ cabeçalho


def _pontos_cabecalho(linha: list[Any]) -> int:
    pts = 0
    preenchidas = 0
    numericas = 0
    for v in linha:
        if vazio(v):
            continue
        preenchidas += 1
        col = classificar_rotulo(v)
        if col.campo in (None,):
            if para_numero(v) is not None:
                numericas += 1
            continue
        if col.campo == "ano":
            pts += 1
        elif col.campo in ("total", "ignorar"):
            pts += 1
        else:
            pts += 2
        if isinstance(v, (int, float)) and col.campo != "ano":
            numericas += 1
    if preenchidas < 2:
        return 0
    return pts - numericas


def _eh_linha_rotulos(linha: list[Any]) -> bool:
    preenchidas = [v for v in linha if not vazio(v)]
    if len(preenchidas) < 2:
        return False
    for v in preenchidas:
        if isinstance(v, (int, float)) and not (1900 <= float(v) <= 2100):
            return False
        if isinstance(v, str) and para_numero(v) is not None and not re.fullmatch(r"(19|20)\d{2}", v.strip()):
            return False
    return True


def _rotulos_combinados(g: Grade, r: int) -> list[Any]:
    """Rótulos da linha r, prefixados pela linha de cima quando ela é um supercabeçalho."""
    atual = list(g.valores[r]) + [None] * (g.n_colunas - len(g.valores[r]))
    if r == 0 or not _eh_linha_rotulos(g.valores[r - 1]):
        return atual
    acima = list(g.valores[r - 1]) + [None] * (g.n_colunas - len(g.valores[r - 1]))
    if sum(1 for v in acima if not vazio(v)) < 2:
        return atual
    # só é supercabeçalho se ao menos um rótulo de cima for reconhecível
    if not any(classificar_rotulo(v).campo for v in acima if not vazio(v)):
        return atual
    # rótulo mesclado sobre os meses: propaga para a direita enquanto a coluna for de mês
    cheio: list[Any] = []
    fill = None
    for c, v in enumerate(acima):
        if not vazio(v):
            fill = v
            cheio.append(v)
        elif fill is not None and _mes_de(atual[c]) is not None:
            cheio.append(fill)
        else:
            fill = None
            cheio.append(None)
    out = []
    for c, v in enumerate(atual):
        sup = cheio[c]
        if vazio(v):
            out.append(sup)
        elif vazio(sup) or normalizar(sup) in normalizar(v):
            out.append(v)
        elif isinstance(v, (_dt.datetime, _dt.date)):
            out.append(f"{texto(sup)} {MESES_PT[v.month - 1]} {v.year}")
        else:
            out.append(f"{texto(sup)} {texto(v)}")
    return out


def encontrar_cabecalho(g: Grade, limite: int = 40) -> tuple[int, int]:
    """Retorna (índice 0-based da linha de cabeçalho, pontuação)."""
    melhor, pts_m = -1, 0
    for r in range(min(limite, g.n_linhas)):
        pts = _pontos_cabecalho(g.valores[r])
        if pts > pts_m:
            melhor, pts_m = r, pts
    if melhor < 0:
        for r in range(min(limite, g.n_linhas)):
            if sum(1 for v in g.valores[r] if not vazio(v)) >= 3:
                return r, 0
        return 0, 0
    # cabeçalho em duas linhas: meses logo abaixo do supercabeçalho
    if melhor + 1 < g.n_linhas:
        abaixo = g.valores[melhor + 1]
        meses_abaixo = sum(1 for v in abaixo if _mes_de(v))
        meses_aqui = sum(1 for v in g.valores[melhor] if _mes_de(v))
        if meses_abaixo >= 3 and meses_aqui < 3:
            return melhor + 1, pts_m
    return melhor, pts_m


# ------------------------------------------------------------------ mapeamento


_RX_CODIGO = re.compile(r"^[A-Za-z]{0,4}[ ._-]?\d[\d.\-/ ]{0,24}$")


def _amostra(g: Grade, c: int, inicio: int, n: int = 300) -> list[Any]:
    out = []
    for r in range(inicio, min(g.n_linhas, inicio + n)):
        v = g.celula(r, c)
        if not vazio(v):
            out.append(v)
    return out


def _razao_numerica(vals: list[Any]) -> float:
    if not vals:
        return 0.0
    return sum(1 for v in vals if para_numero(v) is not None and not isinstance(v, (_dt.date, _dt.datetime))) / len(vals)


def _razao_codigo(vals: list[Any]) -> float:
    if not vals:
        return 0.0
    ok = 0
    for v in vals:
        s = texto(v) or ""
        if _RX_CODIGO.match(s) and len(s) <= 28:
            ok += 1
    return ok / len(vals)


def _letra_para_indice(s: str) -> int | None:
    if not re.fullmatch(r"[A-Za-z]{1,3}", s):
        return None
    i = 0
    for ch in s.upper():
        i = i * 26 + (ord(ch) - 64)
    return i - 1


def mapear_colunas(g: Grade, r_cab: int, mapa_manual: dict[str, str] | None = None) -> tuple[Mapeamento, list[str]]:
    avisos: list[str] = []
    rotulos = _rotulos_combinados(g, r_cab)
    cols: list[Coluna] = []
    for c in range(g.n_colunas):
        v = rotulos[c] if c < len(rotulos) else None
        col = classificar_rotulo(v)
        col.indice = c
        if not col.rotulo:
            col.rotulo = f"(coluna {_col_letra(c)})"
        amostra = _amostra(g, c, r_cab + 1)
        col.exemplo = (texto(amostra[0]) or "")[:40] if amostra else ""
        if not amostra and col.campo is not None:
            col.motivo += " · coluna vazia"
            col.campo = None
        cols.append(col)

    inicio = r_cab + 1
    # ---- resolução pelo conteúdo
    tem_cod = any(c.campo == "codigo" for c in cols)
    for col in cols:
        am = _amostra(g, col.indice, inicio)
        if col.campo == "conta":
            if _razao_codigo(am) >= 0.7:
                col.campo, col.motivo = "codigo", "rótulo 'conta' com conteúdo em formato de código"
            else:
                col.campo, col.motivo = "descricao", "rótulo 'conta' com conteúdo textual"
        elif col.campo == "descricao" and not tem_cod and _razao_codigo(am) >= 0.85:
            col.campo, col.motivo = "codigo", "conteúdo em formato de código"
            tem_cod = True
        elif col.campo == "natureza":
            vals = {normalizar(v) for v in am}
            alvo = {"capex", "opex", "investimento", "custeio", "despesa", "custo", "investimentos"}
            if vals and len(vals & alvo) / len(vals) >= 0.6:
                col.motivo = "valores CAPEX/OPEX"
            else:
                col.campo, col.motivo = "categoria_origem", "rótulo 'natureza' com categorias de gasto"
        if col.campo in CAMPOS_NUMERICOS or col.campo in ("mes_realizado", "mes_anterior"):
            if _razao_numerica(am) < 0.5:
                if col.campo in ("total",):
                    col.campo = None
                    col.motivo = "rótulo genérico sem números"
                elif col.campo == "ano" and _razao_codigo(am) < 0.5:
                    col.campo = None
                else:
                    avisos.append(f"Coluna '{col.rotulo}' parece '{col.campo}' mas tem poucos números; ignorada.")
                    col.motivo += " · descartada: conteúdo não numérico"
                    col.campo = None
        if col.campo is None and am:
            rn = _razao_numerica(am)
            if rn < 0.3:
                col.motivo = col.motivo or "texto não reconhecido"
    # mapeamento manual
    if mapa_manual:
        for campo, ref in mapa_manual.items():
            idx = _letra_para_indice(ref)
            if idx is None:
                alvo = normalizar(ref)
                idx = next((c.indice for c in cols if normalizar(c.rotulo) == alvo), None)
            if idx is None or idx >= len(cols):
                avisos.append(f"Mapa manual: coluna '{ref}' não encontrada para '{campo}'.")
                continue
            for c in cols:
                if c.campo == campo and campo not in ("mes", "mes_realizado"):
                    c.campo, c.motivo = None, "substituída pelo mapa manual"
            cols[idx].campo, cols[idx].motivo = campo, "definido no mapa manual (--mapa)"

    m = Mapeamento(colunas=cols)
    _resolver_campos(m, g, inicio, avisos)
    return m, avisos


def _resolver_campos(m: Mapeamento, g: Grade, inicio: int, avisos: list[str]) -> None:
    cols = m.colunas
    por_campo: dict[str, list[Coluna]] = {}
    for c in cols:
        if c.campo:
            por_campo.setdefault(c.campo, []).append(c)

    def unico(campo: str) -> None:
        lst = por_campo.get(campo, [])
        if lst:
            m.campos[campo] = lst[0].indice
            for extra in lst[1:]:
                extra.motivo += f" · duplicada (usada a coluna '{lst[0].rotulo}')"
                extra.campo = None

    for campo in ("codigo", "descricao", "centro_custo", "fornecedor", "contrato", "unidade",
                  "categoria_origem", "natureza", "observacao", "quantidade", "preco_unitario",
                  "cenario", "competencia"):
        unico(campo)

    anos = [c.ano for c in cols if c.ano and c.campo in ("orcado", "realizado", "total", "ano", "mes",
                                                          "mes_realizado", "projetado")]

    def mais_recente(lst: list[Coluna]) -> Coluna:
        com_ano = [c for c in lst if c.ano]
        if com_ano:
            return max(com_ano, key=lambda c: (c.ano, c.indice))
        return lst[-1]

    # orçado
    orc = por_campo.get("orcado", [])
    if orc:
        esc = mais_recente(orc)
        m.campos["orcado"] = esc.indice
        for c in orc:
            if c is not esc:
                c.campo, c.motivo = "orcado_anterior", c.motivo + " · orçado de período anterior"
    ano_ref = cols[m.campos["orcado"]].ano if "orcado" in m.campos else None
    if ano_ref is None and anos:
        ano_ref = max(anos)

    # total genérico / coluna de ano
    if "orcado" not in m.campos:
        cand = por_campo.get("total", []) + por_campo.get("ano", [])
        cand = [c for c in cand if c.campo in ("total", "ano")]
        if cand:
            esc = mais_recente(cand)
            if ano_ref and esc.ano and esc.ano < ano_ref and any(c.ano == ano_ref for c in cand):
                esc = next(c for c in cand if c.ano == ano_ref)
            m.campos["orcado"] = esc.indice
            esc.campo, esc.motivo = "orcado", esc.motivo + " · usado como valor orçado"
            ano_ref = esc.ano or ano_ref
            for c in cand:
                if c is esc:
                    continue
                if c.ano and ano_ref and c.ano == ano_ref - 1 and "ano_anterior" not in m.campos:
                    c.campo, c.motivo = "ano_anterior", c.motivo + " · ano anterior ao orçado"
                    m.campos["ano_anterior"] = c.indice
                else:
                    c.motivo += " · não utilizada"
                    c.campo = None
    m.ano_referencia = ano_ref

    # realizado × ano anterior
    reais = por_campo.get("realizado", [])
    if reais:
        atuais = [c for c in reais if not (c.ano and ano_ref and c.ano < ano_ref)]
        antigos = [c for c in reais if c.ano and ano_ref and c.ano < ano_ref]
        if atuais:
            esc = mais_recente(atuais)
            m.campos["realizado"] = esc.indice
            for c in atuais:
                if c is not esc:
                    c.campo, c.motivo = None, c.motivo + " · realizado duplicado"
        for c in antigos:
            c.campo = "ano_anterior"
            c.motivo += f" · realizado de {c.ano} (anterior ao orçado {ano_ref})"
            por_campo.setdefault("ano_anterior", []).insert(0, c)
    proj = por_campo.get("projetado", [])
    if proj:
        m.campos["projetado"] = mais_recente(proj).indice
    ant = [c for c in cols if c.campo == "ano_anterior"]
    if ant and "ano_anterior" not in m.campos:
        m.campos["ano_anterior"] = mais_recente(ant).indice
    if "ano_anterior" not in m.campos:
        oa = [c for c in cols if c.campo == "orcado_anterior"]
        if oa:
            m.campos["ano_anterior"] = mais_recente(oa).indice
            mais_recente(oa).motivo += " · usado como referência do ano anterior"

    # meses
    for c in cols:
        if c.campo in ("mes", "mes_realizado", "mes_anterior") and c.mes:
            alvo = {"mes": m.meses, "mes_realizado": m.meses_realizado, "mes_anterior": m.meses_anterior}[c.campo]
            if c.campo != "mes_anterior" and c.ano and ano_ref and c.ano < ano_ref:
                m.meses_anterior.setdefault(c.mes, c.indice)
                c.motivo += f" · mês de {c.ano} (anterior)"
                continue
            if c.mes in alvo:
                c.motivo += " · mês repetido, ignorado"
                c.campo = None
                continue
            alvo[c.mes] = c.indice
    if "orcado" not in m.campos and m.meses:
        m.orcado_calculado = True
    if "realizado" not in m.campos and m.meses_realizado:
        m.realizado_calculado = True
    if "orcado" not in m.campos and not m.meses and not ("competencia" in m.campos):
        # último recurso: coluna numérica com maior soma
        melhor, soma_m = None, 0.0
        for c in cols:
            if c.campo is not None:
                continue
            vals = [para_numero(v) for v in _amostra(g, c.indice, inicio, 5000)]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 3 and sum(abs(v) for v in vals) > soma_m and _razao_codigo(_amostra(g, c.indice, inicio)) < 0.9:
                melhor, soma_m = c, sum(abs(v) for v in vals)
        if melhor is not None:
            melhor.campo, melhor.motivo = "orcado", "sem rótulo reconhecido: coluna numérica de maior soma"
            m.campos["orcado"] = melhor.indice
            avisos.append(f"Não achei a coluna de orçado pelo nome; usei '{melhor.rotulo}' (maior soma). "
                          "Confirme ou informe --mapa orcado=<coluna>.")
    if "descricao" not in m.campos:
        melhor, comp = None, 0.0
        for c in cols:
            if c.campo is not None:
                continue
            am = _amostra(g, c.indice, inicio)
            if am and _razao_numerica(am) < 0.3:
                media = sum(len(str(v)) for v in am) / len(am)
                if media > comp:
                    melhor, comp = c, media
        if melhor is not None:
            melhor.campo, melhor.motivo = "descricao", "coluna de texto mais longa"
            m.campos["descricao"] = melhor.indice
        elif "codigo" in m.campos:
            avisos.append("Sem coluna de descrição: usando o código como descrição.")
    if "competencia" in m.campos and not m.meses and any(
        k in m.campos for k in ("orcado", "realizado")
    ):
        m.formato = "longo"


# ------------------------------------------------------------------ montar linhas


def _valor(g: Grade, r: int, c: int | None) -> float | None:
    if c is None:
        return None
    return para_numero(g.celula(r, c))


def _texto(g: Grade, r: int, c: int | None) -> str | None:
    if c is None:
        return None
    return texto(g.celula(r, c))


def _profundidade_codigo(cod: str | None) -> int:
    if not cod:
        return 0
    partes = [p for p in re.split(r"[.\-/ ]", cod) if p]
    return len(partes)


def _linhas_largo(g: Grade, r_cab: int, m: Mapeamento, avisos: list[str]) -> tuple[list[Linha], list[dict], list[int]]:
    cp = m.campos
    colunas_valor = [cp.get(k) for k in ("orcado", "realizado", "projetado", "ano_anterior")]
    colunas_valor += list(m.meses.values()) + list(m.meses_realizado.values()) + list(m.meses_anterior.values())
    colunas_valor = [c for c in colunas_valor if c is not None]
    linhas: list[Linha] = []
    cabecalhos: list[dict] = []
    vazias: list[int] = []
    grupo_atual: str | None = None
    for r in range(r_cab + 1, g.n_linhas):
        row = g.valores[r]
        if all(vazio(v) for v in row):
            vazias.append(r + 1)
            continue
        desc = _texto(g, r, cp.get("descricao"))
        cod = _texto(g, r, cp.get("codigo"))
        tem_valor = any(_valor(g, r, c) is not None for c in colunas_valor)
        if not tem_valor:
            rot = desc or cod or next((texto(v) for v in row if not vazio(v)), None)
            if rot:
                cabecalhos.append({"linha_origem": r + 1, "codigo": cod, "texto": rot,
                                   "negrito": g.negrito[r], "nivel": _profundidade_codigo(cod)})
                grupo_atual = desc or rot
            continue
        if not desc:
            desc = cod or f"Linha {r + 1}"
        meses = {k: v for k, c in m.meses.items() if (v := _valor(g, r, c)) is not None}
        meses_r = {k: v for k, c in m.meses_realizado.items() if (v := _valor(g, r, c)) is not None}
        meses_a = {k: v for k, c in m.meses_anterior.items() if (v := _valor(g, r, c)) is not None}
        orc = _valor(g, r, cp.get("orcado"))
        if orc is None and m.orcado_calculado:
            orc = sum(meses.values()) if meses else None
        real = _valor(g, r, cp.get("realizado"))
        if real is None and m.realizado_calculado and meses_r:
            real = sum(meses_r.values())
        ant = _valor(g, r, cp.get("ano_anterior"))
        if ant is None and meses_a:
            ant = sum(meses_a.values())
        nat = _texto(g, r, cp.get("natureza"))
        linhas.append(Linha(
            id=len(linhas) + 1, linha_origem=r + 1, aba=g.nome, descricao=desc, codigo=cod,
            centro_custo=_texto(g, r, cp.get("centro_custo")),
            fornecedor=_texto(g, r, cp.get("fornecedor")), contrato=_texto(g, r, cp.get("contrato")),
            unidade=_texto(g, r, cp.get("unidade")),
            categoria_origem=_texto(g, r, cp.get("categoria_origem")), grupo=grupo_atual,
            natureza=(nat.upper() if nat and normalizar(nat) in ("capex", "opex") else nat),
            quantidade=_valor(g, r, cp.get("quantidade")),
            preco_unitario=_valor(g, r, cp.get("preco_unitario")),
            orcado=orc if orc is not None else 0.0, realizado=real,
            projetado=_valor(g, r, cp.get("projetado")), ano_anterior=ant,
            meses=meses, meses_realizado=meses_r, observacao=_texto(g, r, cp.get("observacao")),
            negrito=g.negrito[r], nivel=g.recuo[r],
        ))
        if orc is None:
            avisos.append(f"Linha {r + 1} ('{desc[:40]}') sem valor orçado: considerada R$ 0,00.")
    return linhas, cabecalhos, vazias


def _mes_competencia(v: Any) -> tuple[int, int | None] | None:
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.month, v.year
    n = para_numero(v)
    if n is not None and 1 <= n <= 12 and float(n).is_integer():
        return int(n), None
    s = texto(v) or ""
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?", s)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m:
        return int(m.group(2)), int(m.group(3))
    r = _mes_de(s)
    if r:
        return r[0], r[1]
    return None


def _linhas_longo(g: Grade, r_cab: int, m: Mapeamento, avisos: list[str]) -> tuple[list[Linha], list[dict], list[int]]:
    cp = m.campos
    c_val_orc = cp.get("orcado")
    c_val_real = cp.get("realizado")
    if c_val_orc is not None and c_val_real is None and "cenario" in cp:
        c_valor = c_val_orc
    else:
        c_valor = None
    chaves: dict[tuple, dict] = {}
    anos_vistos: set[int] = set()
    sem_mes = 0
    for r in range(r_cab + 1, g.n_linhas):
        row = g.valores[r]
        if all(vazio(v) for v in row):
            continue
        comp = _mes_competencia(g.celula(r, cp["competencia"]))
        if comp is None:
            sem_mes += 1
            continue
        mes, ano = comp
        if ano:
            anos_vistos.add(ano)
        chave = tuple(_texto(g, r, cp.get(k)) for k in ("codigo", "descricao", "centro_custo",
                                                          "fornecedor", "categoria_origem"))
        d = chaves.setdefault(chave, {"linha_origem": r + 1, "orc": {}, "real": {}, "orc_ant": {},
                                      "real_ant": {}, "natureza": _texto(g, r, cp.get("natureza"))})
        if c_valor is not None:
            cen = normalizar(g.celula(r, cp["cenario"]))
            v = _valor(g, r, c_valor)
            if v is None:
                continue
            tipo = "real" if any(t in cen for t in ("real", "actual", "exec", "incorr")) else "orc"
            d[(tipo, ano)] = d.get((tipo, ano), {})
            d[(tipo, ano)][mes] = d[(tipo, ano)].get(mes, 0.0) + v
        else:
            for tipo, c in (("orc", c_val_orc), ("real", c_val_real)):
                v = _valor(g, r, c)
                if v is not None:
                    d[(tipo, ano)] = d.get((tipo, ano), {})
                    d[(tipo, ano)][mes] = d[(tipo, ano)].get(mes, 0.0) + v
    if sem_mes:
        avisos.append(f"{sem_mes} lançamento(s) sem competência reconhecível foram ignorados.")
    ano_ref = max(anos_vistos) if anos_vistos else None
    if ano_ref:
        # o ano de referência é o mais recente com orçado
        anos_orc = {k[1] for d in chaves.values() for k in d if isinstance(k, tuple) and k[0] == "orc" and k[1]}
        if anos_orc:
            ano_ref = max(anos_orc)
    m.ano_referencia = ano_ref
    linhas: list[Linha] = []
    for chave, d in chaves.items():
        cod, desc, cc, forn, cat = chave
        orc_m: dict[int, float] = {}
        real_m: dict[int, float] = {}
        ant = 0.0
        tem_ant = False
        for k, meses in d.items():
            if not isinstance(k, tuple):
                continue
            tipo, ano = k
            atual = (ano is None) or (ano_ref is None) or ano == ano_ref
            if atual:
                alvo = orc_m if tipo == "orc" else real_m
                for mm, v in meses.items():
                    alvo[mm] = alvo.get(mm, 0.0) + v
            elif ano is not None and ano_ref is not None and ano < ano_ref and tipo == "real":
                ant += sum(meses.values())
                tem_ant = True
        linhas.append(Linha(
            id=len(linhas) + 1, linha_origem=d["linha_origem"], aba=g.nome,
            descricao=desc or cod or f"Conta {len(linhas) + 1}", codigo=cod, centro_custo=cc,
            fornecedor=forn, categoria_origem=cat, natureza=d["natureza"],
            orcado=sum(orc_m.values()), realizado=(sum(real_m.values()) if real_m else None),
            ano_anterior=(ant if tem_ant else None), meses=dict(sorted(orc_m.items())),
            meses_realizado=dict(sorted(real_m.items())),
        ))
    m.orcado_calculado = True
    m.realizado_calculado = any(lin.meses_realizado for lin in linhas)
    avisos.append(f"Arquivo em formato de lançamentos (longo): {len(chaves)} contas consolidadas "
                  "por código/descrição/centro de custo/fornecedor.")
    return linhas, [], []


# ------------------------------------------------------------------ orquestração


def _exemplos_de_item(grades: list[Grade], escolhidas: list[str], m: Mapeamento | None, linhas: list[Linha]) -> None:
    """Exemplo de cada coluna tirado da primeira linha de item (não de título de grupo), em pt-BR."""
    if m is None or not linhas or m.formato == "longo":
        return
    g = next((x for x in grades if x.nome == escolhidas[0]), None)
    if g is None:
        return
    itens = [lin for lin in linhas if lin.aba == g.nome][:200]
    if not itens:
        return
    from .util import num

    for c in m.colunas:
        v = next((g.celula(lin.linha_origem - 1, c.indice) for lin in itens
                  if not vazio(g.celula(lin.linha_origem - 1, c.indice))), None)
        if vazio(v):
            continue
        n = para_numero(v) if not isinstance(v, str) or re.search(r"\d", v) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and n is not None:
            c.exemplo = num(n, 0 if float(n).is_integer() else 2)
        else:
            c.exemplo = (texto(v) or "")[:40]


def _titulo(g: Grade, r_cab: int) -> str:
    for r in range(0, r_cab):
        for v in g.valores[r]:
            t = texto(v)
            if t and len(t) >= 8 and para_numero(t) is None:
                return t
    return ""


def _avaliar_grade(g: Grade) -> dict:
    r, pts = encontrar_cabecalho(g)
    numericos = 0
    for row in g.valores[r + 1: r + 400]:
        numericos += sum(1 for v in row if isinstance(v, (int, float)) or (isinstance(v, str) and para_numero(v) is not None))
    return {"aba": g.nome, "linha_cabecalho": r + 1, "pontuacao": pts + min(numericos / 10.0, 25.0),
            "linhas": g.n_linhas, "colunas": g.n_colunas}


def ler_orcamento(caminho: str | Path, aba: str | None = None,
                  mapa: dict[str, str] | None = None) -> Leitura:
    """Lê e entende um orçamento. ``aba``: nome, lista "A,B" ou "todas"."""
    grades, fmt = carregar_grades(caminho)
    grades = [g for g in grades if g.n_linhas > 0]
    if not grades:
        raise RuntimeError("Arquivo sem dados legíveis.")
    avaliacoes = sorted((_avaliar_grade(g) for g in grades), key=lambda a: -a["pontuacao"])
    if aba is None:
        escolhidas = [avaliacoes[0]["aba"]]
    elif normalizar(aba) == "todas":
        escolhidas = [a["aba"] for a in avaliacoes if a["pontuacao"] >= 5]
    else:
        pedidas = [a.strip() for a in aba.split(",")]
        nomes = {normalizar(g.nome): g.nome for g in grades}
        escolhidas = []
        for p in pedidas:
            if normalizar(p) not in nomes:
                raise RuntimeError(f"Aba '{p}' não encontrada. Abas: {', '.join(g.nome for g in grades)}")
            escolhidas.append(nomes[normalizar(p)])
    for a in avaliacoes:
        a["usada"] = a["aba"] in escolhidas

    todas_linhas: list[Linha] = []
    todos_cab: list[dict] = []
    vazias: list[int] = []
    avisos: list[str] = []
    mapa_ref: Mapeamento | None = None
    r_ref = 0
    titulo = ""
    for nome in escolhidas:
        g = next(x for x in grades if x.nome == nome)
        r_cab, _ = encontrar_cabecalho(g)
        m, av = mapear_colunas(g, r_cab, mapa)
        avisos.extend(f"[{nome}] {a}" if len(escolhidas) > 1 else a for a in av)
        if "orcado" not in m.campos and not m.orcado_calculado and m.formato != "longo":
            avisos.append(f"Aba '{nome}': nenhuma coluna de valor orçado identificada; aba ignorada.")
            continue
        if g.formulas_sem_valor:
            avisos.append(f"Aba '{nome}': {g.formulas_sem_valor} fórmula(s) sem valor calculado salvo — "
                          "abra o arquivo no Excel e salve novamente para que os totais sejam lidos.")
        if m.formato == "longo":
            linhas, cab, vz = _linhas_longo(g, r_cab, m, av_l := [])
            avisos.extend(av_l)
        else:
            linhas, cab, vz = _linhas_largo(g, r_cab, m, av_l := [])
            avisos.extend(av_l[:15])
            if len(av_l) > 15:
                avisos.append(f"... e mais {len(av_l) - 15} aviso(s) de linhas sem valor orçado.")
        if len(escolhidas) > 1 and "centro_custo" not in m.campos:
            for lin in linhas:
                lin.centro_custo = nome
        base_id = len(todas_linhas)
        for lin in linhas:
            lin.id += base_id
        todas_linhas.extend(linhas)
        todos_cab.extend(cab)
        vazias.extend(vz)
        if mapa_ref is None:
            mapa_ref, r_ref = m, r_cab
            titulo = _titulo(g, r_cab)
    if mapa_ref is None:
        raise RuntimeError(
            "Não consegui identificar a estrutura do orçamento (nenhuma coluna de valor). "
            "Use 'python -m bot_orcamento estrutura <arquivo>' para ver o que foi lido e "
            "informe o mapeamento com --mapa campo=coluna (ex.: --mapa orcado=F --mapa descricao=B)."
        )
    meses_real = sorted({k for lin in todas_linhas for k in lin.meses_realizado})
    _exemplos_de_item(grades, escolhidas, mapa_ref, todas_linhas)
    return Leitura(
        arquivo=str(caminho), formato_arquivo=fmt, aba=", ".join(escolhidas), linha_cabecalho=r_ref + 1,
        mapeamento=mapa_ref, linhas=todas_linhas, cabecalhos_grupo=todos_cab,
        abas_avaliadas=avaliacoes, titulo_detectado=titulo, avisos=avisos, linhas_vazias=vazias,
        meses_com_realizado=meses_real,
    )
