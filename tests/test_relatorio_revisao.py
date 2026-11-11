import json
import re
import shutil

import openpyxl
import pytest

from bot_orcamento.analise import analisar
from bot_orcamento.config import carregar_premissas
from bot_orcamento.relatorio import gerar_relatorio
from bot_orcamento.revisor import revisar_html


@pytest.fixture(scope="module")
def gerado(analises, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("rel")
    r = gerar_relatorio(analises["mina"], pasta, navegador=False, log=lambda *x: None)
    return r, pasta


def test_relatorio_aprovado_e_arquivos(gerado):
    r, pasta = gerado
    assert r.status == "aprovado", [v for v in r.verificacoes if v.status != "ok"]
    assert r.passadas == 2
    for k in ("html", "excel", "json", "checklist", "historico"):
        assert r.arquivos[k].exists()
    wb = openpyxl.load_workbook(r.arquivos["excel"])
    assert {"Resumo", "Orçamento adaptado", "Oportunidades", "Premissas", "Revisão"} <= set(wb.sheetnames)


def test_relatorios_dos_tres_formatos_aprovados(analises, tmp_path):
    for nome, a in analises.items():
        r = gerar_relatorio(a, tmp_path / nome, navegador=False, log=lambda *x: None)
        assert r.status == "aprovado", (nome, [(v.id, v.detalhe) for v in r.verificacoes if v.status != "ok"])


def test_revisor_pega_numero_adulterado(gerado, tmp_path):
    r, _ = gerado
    html = r.html.read_text(encoding="utf-8")
    m = re.search(r'data-check="cenario:base:economia" data-valor="([\d.]+)" data-fmt="brl">([^<]+)<', html)
    adulterado = html.replace(m.group(0), m.group(0).replace(m.group(2), "R$ 99.999.999,99"), 1)
    p = tmp_path / "adulterado.html"
    p.write_text(adulterado, encoding="utf-8")
    v = {x.id: x for x in revisar_html(p)}
    assert v["V10"].status == "falha"


def test_revisor_pega_artefato_e_json_inconsistente(gerado, tmp_path):
    r, _ = gerado
    html = r.html.read_text(encoding="utf-8")
    p = tmp_path / "nan.html"
    p.write_text(html.replace("<p class=\"lead\">", "<p class=\"lead\">undefined ", 1), encoding="utf-8")
    assert {x.id: x for x in revisar_html(p)}["V15"].status == "falha"
    dados = json.loads(re.search(r'id="DATA">(.*?)</script>', html, re.S).group(1))
    dados["cenarios"][1]["total_adaptado"] += 5000
    html2 = re.sub(r'(id="DATA">)(.*?)(</script>)',
                   lambda mm: mm.group(1) + json.dumps(dados, ensure_ascii=False) + mm.group(3), html, flags=re.S)
    p2 = tmp_path / "json.html"
    p2.write_text(html2, encoding="utf-8")
    assert {x.id: x for x in revisar_html(p2)}["V09"].status == "falha"


def test_revisor_confere_total_com_a_fonte(gerado):
    r, _ = gerado
    v = {x.id: x for x in revisar_html(r.html, total_esperado=1.0)}
    assert v["V07"].status == "falha"


def test_controle_de_revisoes(exemplos, tmp_path):
    pasta = tmp_path / "hist"
    a = analisar(exemplos["adm"], log=lambda *x: None)
    r0 = gerar_relatorio(a, pasta, navegador=False, excel=False, log=lambda *x: None)
    r0b = gerar_relatorio(analisar(exemplos["adm"], log=lambda *x: None), pasta, navegador=False, excel=False,
                          log=lambda *x: None)
    assert r0.revisao["rev"] == 0 and r0b.revisao["rev"] == 0  # nada mudou: mesma revisão
    a2 = analisar(exemplos["adm"], premissas=carregar_premissas(meta_reducao=0.15), log=lambda *x: None)
    r1 = gerar_relatorio(a2, pasta, navegador=False, excel=False, descricao_revisao="Meta 15%", log=lambda *x: None)
    assert r1.revisao["rev"] == 1
    assert any("Premissas alteradas" in t for t in r1.revisao["alteracoes"])
    hist = json.loads((pasta / "historico_revisoes.json").read_text(encoding="utf-8"))["revisoes"]
    assert [h["rev"] for h in hist] == [0, 1]
    assert "Rev. 01" in r1.html.read_text(encoding="utf-8")


def test_parecer_com_valor_inexistente_gera_alerta(analises, tmp_path):
    a = analises["adm"]
    par = {"texto": "Economia de **R$ 123.456.789,00** possível.", "origem": "teste", "aviso": ""}
    r = gerar_relatorio(a, tmp_path, parecer=par, navegador=False, excel=False, log=lambda *x: None)
    v = {x.id: x for x in r.verificacoes}
    assert v["V20"].status == "alerta"


@pytest.mark.skipif(shutil.which("node") is None, reason="sem Node/Playwright")
def test_navegador(analises, tmp_path):
    r = gerar_relatorio(analises["lanc"], tmp_path, navegador=True, excel=False, log=lambda *x: None)
    v = {x.id: x for x in r.verificacoes}
    if v.get("V21") and v["V21"].status == "pulado":
        pytest.skip("Playwright indisponível")
    assert v["V21"].status == "ok" and v["V22"].status == "ok" and v["V24"].status == "ok"


def test_seguranca_sem_caminho_local_e_sem_formula(tmp_path):
    p = tmp_path / "malicioso.csv"
    p.write_text('Descrição;Orçado\n=HYPERLINK("http://exemplo.invalido","clique");1000\n'
                 'Diesel <script>alert(1)</script>;2000\n', encoding="utf-8")
    a = analisar(p, pastas_skills=[], log=lambda *x: None)
    r = gerar_relatorio(a, tmp_path / "saida", navegador=False, fontes_externas=False, log=lambda *x: None)
    html = r.html.read_text(encoding="utf-8")
    assert str(tmp_path) not in html and "<script>alert(1)" not in html
    assert "fonts.googleapis.com" not in html and "Content-Security-Policy" in html
    v = {x.id: x for x in r.verificacoes}
    assert v["V06b"].status == "ok" and v["V04"].status == "ok"
    wb = openpyxl.load_workbook(r.arquivos["excel"])
    celulas = [c for row in wb["Orçamento adaptado"].iter_rows() for c in row if isinstance(c.value, str)
               and c.value.startswith("=HYPERLINK")]
    assert celulas and all(c.data_type == "s" for c in celulas)


def test_integridade_detecta_alteracao_manual(analises, tmp_path):
    from bot_orcamento.revisor import verificar_integridade

    r = gerar_relatorio(analises["adm"], tmp_path, navegador=False, excel=False, log=lambda *x: None)
    assert verificar_integridade(r.html).status == "ok"
    html = r.html.read_text(encoding="utf-8")
    r.html.write_text(html.replace("Resumo executivo", "Resumo executivo ", 1), encoding="utf-8")
    assert verificar_integridade(r.html).status == "falha"
