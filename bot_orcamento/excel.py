"""Exportação Excel do orçamento adaptado (uma coluna por cenário) e das oportunidades."""

from __future__ import annotations

from pathlib import Path

from .analise import Analise
from .modelo import NIVEIS, Verificacao

FMT_R = '#,##0.00'
PERIGOSOS = ("=", "+", "-", "@", "\t", "\r")


def _texto_seguro(ws) -> None:
    """Texto que começa com = + - @ é gravado como texto, não como fórmula (injeção de fórmula)."""
    for c in ws[ws.max_row]:
        if isinstance(c.value, str) and c.value.startswith(PERIGOSOS):
            c.data_type = "s"
FMT_P = '0.0%'


def exportar_excel(a: Analise, destino: str | Path, verificacoes: list[Verificacao] | None = None,
                   rev: int | None = None) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    cab_fill = PatternFill("solid", fgColor="F0E9D8")
    negrito = Font(bold=True)

    def cabecalho(ws, colunas, larguras):
        ws.append(colunas)
        for i, c in enumerate(ws[ws.max_row], start=1):
            c.font = negrito
            c.fill = cab_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(i)].width = larguras[i - 1] if i - 1 < len(larguras) else 14
        ws.freeze_panes = ws.cell(row=ws.max_row + 1, column=1)

    # Resumo
    ws = wb.active
    ws.title = "Resumo"
    ws.append([f"{a.meta['titulo']} — análise orçamentária"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Fonte: {a.meta['arquivo']} · aba {a.meta['aba']} · data-base {a.meta['data_base']} · "
               f"Rev. {rev if rev is not None else '-'} · {a.meta['bot']} v{a.meta['versao_bot']}"])
    ws.append([a.resumo])
    ws.append([])
    cabecalho(ws, ["Cenário", "Descrição", "Orçado original", "Orçamento adaptado", "Redução", "% redução"],
              [34, 70, 18, 18, 18, 11])
    for c in a.cenarios:
        ws.append([c.nome, c.descricao + (f" {c.nota}" if c.nota else ""), c.total_original, c.total_adaptado,
                   c.economia, c.economia_pct])
        r = ws.max_row
        for col in (3, 4, 5):
            ws.cell(r, col).number_format = FMT_R
        ws.cell(r, 6).number_format = FMT_P
    ws.freeze_panes = None

    # Orçamento adaptado por linha
    ws = wb.create_sheet("Orçamento adaptado")
    cols = ["Linha", "Código", "Descrição", "Categoria", "Centro de custo", "Fornecedor", "Orçado"]
    cols += [c.nome for c in a.cenarios]
    cabecalho(ws, cols, [7, 12, 46, 28, 20, 22, 16] + [16] * len(a.cenarios))
    for x in a.estrutura.itens:
        ws.append([x.linha_origem, x.codigo, x.descricao, a.taxonomia.nome(x.categoria), x.centro_custo,
                   x.fornecedor, x.orcado] + [c.valores.get(x.id, x.orcado) for c in a.cenarios])
        _texto_seguro(ws)
        for col in range(7, 8 + len(a.cenarios)):
            ws.cell(ws.max_row, col).number_format = FMT_R
    n = ws.max_row
    ws.append(["", "", "TOTAL", "", "", ""] + [f"=SUM({get_column_letter(col)}2:{get_column_letter(col)}{n})"
                                               for col in range(7, 8 + len(a.cenarios))])
    for c in ws[ws.max_row]:
        c.font = negrito
        c.number_format = FMT_R
    ws.auto_filter.ref = f"A1:{get_column_letter(7 + len(a.cenarios))}{n}"

    # Oportunidades
    ws = wb.create_sheet("Oportunidades")
    cabecalho(ws, ["ID", "Oportunidade", "Categoria", "Confiança", "Esforço", "Prazo", "Base afetada",
                   "Conservador", "Base", "Agressivo", "Ação recomendada", "Indicador", "Evidências"],
              [8, 50, 26, 11, 10, 10, 16, 16, 16, 16, 70, 40, 70])
    for o in a.oportunidades:
        ws.append([o.id, o.titulo, a.taxonomia.nome(o.categoria) if o.categoria else "Várias", o.confianca,
                   o.esforco, o.horizonte, o.base_afetada] + [o.economia(nv) for nv in NIVEIS]
                  + [o.acao, o.indicador, "\n".join(o.evidencias)])
        _texto_seguro(ws)
        for col in range(7, 11):
            ws.cell(ws.max_row, col).number_format = FMT_R
        for col in (11, 13):
            ws.cell(ws.max_row, col).alignment = Alignment(wrap_text=True, vertical="top")

    # Premissas
    ws = wb.create_sheet("Premissas")
    cabecalho(ws, ["Premissa", "Valor"], [40, 30])
    for k, v in a.premissas.items():
        ws.append([k, str(v) if isinstance(v, (list, dict)) else v])
    ws.append([])
    ws.append(["Categoria", "Conservador", "Base", "Agressivo", "Protegida"])
    for c in ws[ws.max_row]:
        c.font = negrito
    presentes = {d["id"] for d in a.por_categoria}
    for c in a.taxonomia.categorias:
        if c.id in presentes:
            ws.append([c.nome, *c.faixa, "sim" if c.protegida else "não"])
            for col in (2, 3, 4):
                ws.cell(ws.max_row, col).number_format = FMT_P

    if verificacoes:
        ws = wb.create_sheet("Revisão")
        cabecalho(ws, ["ID", "Grupo", "Verificação", "Resultado", "Detalhe"], [6, 18, 50, 10, 90])
        for v in verificacoes:
            ws.append([v.id, v.grupo, v.nome, v.status, v.detalhe])
            _texto_seguro(ws)

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
