"""Linha de comando do Bot de Orçamento.

    python -m bot_orcamento analisar planilha.xlsx            # análise + relatório HTML revisado
    python -m bot_orcamento estrutura planilha.xlsx           # só mostra como o arquivo foi entendido
    python -m bot_orcamento revisar relatorio.html            # revisa um relatório já gerado
    python -m bot_orcamento nova-skill nome --tipo detector   # cria uma skill nova
    python -m bot_orcamento skills                            # lista skills e detectores
    python -m bot_orcamento exemplos                          # gera bases de demonstração
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import NOME_BOT, __version__
from .util import brl, pct

RAIZ = Path(__file__).resolve().parents[1]


def _pastas_skills(extras: list[str] | None) -> list[Path]:
    from .detectores import pastas_padrao

    return pastas_padrao(extras)


def _mapa(itens: list[str] | None) -> dict[str, str] | None:
    if not itens:
        return None
    m = {}
    for it in itens:
        if "=" not in it:
            raise SystemExit(f"--mapa espera campo=coluna (ex.: orcado=F), recebeu '{it}'")
        k, v = it.split("=", 1)
        m[k.strip()] = v.strip()
    return m


def _ler_parecer(caminho: str | None) -> dict | None:
    if not caminho:
        return None
    p = Path(caminho)
    return {"texto": p.read_text(encoding="utf-8"), "origem": f"Parecer do analista ({p.name})", "aviso": ""}


def cmd_analisar(a: argparse.Namespace) -> int:
    from .analise import analisar, resumo_texto
    from .config import carregar_premissas
    from .relatorio import gerar_relatorio
    from .revisor import texto_checklist

    premissas = carregar_premissas(a.config, meta_reducao=a.meta, ipca=a.ipca)
    log = (lambda *x: None) if a.silencioso else print
    an = analisar(a.arquivo, aba=a.aba, mapa=_mapa(a.mapa), premissas=premissas, titulo=a.titulo,
                  pastas_skills=_pastas_skills(a.skills), ia=a.ia, data_base=a.data_base, log=log)
    parecer = _ler_parecer(a.parecer)
    if parecer is None and a.ia:
        from . import ia

        ok, motivo = ia.disponivel()
        if ok:
            log("Gerando parecer executivo com Claude…")
            parecer = ia.gerar_parecer(an, log=log)
        else:
            log(f"Parecer por IA não gerado: {motivo}")
    an.parecer = parecer
    saida = Path(a.saida) if a.saida else Path("relatorios") / an.meta["slug"]
    res = gerar_relatorio(an, saida, descricao_revisao=a.descricao_revisao, parecer=parecer,
                          navegador=not a.sem_navegador, pdf=a.pdf, excel=not a.sem_excel,
                          fontes_externas=not a.sem_fontes_externas, log=log)
    if a.json:
        print(json.dumps({"status": res.status, "rev": res.revisao["rev"],
                          "arquivos": {k: str(v) for k, v in res.arquivos.items()}}, ensure_ascii=False))
    else:
        print()
        print(resumo_texto(an))
        print()
        print(f"Revisão Rev. {res.revisao['rev']:02d}: {res.status.upper()} ({res.passadas} passadas de leitura do HTML)")
        print(texto_checklist(res.verificacoes))
        print()
        for k, v in res.arquivos.items():
            print(f"  {k:<22} {v}")
    return 2 if res.status == "reprovado" else 0


def cmd_estrutura(a: argparse.Namespace) -> int:
    from .config import carregar_premissas
    from .detectores import carregar_plugins
    from .estrutura import analisar_estrutura
    from .leitura import ROTULO_CAMPO, _col_letra, ler_orcamento
    from .taxonomia import Taxonomia

    plugins = carregar_plugins(_pastas_skills(a.skills))
    lt = ler_orcamento(a.arquivo, aba=a.aba, mapa=_mapa(a.mapa))
    tax = Taxonomia(carregar_premissas(a.config), plugins.categorias_extras)
    es = analisar_estrutura(lt, tax)
    if a.json:
        from dataclasses import asdict

        print(json.dumps({"aba": lt.aba, "linha_cabecalho": lt.linha_cabecalho,
                          "colunas": [asdict(c) for c in lt.mapeamento.colunas],
                          "total_itens": es.total_itens, "total_declarado": es.total_declarado,
                          "conciliacao": es.conciliacao, "qualidade": es.qualidade, "avisos": lt.avisos,
                          "agregadoras": [(x.linha_origem, x.descricao, x.tipo, x.motivo_tipo) for x in es.agregadoras],
                          "nao_classificadas": [(x.linha_origem, x.descricao) for x in es.itens
                                                if x.categoria == "nao_classificado"]},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"Arquivo: {lt.arquivo} ({lt.formato_arquivo}) · aba: {lt.aba} · cabeçalho na linha {lt.linha_cabecalho}")
    if len(lt.abas_avaliadas) > 1:
        print("Abas avaliadas: " + "; ".join(f"{x['aba']} (pontos {x['pontuacao']:.0f}{', usada' if x['usada'] else ''})"
                                             for x in lt.abas_avaliadas))
    print(f"Formato: {lt.mapeamento.formato} · ano de referência: {lt.mapeamento.ano_referencia} · {es.hierarquia}")
    print("\nColunas:")
    for c in lt.mapeamento.colunas:
        if c.campo or not c.rotulo.startswith("(coluna"):
            print(f"  {_col_letra(c.indice):>3} {c.rotulo[:34]:<34} → {ROTULO_CAMPO.get(c.campo or '', '—'):<28} {c.motivo}")
    print(f"\nItens: {len(es.itens)} · fora da soma: {len(es.agregadoras)} · total {brl(es.total_itens)} · "
          f"declarado {brl(es.total_declarado)} · conciliação: {es.conciliacao['status']}")
    for x in es.agregadoras:
        print(f"  linha {x.linha_origem:>4} {x.tipo:<8} {x.descricao[:50]:<50} {brl(x.orcado):>22}  ({x.motivo_tipo})")
    print(f"\nClassificação: {pct(es.cobertura_classificacao)} do valor")
    for x in es.itens:
        if x.categoria == "nao_classificado":
            print(f"  sem categoria: linha {x.linha_origem} {x.descricao}")
    if es.qualidade or lt.avisos:
        print("\nQualidade / avisos:")
        for q in es.qualidade:
            print(f"  [{q['severidade']}] {q['mensagem']}")
        for av in lt.avisos:
            print(f"  [leitura] {av}")
    return 0


def cmd_revisar(a: argparse.Namespace) -> int:
    from .revisor import resumo_status, revisar_html, revisar_navegador, texto_checklist

    html = Path(a.html)
    total_fonte = None
    if a.fonte:
        from .analise import analisar

        total_fonte = analisar(a.fonte, aba=a.aba, pastas_skills=_pastas_skills(None), log=lambda *x: None).total
    v = revisar_html(html, total_fonte)
    if not a.sem_navegador:
        import re

        dados = json.loads(re.search(r'<script type="application/json" id="DATA">(.*?)</script>',
                                     html.read_text(encoding="utf-8"), re.S).group(1))
        base = next(c for c in dados["cenarios"] if c["id"] == "base")
        v += revisar_navegador(html, base["economia"], dados["totais"]["orcado"], html.parent / "revisao")
    st = resumo_status(v)
    print(f"Revisão de {html.name}: {st.upper()}")
    print(texto_checklist(v))
    return 2 if st == "reprovado" else 0


def cmd_nova_skill(a: argparse.Namespace) -> int:
    from .skills import criar_skill

    pasta = Path(a.pasta) if a.pasta else RAIZ / ".claude" / "skills"
    criados = criar_skill(a.nome, a.tipo, a.descricao, pasta)
    print(f"Skill '{a.nome}' ({a.tipo}) criada:")
    for c in criados:
        print(f"  {c}")
    print("Próximos passos: implemente o TODO, rode os testes (python -m pytest) e gere o relatório de novo.")
    return 0


def cmd_skills(a: argparse.Namespace) -> int:
    from .detectores import carregar_plugins

    pl = carregar_plugins(_pastas_skills(a.skills))
    print("Detectores:")
    for d in pl.detectores:
        print(f"  {d.id:<30} {d.origem:<26} {d.nome}" + (f"  [requer: {', '.join(d.requer)}]" if d.requer else ""))
    print("\nSkills com código (carregadas pelo motor):")
    if not pl.skills:
        print("  (nenhuma — crie com: python -m bot_orcamento nova-skill <nome> --tipo detector)")
    for s in pl.skills:
        print(f"  {s['nome']:<30} {s['tipo']:<10} {s['status']} {s['erro']}")
    if pl.categorias_extras:
        print(f"\nCategorias extras de taxonomia: {', '.join(c['id'] for c in pl.categorias_extras)}")
    return 0


def cmd_exemplos(a: argparse.Namespace) -> int:
    from .exemplos import gerar_todos

    for p in gerar_todos(a.pasta):
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bot_orcamento", description=f"{NOME_BOT} v{__version__} — lê, entende "
                                 "e propõe reduções de custo em orçamentos, com relatório HTML revisado.")
    ap.add_argument("--versao", action="version", version=f"{NOME_BOT} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def comuns(p):
        p.add_argument("--aba", help="Aba a usar: nome, lista 'A,B' ou 'todas' (padrão: a mais provável)")
        p.add_argument("--mapa", action="append", metavar="CAMPO=COLUNA",
                       help="Força o mapeamento de uma coluna (letra ou rótulo). Ex.: --mapa orcado=F")
        p.add_argument("--skills", action="append", metavar="PASTA", help="Pasta extra de skills")
        p.add_argument("--config", help="JSON com premissas (sobrescreve as padrão)")

    p = sub.add_parser("analisar", help="Analisa o orçamento e gera o relatório HTML revisado")
    p.add_argument("arquivo")
    comuns(p)
    p.add_argument("--saida", help="Pasta de saída (padrão: relatorios/<titulo>)")
    p.add_argument("--titulo", help="Título do relatório (padrão: detectado no arquivo)")
    p.add_argument("--data-base", help="Data-base exibida (padrão: ano do orçamento)")
    p.add_argument("--meta", type=float, help="Meta de redução, fração (0.1 = 10%%)")
    p.add_argument("--ipca", type=float, help="Inflação de referência, fração (0.045 = 4,5%%)")
    p.add_argument("--descricao-revisao", help="Texto da revisão (ex.: 'Rev. após ajuste do CC 1020')")
    p.add_argument("--parecer", help="Arquivo .md com o parecer do analista para incluir no relatório")
    p.add_argument("--ia", action="store_true", help="Usa Claude (API) para classificar linhas ambíguas e redigir o parecer")
    p.add_argument("--pdf", action="store_true", help="Gera também o PDF (A4 paisagem)")
    p.add_argument("--sem-navegador", action="store_true", help="Pula a revisão no navegador")
    p.add_argument("--sem-excel", action="store_true", help="Não gera o Excel")
    p.add_argument("--sem-fontes-externas", action="store_true",
                   help="Não referencia Google Fonts: o HTML não faz nenhuma conexão externa")
    p.add_argument("--json", action="store_true", help="Saída resumida em JSON")
    p.add_argument("--silencioso", action="store_true")
    p.set_defaults(f=cmd_analisar)

    p = sub.add_parser("estrutura", help="Mostra como o arquivo foi lido e entendido (sem gerar relatório)")
    p.add_argument("arquivo")
    comuns(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=cmd_estrutura)

    p = sub.add_parser("revisar", help="Lê um relatório HTML já gerado e refaz todas as verificações")
    p.add_argument("html")
    p.add_argument("--fonte", help="Arquivo de origem: relê e confere o total de forma independente")
    p.add_argument("--aba")
    p.add_argument("--sem-navegador", action="store_true")
    p.set_defaults(f=cmd_revisar)

    p = sub.add_parser("nova-skill", help="Cria uma skill (detector, leitor, taxonomia, cenário ou instruções)")
    p.add_argument("nome")
    p.add_argument("--tipo", choices=["detector", "leitor", "taxonomia", "cenario", "instrucoes"], default="detector")
    p.add_argument("--descricao", default="", help="Uma frase: o que a skill faz e quando usar")
    p.add_argument("--pasta", help="Pasta de skills (padrão: .claude/skills do projeto)")
    p.set_defaults(f=cmd_nova_skill)

    p = sub.add_parser("skills", help="Lista detectores e skills carregadas")
    p.add_argument("--skills", action="append", metavar="PASTA")
    p.set_defaults(f=cmd_skills)

    p = sub.add_parser("exemplos", help="Gera as bases de demonstração (dados fictícios)")
    p.add_argument("--pasta", default="exemplos")
    p.set_defaults(f=cmd_exemplos)

    a = ap.parse_args(argv)
    try:
        return a.f(a)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
