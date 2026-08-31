"""Transcricao e resumo estruturado de ligacoes do Bitrix24."""

from .resumo import ESQUEMA, MODELO, ResumoLigacao, extrair_json, resumir
from .transcricao import (
    MODELO_PADRAO,
    Transcricao,
    Trecho,
    limpar_para_resumo,
    transcrever,
)

__version__ = "1.0.0"

__all__ = [
    "ESQUEMA",
    "MODELO",
    "MODELO_PADRAO",
    "ResumoLigacao",
    "Transcricao",
    "Trecho",
    "extrair_json",
    "limpar_para_resumo",
    "resumir",
    "transcrever",
]
