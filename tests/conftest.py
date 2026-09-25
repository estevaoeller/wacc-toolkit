from pathlib import Path

import pytest

from wacc_toolkit.collector import Contexto
from wacc_toolkit.storage import Repositorio

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo(tmp_path) -> Repositorio:
    return Repositorio(tmp_path / "bases")


@pytest.fixture
def ctx(repo) -> Contexto:
    return Contexto(repo)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
