"""Taxonomia de custos: como o bot reconhece cada linha e que alavancas de redução se aplicam.

A classificação é por palavras-chave sobre a descrição normalizada (sem acento, minúscula),
em ordem de especificidade: a primeira categoria cujo termo aparece na descrição vence.
Se a descrição não casar, tenta-se a categoria/grupo informados no próprio arquivo.

Termos terminados em ``*`` casam por prefixo (``manut*`` → manutenção, manutenções).
Skills de taxonomia (``categorias.json``) podem acrescentar categorias e termos.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .util import normalizar


@dataclass
class Categoria:
    id: str
    nome: str
    palavras: list[str]
    faixa: tuple[float, float, float] = (0.0, 0.0, 0.0)  # conservador, base, agressivo
    comportamento: str = "fixo"  # fixo | variavel | semi
    discricionaria: bool = False
    protegida: bool = False
    esforco: str = "medio"
    horizonte: str = "medio"
    confianca: str = "media"
    alavanca: str = ""
    acoes: list[str] = field(default_factory=list)
    indicador: str = ""
    excluir: list[str] = field(default_factory=list)


C = Categoria

CATEGORIAS_PADRAO: list[Categoria] = [
    C("horas_extras", "Horas extras e adicionais",
      ["hora extra*", "horas extra*", "he", "adicional noturno", "sobreaviso", "dsr sobre he"],
      (0.15, 0.25, 0.40), "variavel", False, False, "medio", "curto", "media",
      "Controle de horas extras",
      ["Revisar escalas e dimensionamento de turnos para eliminar hora extra estrutural",
       "Exigir aprovação prévia do gestor para HE acima de 10 h/mês por colaborador",
       "Implantar banco de horas onde a convenção permitir",
       "Acompanhar HE por centro de custo semanalmente"],
      "% de horas extras sobre a folha (meta ≤ 5%)"),
    C("treinamento", "Treinamento e desenvolvimento",
      ["treinament*", "capacitac*", "curso*", "workshop*", "congresso*", "seminario*", "palestra*"],
      (0.05, 0.10, 0.20), "fixo", True, False, "baixo", "curto", "media",
      "Racionalização de treinamentos",
      ["Priorizar treinamentos obrigatórios (NRs) e críticos para a operação",
       "Migrar conteúdos teóricos para EAD e multiplicadores internos",
       "Negociar pacotes anuais com instituições de ensino"],
      "Custo por hora de treinamento"),
    C("perfuracao_desmonte", "Perfuração e desmonte",
      ["explosiv*", "emulsao", "anfo", "detonac*", "desmonte", "espoleta*", "cordel",
       "perfurac*", "bits", "bit", "broca*", "haste*", "booster*", "retardo*"],
      (0.02, 0.05, 0.08), "variavel", False, False, "medio", "medio", "media",
      "Otimização do plano de fogo e da perfuração",
      ["Revisar malha de perfuração e razão de carga (kg/t) com base na fragmentação medida",
       "Reduzir sobreperfuração e repasse de material",
       "Negociar contrato de explosivos por tonelada desmontada",
       "Controlar consumo de bits e hastes por metro perfurado"],
      "Razão de carga (kg/t) e custo por metro perfurado"),
    C("pneus", "Pneus e material rodante",
      ["pneu*", "otr", "material rodante", "rodante*", "recapag*", "camara de ar", "esteira* de trator"],
      (0.04, 0.08, 0.12), "variavel", False, False, "medio", "medio", "media",
      "Gestão de vida útil de pneus",
      ["Monitorar pressão e temperatura (TPMS) e respeitar o índice TKPH",
       "Manter vias e drenagem para reduzir cortes e desgaste prematuro",
       "Avaliar reparo e recapagem de pneus OTR",
       "Negociar contrato por hora rodada (CPH)"],
      "Custo por hora rodada e vida média do pneu (h)"),
    C("combustiveis", "Combustíveis e lubrificantes",
      ["diesel", "combustiv*", "gasolina", "etanol", "oleo*", "lubrific*", "graxa*", "arla*", "glp",
       "abastecimento"],
      (0.03, 0.06, 0.10), "variavel", False, False, "medio", "medio", "media",
      "Eficiência no consumo de combustível",
      ["Reduzir marcha lenta e filas com despacho e telemetria",
       "Treinar operadores em operação econômica",
       "Otimizar DMT, rampas e layout de pilhas",
       "Controlar abastecimento com identificação por equipamento"],
      "Litros por tonelada movimentada (L/t) e L/h por equipamento"),
    C("energia_utilidades", "Energia e utilidades",
      ["energia*", "consumo de energia", "agua", "esgoto", "gas natural", "utilidade*", "demanda contratada",
       "tarifa de energia"],
      (0.04, 0.08, 0.15), "semi", False, False, "medio", "medio", "media",
      "Gestão de energia e utilidades",
      ["Avaliar migração ou renegociação no mercado livre de energia",
       "Ajustar demanda contratada e corrigir fator de potência",
       "Deslocar cargas para fora do horário de ponta",
       "Reduzir perdas de água e reaproveitar efluentes"],
      "kWh por tonelada e custo médio do MWh"),
    C("ti_telecom", "TI, software e telecom",
      ["software*", "licenca* de software", "licenca* de uso", "sistemas de informac*", "erp", "sistema de gestao", "saas", "cloud", "nuvem",
       "hardware", "computador*", "notebook*", "telefon*", "internet", "link* de dados",
       "celular*", "telecom*", "ti", "tecnologia da informacao", "servidor*", "datacenter",
       "licencas de colaborac*", "e mail", "email", "office 365", "google workspace", "microsoft"],
      (0.08, 0.15, 0.25), "fixo", False, False, "baixo", "curto", "media",
      "Racionalização de software, TI e telecom",
      ["Inventariar licenças e cancelar as ociosas (usuários inativos)",
       "Renegociar contratos anuais e consolidar fornecedores de telecom",
       "Revisar planos de telefonia móvel e links de dados",
       "Avaliar alternativas equivalentes de menor custo"],
      "Custo de TI por usuário e % de licenças ativas"),
    C("seguros", "Seguros",
      ["seguro*", "apolice*", "premio de seguro"],
      (0.03, 0.07, 0.12), "fixo", False, False, "baixo", "medio", "media",
      "Recotação do programa de seguros",
      ["Recotar apólices com três ou mais seguradoras/corretoras",
       "Revisar franquias e importâncias seguradas",
       "Consolidar apólices dispersas"],
      "Prêmio pago sobre importância segurada"),
    C("seguranca_patrimonial", "Segurança patrimonial",
      ["vigilan*", "seguranca patrimonial", "portaria*", "monitoramento eletronico", "cftv", "ronda*"],
      (0.05, 0.10, 0.15), "fixo", False, False, "medio", "medio", "media",
      "Otimização da vigilância",
      ["Substituir postos por monitoramento eletrônico (CFTV) onde viável",
       "Revisar a escala de postos 24 h",
       "Renegociar o contrato com base em custo por posto"],
      "Custo por posto de vigilância"),
    C("alimentacao_transporte", "Alimentação e transporte de pessoal",
      ["aliment*", "refeic*", "refeitorio", "restaurante*", "lanche*", "transporte de pessoal",
       "onibus", "fretado*", "fretamento*", "transporte de colaboradores", "transporte de funcionarios"],
      (0.03, 0.06, 0.10), "semi", False, False, "medio", "medio", "media",
      "Eficiência em alimentação e transporte de pessoal",
      ["Ajustar refeições ao efetivo real (controle por catraca)",
       "Redimensionar rotas e ocupação dos ônibus fretados",
       "Renegociar contratos com base no efetivo atual"],
      "Custo por refeição e taxa de ocupação dos ônibus",
      excluir=["vale"]),
    C("viagens", "Viagens e hospedagem",
      ["viage*", "passage*", "hospedag*", "hote*", "diarias de viagem", "reembolso de km",
       "quilometragem"],
      (0.15, 0.25, 0.40), "fixo", True, False, "baixo", "curto", "media",
      "Política de viagens",
      ["Substituir viagens internas por reuniões virtuais",
       "Exigir antecedência mínima de 14 dias para compra de passagens",
       "Fechar acordos corporativos com hotéis e companhias aéreas",
       "Definir teto de diárias por cargo"],
      "Gasto de viagem por colaborador"),
    C("veiculos_leves", "Veículos leves",
      ["veiculo*", "frota leve", "carro", "carros", "pick up", "picape*", "caminhonete*", "automov*"],
      (0.08, 0.15, 0.25), "fixo", False, False, "baixo", "curto", "media",
      "Racionalização da frota leve",
      ["Revisar a necessidade de cada veículo pela taxa de utilização",
       "Criar pool compartilhado de veículos",
       "Rever categoria e modelo dos veículos locados"],
      "km rodados por veículo/mês"),
    C("aluguel_imoveis", "Aluguel e imóveis",
      ["aluguel*", "locacao de imove*", "locacao de sala*", "condominio*", "imovel", "imoveis"],
      (0.03, 0.08, 0.15), "fixo", False, False, "alto", "longo", "media",
      "Racionalização de imóveis",
      ["Renegociar o aluguel no aniversário do contrato",
       "Consolidar espaços e adotar trabalho híbrido",
       "Revisar condomínio e taxas associadas"],
      "Custo por m² e taxa de ocupação",
      excluir=["equip*", "maquin*", "caminh*", "guindast*", "gerador*", "escavad*", "veicul*"]),
    C("locacao_equipamentos", "Locação de equipamentos",
      ["locacao de equip*", "locacao de maquin*", "locacao de caminh*", "aluguel de equip*",
       "aluguel de maquin*", "equipamento* locado*", "locacao de escavad*", "locacao de guindaste*",
       "locacao de geradores", "locacao*"],
      (0.05, 0.10, 0.20), "semi", False, False, "medio", "medio", "media",
      "Utilização de equipamentos locados",
      ["Desmobilizar equipamentos ociosos (utilização abaixo de 60%)",
       "Comparar locação × aquisição para uso contínuo",
       "Renegociar contratos por hora efetivamente trabalhada"],
      "Utilização física e disponibilidade dos equipamentos (%)"),
    C("transporte_logistica", "Transporte, frete e logística",
      ["frete*", "transporte*", "logistic*", "carreto*", "armazenag*", "pedagio*", "movimentacao de carga",
       "rodoviario", "ferroviario"],
      (0.04, 0.08, 0.12), "variavel", False, False, "medio", "medio", "media",
      "Otimização de frete e logística",
      ["Promover concorrência entre transportadoras (leilão de fretes)",
       "Aumentar a carga média por viagem",
       "Revisar rotas e janelas de carregamento",
       "Renegociar tarifa por tonelada-quilômetro"],
      "R$ por t·km",
      excluir=["vale"]),
    C("marketing_eventos", "Marketing, eventos e patrocínios",
      ["marketing", "publicidad*", "propaganda*", "evento*", "confraterniz*", "brinde*", "patrocin*",
       "midia*", "feira*", "comunicacao", "endomarketing"],
      (0.10, 0.20, 0.35), "fixo", True, False, "baixo", "curto", "media",
      "Revisão de eventos, patrocínios e comunicação",
      ["Priorizar ações com retorno mensurável",
       "Cancelar ou postergar eventos não essenciais",
       "Limitar brindes e confraternizações a um teto por área"],
      "Gasto por ação e retorno obtido"),
    C("consultoria", "Consultorias e assessorias",
      ["consultor*", "assessori*", "auditori*", "honorari*", "juridic*", "advoca*", "pericia*",
       "parecer*"],
      (0.10, 0.20, 0.35), "fixo", True, False, "medio", "curto", "media",
      "Gestão de consultorias e serviços especializados",
      ["Exigir escopo, entregáveis e business case antes de contratar",
       "Internalizar atividades recorrentes",
       "Cotar com no mínimo três fornecedores",
       "Contratar por entrega, não por hora"],
      "Gasto com consultoria por projeto/entregável"),
    C("ssma", "Saúde, segurança e meio ambiente",
      ["ambient*", "licenca ambiental", "licencas ambientais", "residuo*", "efluente*",
       "saude ocupacional", "exame* ocupaciona*", "aso", "sst", "seguranca do trabalho", "ssma",
       "hse", "condicionante*"],
      (0.0, 0.0, 0.0), "fixo", False, True, "alto", "longo", "baixa",
      "Conformidade legal — sem corte automático",
      ["Manter: são obrigações legais e de segurança; revisar apenas eficiência de contratação"],
      "Atendimento às condicionantes"),
    C("impostos", "Impostos, taxas e royalties",
      ["imposto*", "tribut*", "taxa*", "cfem", "royalt*", "iptu", "contribuic*", "icms", "iss",
       "pis", "cofins"],
      (0.0, 0.0, 0.0), "variavel", False, True, "alto", "longo", "baixa",
      "Obrigação tributária — sem corte automático",
      ["Avaliar planejamento tributário com a área fiscal (fora do escopo de corte)"],
      "—"),
    C("financeiras", "Despesas financeiras",
      ["juros", "encargos financeiros", "multa*", "variacao cambial", "despesas bancarias",
       "tarifas bancarias", "iof", "desagio"],
      (0.0, 0.05, 0.10), "fixo", False, True, "alto", "longo", "baixa",
      "Gestão financeira",
      ["Renegociar dívidas e tarifas bancárias", "Evitar multas por atraso com gestão de pagamentos"],
      "Custo efetivo da dívida"),
    C("depreciacao", "Depreciação e amortização",
      ["depreciac*", "amortizac*", "exaust*"],
      (0.0, 0.0, 0.0), "fixo", False, True, "alto", "longo", "baixa",
      "Sem efeito caixa",
      ["Sem ação de curto prazo (despesa contábil sem desembolso)"],
      "—"),
    C("capex", "Investimentos (CAPEX)",
      ["capex", "investiment*", "aquisicao de equip*", "compra de equip*", "obra*", "ampliac*",
       "implantac*", "imobilizad*", "projeto de capital"],
      (0.0, 0.05, 0.15), "fixo", False, False, "medio", "medio", "baixa",
      "Priorização de investimentos",
      ["Postergar projetos sem retorno comprovado",
       "Revisar escopo e especificação técnica",
       "Fasear os desembolsos ao longo do ano"],
      "VPL/TIR e cronograma físico-financeiro por projeto",
      excluir=["mao de obra"]),
    C("facilities", "Facilities (limpeza e conservação)",
      ["limpeza*", "conservac*", "jardinag*", "zelador*", "dedetiz*", "copa", "manutencao predial",
       "facilities", "higienizac*"],
      (0.05, 0.10, 0.15), "fixo", False, False, "baixo", "medio", "media",
      "Revisão de serviços de facilities",
      ["Revisar frequência e escopo (SLA) de limpeza e conservação",
       "Consolidar contratos de facilities",
       "Remunerar por produtividade (m² por posto)"],
      "Custo por m² atendido"),
    C("administrativas", "Despesas administrativas",
      ["material de escritorio", "materiais de escritorio", "papelaria", "escritorio", "impress*",
       "copias", "xerox", "correio*", "cartorio*", "assinatura*", "despesas administrativas",
       "despesa* administrativa*", "malote*", "uniformes administrativos"],
      (0.08, 0.15, 0.25), "fixo", True, False, "baixo", "curto", "media",
      "Racionalização de despesas administrativas",
      ["Digitalizar processos e reduzir impressão",
       "Centralizar compras de material de escritório",
       "Revisar cartório, correios e assinaturas recorrentes"],
      "Despesa administrativa por colaborador"),
    C("manutencao", "Manutenção",
      ["manut*", "reparo*", "consert*", "revisao de equip*", "preventiv*", "corretiv*", "oficina*",
       "peca*", "pecas", "sobressalente*", "componente*", "reposic*", "recondicion*", "reforma*"],
      (0.04, 0.08, 0.15), "semi", False, False, "medio", "medio", "media",
      "Excelência em manutenção",
      ["Aumentar manutenção preventiva/preditiva para reduzir corretivas",
       "Consolidar fornecedores de serviços e peças em acordos-quadro",
       "Recondicionar componentes em vez de trocar",
       "Gerir estoque de sobressalentes (críticos × obsoletos)"],
      "% de manutenção corretiva, MTBF e custo de manutenção por hora"),
    C("materiais", "Materiais e insumos",
      ["material*", "materiais", "insumo*", "consumo", "almoxarifad*", "epi*", "uniforme*",
       "ferrament*", "reagente*", "quimic*", "cal", "floculante*", "bola* de moinho", "corpo* moedor*",
       "revestiment*"],
      (0.04, 0.08, 0.12), "variavel", False, False, "medio", "medio", "media",
      "Compras estratégicas de materiais",
      ["Consolidar volumes em contratos anuais",
       "Padronizar especificações e reduzir a variedade de itens",
       "Usar leilão reverso / cotação competitiva",
       "Controlar consumo por centro de custo"],
      "Preço médio pago × preço de referência"),
    C("servicos_terceiros", "Serviços de terceiros",
      ["servico*", "terceir*", "contratad*", "prestacao de servic*", "empreit*", "mao de obra terceir*",
       "outsourcing", "subcontrat*"],
      (0.05, 0.10, 0.18), "semi", False, False, "medio", "medio", "media",
      "Renegociação e revisão de escopo de serviços contratados",
      ["Revisar escopo e dimensionamento de cada contrato",
       "Renegociar preço com base em referências de mercado e volume",
       "Remunerar por desempenho (SLA/KPI)",
       "Avaliar internalização × terceirização"],
      "Custo por unidade de serviço entregue"),
    C("pessoal", "Pessoal (salários, encargos e benefícios)",
      ["salari*", "ordenado*", "encargo* soc*", "encargos trabalhistas", "inss", "fgts", "beneficio*",
       "plr", "participacao nos lucros", "ferias", "13o*", "13 salario", "decimo terceiro", "folha*", "rescis*",
       "plano de saude", "assistencia medica", "odontolog*", "mao de obra propria", "pessoal",
       "remunerac*", "bonus", "estagi*", "pro labore", "vale refeic*", "vale alimentac*",
       "vale transporte", "previdencia privada", "gratificac*", "comiss*"],
      (0.0, 0.02, 0.04), "fixo", False, False, "alto", "longo", "baixa",
      "Gestão de quadro e produtividade",
      ["Congelar reposição de vagas não críticas",
       "Revisar estrutura organizacional (amplitude de controle)",
       "Rever benefícios de baixo valor percebido"],
      "Custo de pessoal por colaborador e por unidade produzida"),
    C("contingencia", "Contingências e rubricas genéricas",
      ["contingenc*", "reserva*", "imprevist*", "diversa*", "diversos", "outros", "outras despesas",
       "outras", "eventuai*", "gerais", "geral", "nao previst*", "verba*"],
      (0.15, 0.30, 0.50), "fixo", True, False, "baixo", "curto", "media",
      "Detalhamento de rubricas genéricas",
      ["Exigir memória de cálculo e detalhamento de cada rubrica genérica",
       "Limitar contingência a um percentual formal e com regra de liberação",
       "Reclassificar o que for identificável para a conta correta"],
      "% do orçamento em rubricas genéricas"),
]

NAO_CLASSIFICADO = Categoria(
    "nao_classificado", "Não classificado", [], (0.0, 0.0, 0.0), "fixo", False, False,
    "medio", "medio", "baixa", "Classificar a linha",
    ["Informar a natureza do gasto para que o bot aplique a alavanca correta"], "—",
)

# Termos sazonais legítimos: pico concentrado nestes casos é esperado, não oportunidade.
TERMOS_SAZONAIS = ["plr", "participacao nos lucros", "13o*", "13 salario", "decimo terceiro", "ferias", "bonus",
                   "dissidio", "iptu", "seguro*", "licenca* anua*", "anuidade*", "premio*",
                   "rescis*", "cfem", "auditoria*"]


def _regex(termo: str) -> re.Pattern[str]:
    """Cada palavra do termo pode terminar em ``*`` (prefixo): ``encargo* soc*``."""
    partes = []
    for tok in termo.split():
        prefixo = tok.endswith("*")
        t = normalizar(tok.rstrip("*"))
        if not t:
            continue
        partes.append(re.escape(t) + (r"[a-z0-9]*" if prefixo else r"\b"))
    return re.compile(r"\b" + r"\s+".join(partes))


@lru_cache(maxsize=4096)
def _rx(termo: str) -> re.Pattern[str]:
    return _regex(termo)


def contem_termo(texto_norm: str, termos: list[str]) -> str | None:
    for t in termos:
        if _rx(t).search(texto_norm):
            return t
    return None


class Taxonomia:
    def __init__(self, premissas: dict | None = None, extras: list[dict] | None = None):
        self.categorias: list[Categoria] = copy.deepcopy(CATEGORIAS_PADRAO)
        premissas = premissas or {}
        # categorias vindas de skills (mais específicas → entram primeiro)
        for d in extras or []:
            if any(c.id == d["id"] for c in self.categorias):
                cat = self.get(d["id"])
                cat.palavras = list(d.get("palavras", [])) + cat.palavras
                continue
            self.categorias.insert(0, Categoria(
                id=d["id"], nome=d.get("nome", d["id"]), palavras=list(d.get("palavras", [])),
                faixa=tuple(d.get("faixa", (0.0, 0.0, 0.0))),
                comportamento=d.get("comportamento", "fixo"),
                discricionaria=d.get("discricionaria", False),
                protegida=d.get("protegida", False), esforco=d.get("esforco", "medio"),
                horizonte=d.get("horizonte", "medio"), confianca=d.get("confianca", "media"),
                alavanca=d.get("alavanca", ""), acoes=list(d.get("acoes", [])),
                indicador=d.get("indicador", ""), excluir=list(d.get("excluir", [])),
            ))
        for cid, termos in (premissas.get("palavras_extras") or {}).items():
            cat = self.get(cid)
            if cat.id != "nao_classificado":
                cat.palavras = list(termos) + cat.palavras
        for cid, faixa in (premissas.get("faixas") or {}).items():
            cat = self.get(cid)
            if cat.id != "nao_classificado":
                cat.faixa = tuple(float(x) for x in faixa)  # type: ignore[assignment]
        protegidas = set(premissas.get("protegidas", []))
        if protegidas:
            for c in self.categorias:
                c.protegida = c.id in protegidas
        self._idx = {c.id: c for c in self.categorias}

    def get(self, cid: str) -> Categoria:
        for c in self.categorias:
            if c.id == cid:
                return c
        return NAO_CLASSIFICADO

    def nome(self, cid: str) -> str:
        return self.get(cid).nome

    def _casa(self, texto_norm: str) -> tuple[Categoria, str] | None:
        if not texto_norm:
            return None
        for c in self.categorias:
            if c.excluir and contem_termo(texto_norm, c.excluir):
                continue
            t = contem_termo(texto_norm, c.palavras)
            if t:
                return c, t
        return None

    def classificar(self, descricao: str, categoria_origem: str | None = None,
                    grupo: str | None = None) -> tuple[str, str, str]:
        """Retorna (id_categoria, confiança, termo que decidiu)."""
        d = normalizar(descricao)
        r = self._casa(d)
        if r:
            cat, termo = r
            conf = "alta" if (" " in termo.strip("*") or len(termo.strip("*")) >= 6) else "media"
            # confirmação pela categoria de origem aumenta a confiança
            if categoria_origem:
                r2 = self._casa(normalizar(categoria_origem))
                if r2 and r2[0].id == cat.id:
                    conf = "alta"
            return cat.id, conf, termo
        for fonte in (categoria_origem, grupo):
            r = self._casa(normalizar(fonte))
            if r:
                return r[0].id, "baixa", r[1]
        return "nao_classificado", "baixa", ""
