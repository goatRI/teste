from pathlib import Path

import pytest

from bot_orcamento.exemplos import gerar_todos


@pytest.fixture(scope="session")
def exemplos(tmp_path_factory) -> dict[str, Path]:
    pasta = tmp_path_factory.mktemp("exemplos")
    mina, adm, lanc = gerar_todos(pasta)
    return {"mina": mina, "adm": adm, "lanc": lanc}


@pytest.fixture(scope="session")
def analises(exemplos):
    from bot_orcamento.analise import analisar

    return {k: analisar(v, log=lambda *x: None) for k, v in exemplos.items()}
