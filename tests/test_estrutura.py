import openpyxl
import pytest
from openpyxl.styles import Font

from bot_orcamento.estrutura import analisar_estrutura
from bot_orcamento.leitura import ler_orcamento
from bot_orcamento.taxonomia import Taxonomia


def _estr(p):
    return analisar_estrutura(ler_orcamento(p), Taxonomia())


def test_mina_subtotais_e_conciliacao(exemplos):
    e = _estr(exemplos["mina"])
    assert len(e.itens) == 51
    assert sum(1 for x in e.agregadoras if x.tipo == "subtotal") == 6
    assert sum(1 for x in e.agregadoras if x.tipo == "total") == 1
    assert e.conciliacao["status"] == "ok"
    assert e.total_itens == pytest.approx(161_828_000, abs=0.01)
    assert e.cobertura_classificacao == 1.0


def test_hierarquia_por_codigo(tmp_path):
    p = tmp_path / "hier.csv"
    p.write_text("Conta;Descrição;Valor\n3;Despesas;300\n3.1;Viagens;100\n3.2;Diesel;200\n", encoding="utf-8")
    e = _estr(p)
    assert [x.descricao for x in e.itens] == ["Viagens", "Diesel"]
    assert e.agregadoras[0].motivo_tipo.startswith("código")
    assert e.total_itens == 300


def test_subtotal_por_soma_em_negrito(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Descrição", "Orçado"])
    ws.append(["Passagens", 120.0])
    ws.append(["Hotel", 80.0])
    ws.append(["Viagens", 200.0])
    ws["A4"].font = Font(bold=True)
    ws.append(["Diesel", 500.0])
    p = tmp_path / "negrito.xlsx"
    wb.save(p)
    e = _estr(p)
    assert sorted(x.descricao for x in e.itens) == ["Diesel", "Hotel", "Passagens"]
    assert e.total_itens == 700


def test_total_divergente_vira_qualidade(tmp_path):
    p = tmp_path / "div.csv"
    p.write_text("Descrição;Valor\nViagens;100\nDiesel;200\nTOTAL GERAL;350\n", encoding="utf-8")
    e = _estr(p)
    assert e.conciliacao["status"] == "divergente"
    assert any(q["tipo"] == "total_divergente" for q in e.qualidade)


@pytest.mark.parametrize("desc,cat", [
    ("Horas extras", "horas_extras"), ("Óleo diesel", "combustiveis"), ("Pneus OTR 40.00R57", "pneus"),
    ("Mão de obra terceirizada", "servicos_terceiros"), ("Manutenção geral de equipamentos", "manutencao"),
    ("Aluguel de escritório", "aluguel_imoveis"), ("Locação de equipamentos (escavadeira)", "locacao_equipamentos"),
    ("Taxas e licenças ambientais", "ssma"), ("Licenças de software (Paradigm/Opit)", "ti_telecom"),
    ("Encargos sociais", "pessoal"), ("Vale transporte", "pessoal"), ("Despesas diversas", "contingencia"),
    ("Transporte de funcionários", "alimentacao_transporte"), ("CFEM e royalties", "impostos"),
])
def test_taxonomia(desc, cat):
    assert Taxonomia().classificar(desc)[0] == cat
