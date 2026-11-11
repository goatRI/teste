"""Gera bases de DEMONSTRAÇÃO (dados fictícios) em três formatos diferentes.

Servem para testar o bot e mostrar o relatório. Cada arquivo traz "DADOS FICTÍCIOS"
no título ou no nome, para nunca ser confundido com orçamento real.

1. ``orcamento_opex_mina_2026.xlsx`` — planilha "de verdade": título antes do cabeçalho,
   grupos em negrito, subtotais por grupo, total geral, meses, qtd × preço unitário,
   coluna do realizado do ano anterior.
2. ``orcamento_administrativo_2026.csv`` — CSV pt-BR (; e vírgula decimal), código de conta,
   realizado 2025 × orçado 2026 e linha TOTAL.
3. ``lancamentos_orcado_realizado_2026.csv`` — formato longo (um lançamento por linha),
   orçado jan–dez e realizado jan–jun.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

PERFIL_PRODUCAO = [0.84, 0.86, 0.92, 1.03, 1.06, 1.07, 1.08, 1.08, 1.06, 1.04, 1.0, 0.96]


def _distribuir(total: float, perfil: list[float] | str, rng: random.Random, ruido: float = 0.03) -> list[float]:
    if perfil == "exato":
        base = round(total / 12, 2)
        vals = [base] * 11 + [round(total - base * 11, 2)]
        return vals
    if perfil == "plano":
        pesos = [1.0] * 12
    elif perfil == "producao":
        pesos = list(PERFIL_PRODUCAO)
    elif perfil == "dezembro":
        pesos = [0.6] * 11 + [6.0]
    elif perfil == "dezembro_forte":
        pesos = [0.8] * 11 + [4.2]
    elif perfil == "marco":
        pesos = [0.0, 0.0, 1.0] + [0.0] * 9
    elif perfil == "janeiro":
        pesos = [1.0] + [0.0] * 11
    elif perfil == "julho_pico":
        pesos = [1.0] * 6 + [3.4] + [1.0] * 5
    else:
        pesos = list(perfil)  # type: ignore[arg-type]
    pesos = [p * (1 + rng.uniform(-ruido, ruido)) if p else 0.0 for p in pesos]
    s = sum(pesos)
    vals = [round(total * p / s, 2) for p in pesos]
    vals[-1 if pesos[-1] else max(range(12), key=lambda i: pesos[i])] += round(total - sum(vals), 2)
    return vals


# (código, descrição, CC, fornecedor, un, qtd, pu, total 2026, real 2025, perfil)
GRUPOS_MINA = [
    ("1", "PESSOAL", [
        ("1.01", "Salários e ordenados", "Lavra", None, None, None, None, 18_240_000, 17_350_000, "plano"),
        ("1.02", "Encargos sociais (INSS/FGTS)", "Lavra", None, None, None, None, 6_930_000, 6_610_000, "plano"),
        ("1.03", "Horas extras", "Lavra", None, None, None, None, 2_918_000, 2_204_000, "plano"),
        ("1.04", "Benefícios (plano de saúde e vale-refeição)", "Administrativo", None, None, None, None, 3_215_000, 3_020_000, "plano"),
        ("1.05", "PLR — participação nos lucros", "Administrativo", None, None, None, None, 1_500_000, 1_420_000, "marco"),
        ("1.06", "Treinamento e capacitação", "SSMA", None, None, None, None, 452_000, 398_000, "plano"),
    ]),
    ("2", "SERVIÇOS DE TERCEIROS", [
        ("2.01", "Serviço de perfuração (contratada)", "Perfuração e Desmonte", "PerfuraSul Serviços", None, None, None, 9_612_000, 9_180_000, "producao"),
        ("2.02", "Transporte de minério (contratada)", "Transporte", "TransMinas Logística", None, None, None, 14_436_000, 13_720_000, "producao"),
        ("2.03", "Manutenção de equipamentos móveis", "Manutenção", "Oficina Alfa", None, None, None, 2_160_000, 2_050_000, "plano"),
        ("2.04", "Manutenção de equipamentos móveis — escavadeiras", "Manutenção", "Beta Mecânica", None, None, None, 1_840_000, 1_700_000, "plano"),
        ("2.05", "Manutenção de equipamentos móveis — caminhões", "Manutenção", "Gama Serviços Industriais", None, None, None, 1_395_000, 1_310_000, "plano"),
        ("2.06", "Manutenção de equipamentos fixos (usina)", "Beneficiamento", "Épsilon Manutenção", None, None, None, 2_108_000, 2_010_000, "plano"),
        ("2.07", "Manutenção corretiva emergencial", "Manutenção", "Delta Hidráulica", None, None, None, 1_214_000, 1_090_000, "julho_pico"),
        ("2.08", "Consultoria geotécnica", "Lavra", "GeoConsult Engenharia", None, None, None, 962_000, 910_000, "plano"),
        ("2.09", "Consultoria de gestão e processos", "Administrativo", "Vértice Consultores", None, None, None, 1_800_000, 1_100_000, "dezembro_forte"),
        ("2.10", "Assessoria jurídica", "Administrativo", "Moraes & Lima Advogados", None, None, None, 604_000, 588_000, "plano"),
        ("2.11", "Vigilância patrimonial", "Infraestrutura", "Guardião Segurança", None, None, None, 1_446_000, 1_380_000, "plano"),
        ("2.12", "Limpeza e conservação", "Infraestrutura", "LimpaBem Serviços", None, None, None, 721_000, 690_000, "plano"),
        ("2.13", "Transporte de pessoal (ônibus fretado)", "Administrativo", "ViaNorte Fretamento", None, None, None, 2_163_000, 2_070_000, "plano"),
        ("2.14", "Alimentação (refeitório)", "Administrativo", "Sabor Industrial", None, None, None, 2_884_000, 2_760_000, "plano"),
    ]),
    ("3", "MATERIAIS E INSUMOS", [
        ("3.01", "Óleo diesel", "Transporte", "Distribuidora Rota", "L", 3_500_000, 6.05, None, 19_980_000, "producao"),
        ("3.02", "Lubrificantes e graxas", "Manutenção", "Distribuidora Rota", None, None, None, 1_306_000, 1_240_000, "producao"),
        ("3.03", "Pneus OTR 40.00R57", "Transporte", "Pneumax", "un", 64, 82_000.0, None, 5_010_000, "producao"),
        ("3.04", "Pneus OTR 40.00R57 — reposição emergencial", "Transporte", "RodaForte", "un", 16, 94_500.0, None, 1_330_000, "producao"),
        ("3.05", "Explosivos (emulsão bombeada)", "Perfuração e Desmonte", "Detonar Explosivos", "t", 5_200, 1_480.0, None, 7_350_000, "producao"),
        ("3.06", "Acessórios de detonação", "Perfuração e Desmonte", "Detonar Explosivos", None, None, None, 1_153_000, 1_100_000, "producao"),
        ("3.07", "Bits de perfuração 6 3/4\"", "Perfuração e Desmonte", "PerfuraTec", "un", 900, 4_150.0, None, 3_560_000, "producao"),
        ("3.08", "Bits de perfuração 6 3/4\" — lote complementar", "Perfuração e Desmonte", "Brocas Sul", "un", 300, 5_020.0, None, 1_390_000, "producao"),
        ("3.09", "Peças de reposição — frota", "Manutenção", "Diversos", None, None, None, 4_917_000, 4_680_000, "plano"),
        ("3.10", "Peças de reposição — usina", "Beneficiamento", "Diversos", None, None, None, 2_311_000, 2_200_000, "plano"),
        ("3.11", "EPIs e uniformes", "SSMA", "ProteSeg", None, None, None, 641_000, 612_000, "plano"),
        ("3.12", "Material de escritório", "Administrativo", "Papelaria Central", None, None, None, 183_000, 171_000, "plano"),
    ]),
    ("4", "UTILIDADES E LOCAÇÕES", [
        ("4.01", "Energia elétrica", "Beneficiamento", "Concessionária de energia", None, None, None, 8_406_000, 8_020_000, "producao"),
        ("4.02", "Água e esgoto", "Infraestrutura", "Concessionária de água", None, None, None, 242_000, 231_000, "plano"),
        ("4.03", "Locação de equipamentos (escavadeira e caminhões)", "Lavra", "LocaMáquinas", None, None, None, 6_000_000, 4_600_000, "exato"),
        ("4.04", "Locação de veículos leves", "Administrativo", "FrotaLeve Locadora", None, None, None, 1_562_000, 1_480_000, "plano"),
        ("4.05", "Aluguel de escritório regional", "Administrativo", "Imobiliária Centro", None, None, None, 721_000, 700_000, "plano"),
    ]),
    ("5", "DESPESAS GERAIS E ADMINISTRATIVAS", [
        ("5.01", "Viagens e hospedagem", "Administrativo", None, None, None, None, 982_000, 700_000, "plano"),
        ("5.02", "Passagens aéreas", "Administrativo", None, None, None, None, 621_000, 560_000, "plano"),
        ("5.03", "Eventos e confraternizações", "Administrativo", None, None, None, None, 352_000, 221_000, "dezembro"),
        ("5.04", "Brindes e patrocínios", "Administrativo", None, None, None, None, 284_000, 260_000, "plano"),
        ("5.05", "Software e licenças corporativas", "Administrativo", None, None, None, None, 1_153_000, 800_000, "plano"),
        ("5.06", "Licenças de software (Paradigm/Opit)", "Lavra", None, None, None, None, 420_000, 401_000, "plano"),
        ("5.07", "Licenças de Software - Paradigm / Opit", "Lavra", None, None, None, None, 420_000, None, "plano"),
        ("5.08", "Telefonia e internet", "Administrativo", None, None, None, None, 383_000, 365_000, "plano"),
        ("5.09", "Monitoramento ambiental", "SSMA", "EcoAnálise", None, None, None, 763_000, 740_000, "plano"),
        ("5.10", "Taxas e licenças ambientais", "SSMA", None, None, None, None, 521_000, 500_000, "plano"),
        ("5.11", "Despesas diversas", "Administrativo", None, None, None, None, 1_200_000, 980_000, "exato"),
    ]),
    ("6", "TRIBUTOS, SEGUROS E CONTINGÊNCIA", [
        ("6.01", "CFEM e royalties", "Administrativo", None, None, None, None, 3_412_000, 3_250_000, "producao"),
        ("6.02", "Seguros operacionais", "Administrativo", None, None, None, None, 1_903_000, 1_820_000, "janeiro"),
        ("6.03", "Contingência operacional (5%)", "Administrativo", None, None, None, None, 4_500_000, None, "exato"),
    ]),
]


def gerar_xlsx_mina(destino: Path, seed: int = 26) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    rng = random.Random(seed)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "OPEX 2026"
    meses = ["Jan/26", "Fev/26", "Mar/26", "Abr/26", "Mai/26", "Jun/26", "Jul/26", "Ago/26", "Set/26",
             "Out/26", "Nov/26", "Dez/26"]
    cab = ["Código", "Descrição", "Centro de Custo", "Fornecedor", "Un.", "Qtd.", "Preço Unit."] + meses + \
          ["Total 2026", "Real 2025", "Observação"]
    ws.append(["UNIDADE MINA NORTE — ORÇAMENTO OPEX 2026 (DADOS FICTÍCIOS PARA DEMONSTRAÇÃO)"])
    ws.append(["Proposta orçamentária · valores em R$ · versão de trabalho"])
    ws.append([])
    ws.append(cab)
    negrito = Font(bold=True)
    for c in ws[4]:
        c.font = negrito
        c.fill = PatternFill("solid", fgColor="F0E9D8")
    ws["A1"].font = Font(bold=True, size=13)
    total_geral = [0.0] * 13
    total_ant = 0.0
    for cod_g, nome_g, itens in GRUPOS_MINA:
        ws.append([cod_g, nome_g])
        for c in ws[ws.max_row]:
            c.font = negrito
        soma = [0.0] * 13
        soma_ant = 0.0
        for cod, desc, cc, forn, un, qtd, pu, total, ant, perfil in itens:
            if total is None:
                total = round(qtd * pu, 2)
            vals = _distribuir(float(total), perfil, rng)
            tot = round(sum(vals), 2)
            obs = None
            if cod == "6.03":
                obs = "5% sobre o OPEX"
            linha = [cod, desc, cc, forn, un, qtd, pu] + vals + [tot, ant, obs]
            ws.append(linha)
            ws.cell(row=ws.max_row, column=2).alignment = Alignment(indent=1)
            for i in range(12):
                soma[i] += vals[i]
            soma[12] += tot
            soma_ant += ant or 0.0
        ws.append([None, f"Total {nome_g.title()}", None, None, None, None, None] +
                  [round(v, 2) for v in soma] + [round(soma_ant, 2), None])
        for c in ws[ws.max_row]:
            c.font = negrito
        for i in range(13):
            total_geral[i] += soma[i]
        total_ant += soma_ant
    ws.append([])
    ws.append([None, "TOTAL GERAL", None, None, None, None, None] + [round(v, 2) for v in total_geral] +
              [round(total_ant, 2), None])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["Fonte: planejamento financeiro (dados fictícios). Valores sem impostos recuperáveis."])
    for row in ws.iter_rows(min_row=5, min_col=6, max_col=20):
        for c in row:
            c.number_format = "#,##0.00"
    larguras = {"A": 8, "B": 46, "C": 22, "D": 26, "E": 6, "F": 12, "G": 12}
    for k, v in larguras.items():
        ws.column_dimensions[k].width = v
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


def _fmt_br(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:,.2f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


ADMIN = [
    ("4.1.01.001", "Salários - administrativo", "RH", 4_820_000, 5_010_000),
    ("4.1.01.002", "Encargos sociais", "RH", 1_830_000, 1_905_000),
    ("4.1.01.003", "Benefícios (plano de saúde)", "RH", 960_000, 1_050_000),
    ("4.1.01.004", "Horas extras", "RH", 95_000, 101_000),
    ("4.1.01.005", "Treinamentos corporativos", "RH", 210_000, 265_000),
    ("4.1.02.001", "Consultoria tributária", "Financeiro", 380_000, 552_000),
    ("4.1.02.002", "Auditoria externa", "Financeiro", 290_000, 304_000),
    ("4.1.02.003", "Assessoria jurídica trabalhista", "Jurídico", 410_000, 428_000),
    ("4.1.02.004", "Honorários advocatícios (contencioso)", "Jurídico", 620_000, 655_000),
    ("4.1.03.001", "Marketing institucional", "Marketing", 540_000, 610_000),
    ("4.1.03.002", "Eventos corporativos", "Marketing", 300_000, 450_000),
    ("4.1.03.003", "Patrocínios", "Marketing", 250_000, 280_000),
    ("4.1.04.001", "Viagens nacionais", "Diretoria", 330_000, 372_000),
    ("4.1.04.002", "Viagens internacionais", "Diretoria", 210_000, 336_000),
    ("4.1.04.003", "Hospedagem e diárias", "Diretoria", 145_000, 160_000),
    ("4.1.05.001", "Aluguel da sede", "Facilities", 1_440_000, 1_512_000),
    ("4.1.05.002", "Condomínio da sede", "Facilities", 360_000, 378_000),
    ("4.1.05.003", "IPTU", "Facilities", 120_000, 126_000),
    ("4.1.05.004", "Energia elétrica - sede", "Facilities", 210_000, 228_000),
    ("4.1.05.005", "Limpeza e conservação", "Facilities", 280_000, 296_000),
    ("4.1.05.006", "Vigilância e portaria", "Facilities", 330_000, 348_000),
    ("4.1.06.001", "Licenças ERP", "TI", 690_000, 742_000),
    ("4.1.06.002", "Licenças de colaboração (e-mail/escritório)", "TI", 260_000, 285_000),
    ("4.1.06.003", "Software de BI", "TI", None, 240_000),
    ("4.1.06.004", "Telefonia móvel", "TI", 150_000, 162_000),
    ("4.1.06.005", "Links de internet e dados", "TI", 180_000, 190_000),
    ("4.1.07.001", "Material de escritório", "Facilities", 65_000, 72_000),
    ("4.1.07.002", "Correios e malotes", "Facilities", 38_000, 41_000),
    ("4.1.07.003", "Cartório e registros", "Jurídico", 22_000, 25_000),
    ("4.1.08.001", "Seguros patrimoniais", "Financeiro", 175_000, 183_000),
    ("4.1.08.002", "Locação de veículos executivos", "Diretoria", 290_000, 318_000),
    ("4.1.08.003", "Despesas bancárias", "Financeiro", 88_000, 92_000),
    ("4.1.09.001", "Despesas diversas", "Diretoria", 180_000, 300_000),
]


def gerar_csv_administrativo(destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Conta", "Descrição", "Departamento", "Realizado 2025", "Orçado 2026"])
        t25 = t26 = 0.0
        for cod, desc, dep, r25, o26 in ADMIN:
            w.writerow([cod, desc, dep, _fmt_br(r25), _fmt_br(o26)])
            t25 += r25 or 0
            t26 += o26
        w.writerow(["", "TOTAL GERAL (dados fictícios)", "", _fmt_br(t25), _fmt_br(t26)])
    return destino


LANC = [
    # conta, descrição, CC, orçado anual, ritmo de execução jan-jun (realizado / orçado)
    ("5.1.01", "Treinamentos operacionais", "Operação", 360_000, 0.42),
    ("5.1.02", "Consultoria de processos", "Operação", 600_000, 0.50),
    ("5.1.03", "Manutenção predial", "Facilities", 420_000, 0.61),
    ("5.1.04", "Energia elétrica", "Operação", 2_400_000, 1.18),
    ("5.1.05", "Frete de produtos acabados", "Logística", 1_800_000, 1.15),
    ("5.1.06", "Materiais de consumo", "Operação", 950_000, 0.97),
    ("5.1.07", "Manutenção de máquinas", "Manutenção", 1_350_000, 1.03),
    ("5.1.08", "Peças de reposição", "Manutenção", 880_000, 0.95),
    ("5.1.09", "Serviços de limpeza industrial", "Facilities", 310_000, 1.00),
    ("5.1.10", "Viagens a clientes", "Comercial", 240_000, 0.55),
    ("5.1.11", "Feiras e eventos", "Comercial", 300_000, 0.20),
    ("5.1.12", "Software de gestão", "TI", 420_000, 1.00),
    ("5.1.13", "Telefonia e dados", "TI", 130_000, 0.98),
    ("5.1.14", "Locação de empilhadeiras", "Logística", 540_000, 1.00),
    ("5.1.15", "Seguro de carga", "Logística", 160_000, 1.02),
    ("5.1.16", "Alimentação de funcionários", "RH", 780_000, 1.01),
    ("5.1.17", "Transporte de funcionários", "RH", 650_000, 0.99),
    ("5.1.18", "Vigilância patrimonial", "Facilities", 390_000, 1.00),
    ("5.1.19", "Outras despesas operacionais", "Operação", 450_000, 0.35),
    ("5.1.20", "Salários da operação", "RH", 7_200_000, 1.01),
]


def gerar_csv_lancamentos(destino: Path, seed: int = 7) -> Path:
    rng = random.Random(seed)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Competência", "Conta", "Descrição", "Centro de Custo", "Cenário", "Valor"])
        for conta, desc, cc, anual, ritmo in LANC:
            mensal = _distribuir(float(anual), "plano", rng, 0.04)
            for m in range(12):
                w.writerow([f"2026-{m + 1:02d}", conta, desc, cc, "Orçado", _fmt_br(mensal[m])])
            for m in range(6):
                real = round(mensal[m] * ritmo * (1 + rng.uniform(-0.04, 0.04)), 2)
                w.writerow([f"2026-{m + 1:02d}", conta, desc, cc, "Realizado", _fmt_br(real)])
    return destino


def gerar_todos(pasta: str | Path = "exemplos") -> list[Path]:
    pasta = Path(pasta)
    return [
        gerar_xlsx_mina(pasta / "orcamento_opex_mina_2026.xlsx"),
        gerar_csv_administrativo(pasta / "orcamento_administrativo_2026.csv"),
        gerar_csv_lancamentos(pasta / "lancamentos_orcado_realizado_2026.csv"),
    ]


if __name__ == "__main__":  # pragma: no cover
    for p in gerar_todos():
        print(p)
