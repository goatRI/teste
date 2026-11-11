import openpyxl
import pytest

from bot_orcamento.leitura import classificar_rotulo, ler_orcamento
from bot_orcamento.util import brl, brl_curto, ler_brl, para_numero, pct


@pytest.mark.parametrize("entrada,esperado", [
    (1234.5, 1234.5), ("1.234,56", 1234.56), ("R$ 1.234,56", 1234.56), ("(1.234,56)", -1234.56),
    ("1,234.56", 1234.56), ("12.500", 12500.0), ("3,5", 3.5), ("-", None), ("", None), ("abc", None),
    ("1.234.567,89", 1234567.89), ("12%", 0.12), ("1234-", -1234.0),
])
def test_para_numero(entrada, esperado):
    assert para_numero(entrada) == esperado


def test_formatacao_ptbr_e_ida_e_volta():
    assert brl(1234567.891) == "R$ 1.234.567,89"
    assert brl(-50) == "-R$ 50,00".replace("-R$ ", "R$ -") or brl(-50) == "R$ -50,00"
    assert brl_curto(17_219_047.85) == "R$ 17,2 mi"
    assert pct(0.1064) == "10,6%"
    assert ler_brl("R$ 1.234,56") == 1234.56
    assert abs(ler_brl("R$ 17,2 mi") - 17_200_000) < 1


@pytest.mark.parametrize("rotulo,campo", [
    ("Código", "codigo"), ("Descrição", "descricao"), ("Centro de Custo", "centro_custo"),
    ("Jan/26", "mes"), ("Real Jan", "mes_realizado"), ("Total 2026", "total"), ("Real 2025", "realizado"),
    ("Orçado 2026", "orcado"), ("Preço Unit.", "preco_unitario"), ("Qtd.", "quantidade"), ("Var. %", "ignorar"),
    ("Fornecedor", "fornecedor"), ("Competência", "competencia"), ("Cenário", "cenario"), (2025, "ano"),
])
def test_classificar_rotulo(rotulo, campo):
    assert classificar_rotulo(rotulo).campo == campo


def test_xlsx_mina_cabecalho_e_mapeamento(exemplos):
    lt = ler_orcamento(exemplos["mina"])
    m = lt.mapeamento
    assert lt.linha_cabecalho == 4
    assert m.colunas[m.campos["orcado"]].rotulo == "Total 2026"
    assert m.colunas[m.campos["ano_anterior"]].rotulo == "Real 2025"
    assert sorted(m.meses) == list(range(1, 13))
    assert m.ano_referencia == 2026
    assert "DADOS FICTÍCIOS" in lt.titulo_detectado
    assert len(lt.cabecalhos_grupo) >= 6


def test_csv_ptbr(exemplos):
    lt = ler_orcamento(exemplos["adm"])
    assert lt.mapeamento.colunas[lt.mapeamento.campos["orcado"]].rotulo == "Orçado 2026"
    assert "ano_anterior" in lt.mapeamento.campos  # Realizado 2025 < 2026
    assert "realizado" not in lt.mapeamento.campos
    assert lt.linhas[0].codigo == "4.1.01.001"


def test_formato_longo_pivota(exemplos):
    lt = ler_orcamento(exemplos["lanc"])
    assert lt.mapeamento.formato == "longo"
    assert len(lt.linhas) == 20
    assert all(len(x.meses) == 12 for x in lt.linhas)
    assert lt.meses_com_realizado == [1, 2, 3, 4, 5, 6]


def test_supercabecalho_em_duas_linhas(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Relatório de custos"])
    ws.append(["Conta", "Descrição", "Orçado 2026", None, None, "Realizado 2026", None, None])
    ws.append([None, None, "Jan", "Fev", "Mar", "Jan", "Fev", "Mar"])
    ws.append(["1.1", "Energia", 100, 110, 120, 90, 95, None])
    ws.append(["1.2", "Frete", 50, 50, 50, 70, 75, None])
    p = tmp_path / "duas_linhas.xlsx"
    wb.save(p)
    lt = ler_orcamento(p)
    assert lt.linha_cabecalho == 3
    assert sorted(lt.mapeamento.meses) == [1, 2, 3]
    # a coluna "Realizado Mar" está vazia: é descartada, e o realizado cobre jan–fev
    assert sorted(lt.mapeamento.meses_realizado) == [1, 2]
    assert lt.linhas[0].orcado == 330 and lt.linhas[0].realizado == 185
    assert lt.meses_com_realizado == [1, 2]


def test_mapa_manual(tmp_path):
    p = tmp_path / "estranho.csv"
    p.write_text("Item;Coisa;Grana\nA;Viagens;1.000,00\nB;Diesel;2.000,00\n", encoding="utf-8")
    lt = ler_orcamento(p, mapa={"orcado": "C", "descricao": "Coisa"})
    assert [x.orcado for x in lt.linhas] == [1000.0, 2000.0]
    assert lt.linhas[0].descricao == "Viagens"
