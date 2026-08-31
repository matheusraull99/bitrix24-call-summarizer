"""Data e hora no fuso de quem usa o robô — nunca no fuso de quem o hospeda.

Servidor de CI e VM de nuvem rodam em UTC. `date.today()` num processo UTC
devolve o dia seguinte a partir das 21h de Brasília, e este robô usa data para
decidir *quais ligações entram no lote*: o padrão de `--desde` é "ontem". Rodando
às 22h, o "ontem" em UTC já é o "hoje" de Brasília — o lote pula um dia inteiro
de ligações e ninguém percebe, porque o robô termina com sucesso.

Por isso as datas do robô saem daqui, com o fuso escrito na cara. Usar UTC
"porque é neutro" não resolveria: mudaria a regra de negócio, que é o calendário
comercial brasileiro.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

#: Fuso de referência do negócio. Em Windows depende do pacote `tzdata`.
FUSO = ZoneInfo("America/Sao_Paulo")


def agora() -> datetime:
    """Instante atual, ciente do fuso (nunca ingênuo)."""
    return datetime.now(FUSO)


def hoje() -> date:
    """Data de hoje no calendário brasileiro."""
    return agora().date()
