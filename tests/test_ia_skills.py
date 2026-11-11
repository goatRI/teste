import json
from types import SimpleNamespace as NS

from bot_orcamento import ia
from bot_orcamento.analise import analisar
from bot_orcamento.detectores import carregar_plugins
from bot_orcamento.skills import criar_skill


class ClienteFalso:
    """Imita o formato de resposta do SDK da Anthropic (sem rede)."""

    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.chamadas = payload, stop, []

    @property
    def beta(self):
        return NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.chamadas.append(kw)
        return NS(stop_reason=self.stop, content=[NS(type="text", text=json.dumps(self.payload))])


def test_parecer_ia_usa_saida_estruturada(analises):
    f = ClienteFalso({"resumo": "Resumo.", "destaques": ["A"], "riscos": [], "proximos_passos": ["B"]})
    par = ia.gerar_parecer(analises["adm"], client=f, log=lambda *x: None)
    assert "### Destaques" in par["texto"] and "revise" in par["aviso"]
    kw = f.chamadas[0]
    assert kw["model"] == ia.MODELO
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default"


def test_recusa_nao_quebra():
    assert ia._chamar("s", "p", {"type": "object"}, client=ClienteFalso({}, stop="refusal"), log=lambda *x: None) is None


def test_ia_classifica_sem_mudar_valores(exemplos):
    a = analisar(exemplos["adm"], log=lambda *x: None)
    lin = a.estrutura.itens[0]
    valor = lin.orcado
    lin.categoria = "nao_classificado"
    n = ia.classificar_nao_classificados(a.estrutura, a.taxonomia,
                                         client=ClienteFalso({"classificacoes": [{"id": lin.id, "categoria": "pessoal"}]}),
                                         log=lambda *x: None)
    assert n == 1 and lin.categoria == "pessoal" and lin.orcado == valor


def test_criar_skill_detector_e_carregar(tmp_path, exemplos):
    criados = criar_skill("minha regra", "detector", "Teste", tmp_path)
    assert (tmp_path / "minha-regra" / "detector.py") in criados
    det = (tmp_path / "minha-regra" / "detector.py")
    det.write_text(det.read_text(encoding="utf-8").replace("and False]", "and 'diesel' in x.descricao.lower()]"),
                   encoding="utf-8")
    a = analisar(exemplos["mina"], pastas_skills=[tmp_path], log=lambda *x: None)
    assert any(o.detector == "minha_regra" for o in a.oportunidades)


def test_skill_quebrada_nao_derruba(tmp_path, exemplos):
    (tmp_path / "quebrada").mkdir()
    (tmp_path / "quebrada" / "detector.py").write_text("ID='q'\nNOME='Q'\ndef detectar(ctx):\n    raise ValueError('x')\n")
    (tmp_path / "sem-contrato").mkdir()
    (tmp_path / "sem-contrato" / "detector.py").write_text("x = 1\n")
    pl = carregar_plugins([tmp_path])
    assert any(s["nome"] == "sem-contrato" and s["status"] == "erro" for s in pl.skills)
    a = analisar(exemplos["adm"], pastas_skills=[tmp_path], log=lambda *x: None)
    assert any(d["id"] == "q" and d["status"] == "erro" for d in a.detectores)


def test_criar_skill_taxonomia_cenario_leitor(tmp_path):
    for tipo in ("taxonomia", "cenario", "leitor", "instrucoes"):
        criar_skill(f"s {tipo}", tipo, "x", tmp_path)
    pl = carregar_plugins([tmp_path])
    assert {s["tipo"] for s in pl.skills} == {"taxonomia", "cenario", "leitor"}
    assert all(s["status"] == "carregada" for s in pl.skills)
