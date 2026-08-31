"""Testes do fuso — o robô decide lote por data, então a data tem que ser a nossa."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ligacao.tempo import FUSO, agora, hoje


def test_fuso_e_o_de_sao_paulo():
    assert FUSO.key == "America/Sao_Paulo"


def test_agora_nunca_e_ingenuo():
    assert agora().utcoffset() is not None


def test_hoje_e_a_data_de_sao_paulo():
    esperado = datetime.now(timezone.utc).astimezone(FUSO).date()
    assert hoje() == esperado


def test_hoje_pode_divergir_do_utc_no_fim_do_dia():
    """Às 22h de Brasília o UTC já virou o dia — é esse o bug que o módulo evita."""
    noite = datetime(2026, 3, 10, 22, 0, tzinfo=FUSO)
    assert noite.date() == date(2026, 3, 10)
    assert noite.astimezone(timezone.utc).date() == date(2026, 3, 11)
    assert (noite.date() - timedelta(days=1)) == date(2026, 3, 9)
