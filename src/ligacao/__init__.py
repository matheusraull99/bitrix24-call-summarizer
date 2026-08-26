"""Transcricao e resumo estruturado de ligacoes do Bitrix24."""

from .resumo import ESQUEMA, MODELO, ResumoLigacao, extrair_json, resumir
from .transcricao import (
    MODELO_PADRAO,
    Trecho,
    Transcricao,
    limpar_para_resumo,
    transcrever,
)

__version__ = "1.0.0"

__all__ = [
    "ESQUEMA",
    "MODELO",
    "MODELO_PADRAO",
    "ResumoLigacao",
    "Trecho",
    "Transcricao",
    "extrair_json",
    "limpar_para_resumo",
    "resumir",
    "transcrever",
]
