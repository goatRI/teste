"""Funções utilitárias: normalização de texto, leitura de números e formatação pt-BR."""

from __future__ import annotations

import datetime as _dt
import math
import re
import unicodedata
from typing import Any

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES_EN = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MESES_NOME = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def normalizar(texto: Any) -> str:
    """Minúsculas, sem acento, só letras/dígitos separados por espaço simples."""
    if texto is None:
        return ""
    if isinstance(texto, float) and math.isnan(texto):
        return ""
    s = str(texto)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9%]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def vazio(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    if isinstance(valor, str) and valor.strip() in ("", "-", "—", "–", "nan", "NaN", "None"):
        return True
    return False


_RE_SO_PONTO_MILHAR = re.compile(r"^-?\d{1,3}(\.\d{3})+$")
_RE_SO_VIRGULA_MILHAR = re.compile(r"^-?\d{1,3}(,\d{3}){2,}$")


def para_numero(valor: Any) -> float | None:
    """Converte células de planilha/CSV em float.

    Aceita: 1234.5 · "1.234,56" · "R$ 1.234,56" · "(1.234,56)" (negativo) · "1,234.56" ·
    "12%" (vira 0,12 apenas se ``%`` presente) · "-" / "" (None).
    """
    if vazio(valor):
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        f = float(valor)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(valor, (_dt.date, _dt.datetime)):
        return None
    s = str(valor).strip()
    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo = True
        s = s[1:-1]
    s = s.replace("R$", "").replace("r$", "").replace(" ", " ").strip()
    pct = s.endswith("%")
    s = s.rstrip("%").strip().replace(" ", "")
    if s.endswith("-"):
        negativo = True
        s = s[:-1]
    if s.startswith("-"):
        negativo = not negativo if s.count("-") == 1 else negativo
        s = s[1:]
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if _RE_SO_VIRGULA_MILHAR.match(s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        if _RE_SO_PONTO_MILHAR.match(s):
            s = s.replace(".", "")
    try:
        f = float(s)
    except ValueError:
        return None
    if pct:
        f = f / 100.0
    return -f if negativo else f


def texto(valor: Any) -> str | None:
    if vazio(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    if isinstance(valor, (_dt.datetime, _dt.date)):
        return valor.strftime("%d/%m/%Y")
    s = str(valor).replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s or None


# ---------------------------------------------------------------- formatação pt-BR

def _fmt(v: float, casas: int) -> str:
    s = f"{abs(v):,.{casas}f}"
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return ("-" if v < 0 and round(abs(v), casas) != 0 else "") + s


def brl(v: float | None, casas: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return "R$ " + _fmt(float(v), casas)


def brl_curto(v: float | None) -> str:
    """R$ 12,4 mi · R$ 850,0 mil · R$ 1,23 bi — para títulos e KPIs."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return "R$ " + _fmt(v / 1e9, 2) + " bi"
    if a >= 1e6:
        return "R$ " + _fmt(v / 1e6, 1) + " mi"
    if a >= 1e3:
        return "R$ " + _fmt(v / 1e3, 1) + " mil"
    return "R$ " + _fmt(v, 0)


def num(v: float | None, casas: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return _fmt(float(v), casas)


def pct(v: float | None, casas: int = 1, sinal: bool = False) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    s = _fmt(v * 100, casas) + "%"
    if sinal and v > 0 and round(v * 100, casas) != 0:
        s = "+" + s
    return s


def ler_brl(textual: str) -> float | None:
    """Inverso de ``brl``/``brl_curto`` — usado pelo revisor para conferir o HTML."""
    if textual is None:
        return None
    s = textual.strip().replace(" ", " ")
    mult = 1.0
    for suf, m in ((" bi", 1e9), (" mi", 1e6), (" mil", 1e3)):
        if s.endswith(suf):
            mult = m
            s = s[: -len(suf)]
            break
    s = s.replace("R$", "").strip()
    pct_ = s.endswith("%")
    s = s.rstrip("%").strip().lstrip("+")
    if not re.fullmatch(r"-?[\d.]*\d(,\d+)?", s):
        return None
    v = float(s.replace(".", "").replace(",", "."))
    if pct_:
        return v / 100.0
    return v * mult


def plural(n: int, singular: str, plural_: str) -> str:
    """plural(1, "linha", "linhas") → "1 linha"; plural(7, ...) → "7 linhas"."""
    return f"{n} {singular if n == 1 else plural_}"


def slug(texto_: str, maximo: int = 60) -> str:
    s = normalizar(texto_).replace("%", "")
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:maximo].strip("-") or "orcamento"


def ano_em(texto_: str) -> int | None:
    m = re.search(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", texto_ or "")
    return int(m.group(1)) if m else None


def agora_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = _dt.datetime.fromisoformat(iso)
        return d.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso
