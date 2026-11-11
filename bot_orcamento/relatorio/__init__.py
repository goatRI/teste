"""Pipeline do relatório: renderizar → gravar → LER O HTML E REVISAR → re-renderizar com a revisão.

O relatório só é considerado pronto quando a revisão feita sobre o arquivo final
coincide com a revisão impressa dentro dele (convergência em até 3 passadas).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..analise import Analise
from ..modelo import Verificacao
from ..revisoes import Historico
from ..revisor import assinatura, resumo_status, revisar_html, revisar_navegador
from .render import renderizar, status_geral


@dataclass
class Resultado:
    html: Path
    status: str
    revisao: dict
    verificacoes: list[Verificacao]
    arquivos: dict[str, Path] = field(default_factory=dict)
    passadas: int = 0


def _verificar(caminho: Path, a: Analise, navegador: bool, pasta_rev: Path, total_fonte: float | None,
               pdf: Path | None) -> list[Verificacao]:
    v = revisar_html(caminho, total_fonte)
    if navegador:
        base = a.cenario("base")
        v += revisar_navegador(caminho, base.economia, a.total, pasta_rev, pdf)
    return v


def gerar_relatorio(a: Analise, pasta_saida: str | Path, descricao_revisao: str | None = None,
                    parecer: dict | None = None, navegador: bool = True, pdf: bool = False,
                    excel: bool = True, total_fonte: float | None = None, log=print) -> Resultado:
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"analise-orcamentaria-{a.meta['slug']}"
    html_path = pasta / f"{nome}.html"
    pasta_rev = pasta / "revisao"
    hist = Historico(pasta / "historico_revisoes.json")
    rev = hist.preparar(a, descricao_revisao)
    linha_tempo = hist.linha_do_tempo(rev)

    # passada 1: relatório com a revisão pendente
    html_path.write_text(renderizar(a, rev, linha_tempo, None, parecer), encoding="utf-8")
    log(f"Relatório gerado (passada 1). Lendo o HTML para revisar: {html_path.name}")
    verif = _verificar(html_path, a, navegador, pasta_rev, total_fonte, None)
    passadas = 1
    convergiu = False

    def imprimir(v: list[Verificacao]) -> None:
        rev["status"] = resumo_status(v)
        rev["verificado"] = status_geral(v)["rotulo"]
        html_path.write_text(renderizar(a, rev, hist.linha_do_tempo(rev), v, parecer), encoding="utf-8")

    # passadas seguintes: imprime a revisão no relatório e confere de novo o ARQUIVO FINAL
    for _ in range(3):
        imprimir(verif)
        passadas += 1
        final = _verificar(html_path, a, navegador, pasta_rev, total_fonte,
                           (pasta / f"{nome}.pdf") if pdf else None)
        if assinatura(final) == assinatura(verif):
            verif, convergiu = final, True
            break
        log("Resultado da revisão mudou após reimpressão; revisando de novo.")
        verif = final
    if not convergiu:
        verif.append(Verificacao("V27", "Revisão estável entre passadas", "alerta",
                                 "O resultado da revisão mudou entre reimpressões; o checklist impresso é o da "
                                 "última leitura do arquivo.", "Navegador"))
        imprimir(verif)
    hist.registrar(rev)

    arquivos = {"html": html_path, "historico": hist.caminho}
    checklist = pasta_rev / "checklist.json"
    checklist.parent.mkdir(parents=True, exist_ok=True)
    checklist.write_text(json.dumps({"rev": rev["rev"], "status": rev["status"], "passadas": passadas,
                                     "verificacoes": [v.__dict__ for v in verif]}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    arquivos["checklist"] = checklist
    for nome_shot in ("relatorio-desktop.png", "relatorio-celular.png"):
        if (pasta_rev / nome_shot).exists():
            arquivos[nome_shot] = pasta_rev / nome_shot
    if pdf and (pasta / f"{nome}.pdf").exists():
        arquivos["pdf"] = pasta / f"{nome}.pdf"
    if excel:
        from ..excel import exportar_excel

        arquivos["excel"] = exportar_excel(a, pasta / f"{nome}.xlsx", verif, rev["rev"])
    from ..saida import exportar_json

    arquivos["json"] = exportar_json(a, pasta / "analise.json", rev, verif)
    return Resultado(html_path, rev["status"], rev, verif, arquivos, passadas)
