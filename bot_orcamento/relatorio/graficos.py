"""Gráficos em SVG inline (sem dependência externa — o relatório abre sem internet).

Regras seguidas: uma escala por gráfico (nada de eixo duplo), marcas finas, grade em
traço fino e claro, rótulos seletivos, tooltip nativo (<title>) em cada marca e uma
tabela equivalente no relatório para quem não enxerga cor.
"""

from __future__ import annotations

import math
from html import escape

from ..util import MESES_PT, brl, brl_curto, pct

COR = {
    "ouro": "#B4842A", "ouro_esc": "#8A6320", "plano": "#C9BDA0", "plano_linha": "#A6906A",
    "grade": "#EAE2CF", "eixo": "#CFC2A3", "tinta": "#2B2620", "mudo": "#7A7062", "fundo": "#FFFFFF",
    "ok": "#3E8E5A",
}


def _escala_bonita(maximo: float, n: int = 4) -> list[float]:
    if maximo <= 0:
        return [0.0, 1.0]
    bruto = maximo / n
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        passo = m * mag
        if passo >= bruto:
            break
    topo = passo * math.ceil(maximo / passo)
    k = int(round(topo / passo))
    return [passo * i for i in range(k + 1)]


def curva_pareto(pontos: list[tuple[float, float]], n80: int, n: int) -> str:
    """Curva acumulada (x = % das linhas, y = % do valor). Um eixo só, 0–100%."""
    if not pontos:
        return ""
    W, H = 470, 250
    ml, mr, mt, mb = 44, 14, 14, 38
    pw, ph = W - ml - mr, H - mt - mb

    def X(fr: float) -> float:
        return ml + fr * pw

    def Y(fr: float) -> float:
        return mt + (1 - fr) * ph

    partes = [f'<svg viewBox="0 0 {W} {H}" class="viz" style="max-width:{W}px" role="img" '
              f'aria-label="Curva de Pareto: {n80} de {n} linhas somam 80% do orçamento">']
    for k in (0, 0.25, 0.5, 0.75, 1.0):
        partes.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(k):.1f}" y2="{Y(k):.1f}" stroke="{COR["grade"]}" stroke-width="1"/>')
        partes.append(f'<text x="{ml - 8}" y="{Y(k) + 4:.1f}" text-anchor="end" class="tick">{int(k * 100)}%</text>')
    for k in (0, 0.25, 0.5, 0.75, 1.0):
        partes.append(f'<text x="{X(k):.1f}" y="{H - mb + 18}" text-anchor="middle" class="tick">{int(k * 100)}%</text>')
    partes.append(f'<text x="{ml + pw / 2:.1f}" y="{H - 4}" text-anchor="middle" class="tick">% das linhas (da maior para a menor)</text>')
    d = f"M{X(0):.1f},{Y(0):.1f} " + " ".join(f"L{X(x):.1f},{Y(y):.1f}" for x, y in pontos)
    partes.append(f'<path d="{d}" fill="none" stroke="{COR["ouro"]}" stroke-width="2" stroke-linejoin="round"/>')
    fx = n80 / n if n else 0
    partes.append(f'<line x1="{X(fx):.1f}" x2="{X(fx):.1f}" y1="{Y(0):.1f}" y2="{Y(0.8):.1f}" stroke="{COR["plano_linha"]}" stroke-width="1"/>')
    partes.append(f'<line x1="{X(0):.1f}" x2="{X(fx):.1f}" y1="{Y(0.8):.1f}" y2="{Y(0.8):.1f}" stroke="{COR["plano_linha"]}" stroke-width="1"/>')
    partes.append(f'<g><title>{n80} de {n} linhas ({pct(fx)}) somam 80% do orçamento</title>'
                  f'<circle cx="{X(fx):.1f}" cy="{Y(0.8):.1f}" r="12" fill="transparent"/>'
                  f'<circle cx="{X(fx):.1f}" cy="{Y(0.8):.1f}" r="5" fill="{COR["ouro"]}" stroke="{COR["fundo"]}" stroke-width="2"/></g>')
    lx = X(fx) + 10
    anchor = "start"
    if fx > 0.6:
        lx, anchor = X(fx) - 10, "end"
    partes.append(f'<text x="{lx:.1f}" y="{Y(0.8) + 18:.1f}" text-anchor="{anchor}" class="lbl">'
                  f'{n80} linhas = 80% do valor</text>')
    partes.append("</svg>")
    return "".join(partes)


def colunas_mensais(orcado: dict[int, float], realizado: dict[int, float] | None = None) -> str:
    """Colunas mensais. Com realizado: orçado (cor de plano) ao lado do realizado (cor cheia)."""
    if not orcado:
        return ""
    W, H = 1060, 280
    ml, mr, mt, mb = 84, 12, 16, 34
    pw, ph = W - ml - mr, H - mt - mb
    meses = list(range(1, 13))
    maxv = max(list(orcado.values()) + list((realizado or {}).values()) + [0])
    ticks = _escala_bonita(maxv)
    topo = ticks[-1] or 1

    def Y(v: float) -> float:
        return mt + (1 - v / topo) * ph

    slot = pw / 12
    duas = bool(realizado)
    larg = min(30.0, slot * (0.34 if duas else 0.5))
    rot = "Orçado e realizado por mês" if duas else "Orçado por mês"
    partes = [f'<svg viewBox="0 0 {W} {H}" class="viz" style="max-width:{W}px" role="img" aria-label="{rot}">']
    for t in ticks:
        partes.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{COR["grade"]}" stroke-width="1"/>')
        partes.append(f'<text x="{ml - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="tick">{escape(brl_curto(t))}</text>')

    def coluna(x: float, v: float, cor: str, titulo: str) -> str:
        y = Y(max(v, 0))
        h = max(0.0, Y(0) - y)
        r = min(4.0, h / 2, larg / 2)
        # topo arredondado (4px), base reta no eixo
        d = (f"M{x:.1f},{Y(0):.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
             f"L{x + larg - r:.1f},{y:.1f} Q{x + larg:.1f},{y:.1f} {x + larg:.1f},{y + r:.1f} "
             f"L{x + larg:.1f},{Y(0):.1f} Z")
        return (f'<g><title>{escape(titulo)}</title><rect x="{x - 3:.1f}" y="{mt}" width="{larg + 6:.1f}" '
                f'height="{ph:.1f}" fill="transparent"/><path d="{d}" fill="{cor}"/></g>')

    for i, m in enumerate(meses):
        cx = ml + slot * i + slot / 2
        o = orcado.get(m, 0.0)
        if duas:
            partes.append(coluna(cx - larg - 1, o, COR["plano"], f"{MESES_PT[m - 1].capitalize()} · orçado {brl(o)}"))
            if m in realizado:
                rv = realizado[m]
                partes.append(coluna(cx + 1, rv, COR["ouro"], f"{MESES_PT[m - 1].capitalize()} · realizado {brl(rv)} "
                                                               f"({pct(rv / o) if o else '—'} do orçado)"))
        else:
            partes.append(coluna(cx - larg / 2, o, COR["ouro"], f"{MESES_PT[m - 1].capitalize()} · {brl(o)}"))
        partes.append(f'<text x="{cx:.1f}" y="{H - mb + 18}" text-anchor="middle" class="tick">'
                      f'{MESES_PT[m - 1].capitalize()}</text>')
    partes.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="{COR["eixo"]}" stroke-width="1"/>')
    partes.append("</svg>")
    return "".join(partes)
