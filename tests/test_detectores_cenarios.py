from pathlib import Path

import pytest

from bot_orcamento.cenarios import aplicar
from bot_orcamento.modelo import Linha, LinhaOportunidade, Oportunidade


def _titulos(a):
    return [o.titulo for o in a.oportunidades]


def test_detectores_mina(analises):
    a = analises["mina"]
    t = " | ".join(_titulos(a))
    assert "Horas extras acima do patamar saudável" in t
    assert "Possível duplicidade: Licenças de Software - Paradigm / Opit" in t
    assert "Equalização de preço unitário — Pneus OTR 40.00R57" in t
    assert "Equalização de preço unitário — Bits de perfuração" in t
    assert "Crescimento acima da inflação em 7 linhas" in t
    assert "Consolidação de fornecedores — Manutenção" in t
    assert "Rubricas genéricas e contingência sem destinação definida" in t
    assert all(d["status"] != "erro" for d in a.detectores)


def test_horas_extras_valor(analises):
    o = next(o for o in analises["mina"].oportunidades if o.detector == "horas_extras")
    # HE 2.918.000 − 5% × salários 18.240.000 = 2.006.000
    assert o.economia("base") == pytest.approx(2_006_000, abs=1)


def test_dezembro_ignora_sazonalidade_conhecida(analises):
    o = next(o for o in analises["mina"].oportunidades if "dezembro" in o.titulo)
    linhas = {analises["mina"].estrutura.itens[i].descricao for i in range(len(analises["mina"].estrutura.itens))
              if analises["mina"].estrutura.itens[i].id in {lo.linha_id for lo in o.linhas}}
    assert "Eventos e confraternizações" in linhas
    assert not any("PLR" in d or "Seguros" in d for d in linhas)


def test_execucao_folga_e_estouro(analises):
    a = analises["lanc"]
    folga = next(o for o in a.oportunidades if o.detector == "execucao_orcamentaria")
    assert len(folga.linhas) == 6 and folga.confianca == "alta"
    assert {al.titulo.split("· ")[-1] for al in a.alertas} >= {"Energia elétrica", "Frete de produtos acabados"}
    # linha em estouro não recebe corte de categoria
    energia = next(x for x in a.estrutura.itens if x.descricao == "Energia elétrica")
    for o in a.oportunidades:
        assert all(lo.linha_id != energia.id for lo in o.linhas if o.detector == "alavancas_categoria")
    assert any(c.id == "realinhamento" for c in a.cenarios)


def test_cenarios_ordenados_e_meta(analises):
    for a in analises.values():
        e = {c.id: c.economia for c in a.cenarios}
        assert 0 <= e["conservador"] <= e["base"] <= e["agressivo"] <= a.total
        meta = a.cenario("meta")
        if meta.meta_atingida:
            assert meta.economia >= a.premissas["meta_reducao"] * a.total - 1


def test_regra_de_sobreposicao_e_teto():
    linhas = [Linha(id=1, linha_origem=2, descricao="X", orcado=1000.0)]

    def op(i, taxa, total=False):
        return Oportunidade(detector="t", titulo="t", racional="", acao="", id=f"OP-{i}", permite_total=total,
                            linhas=[LinhaOportunidade(1, 1000.0, {"conservador": taxa, "base": taxa, "agressivo": taxa})])

    ops = [op(1, 0.1), op(2, 0.1)]
    assert aplicar(linhas, ops, {"OP-1": "base", "OP-2": "base"}, 0.6)[1] == pytest.approx(810.0)  # 19%, não 20%
    ops = [op(1, 0.5), op(2, 0.5)]
    assert aplicar(linhas, ops, {"OP-1": "base", "OP-2": "base"}, 0.6)[1] == pytest.approx(400.0)  # teto 60%
    ops = [op(1, 1.0, total=True)]
    assert aplicar(linhas, ops, {"OP-1": "base"}, 0.6)[1] == 0.0  # duplicidade pode zerar


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / ".claude" / "skills" / "compras-emergenciais").exists(),
                    reason="skill de exemplo não presente neste checkout")
def test_skill_do_repositorio_carregada(analises):
    a = analises["mina"]
    assert any(s["nome"] == "compras-emergenciais" and s["status"] == "carregada" for s in a.skills)
    assert any(o.detector == "compras_emergenciais" for o in a.oportunidades)
