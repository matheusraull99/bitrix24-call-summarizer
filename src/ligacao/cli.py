"""Linha de comando do resumidor de ligações."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

import requests
from bitrix24_client import from_env
from bitrix24_client.errors import BitrixError

from .resumo import ResumoLigacao, resumir
from .transcricao import MODELO_PADRAO, limpar_para_resumo, transcrever

log = logging.getLogger("ligacao")


def baixar_gravacao(url: str, destino: Path) -> Path:
    """Baixa a gravação em fluxo, sem carregar tudo na memória."""
    with requests.get(url, stream=True, timeout=120) as resposta:
        resposta.raise_for_status()
        with destino.open("wb") as fh:
            for pedaco in resposta.iter_content(chunk_size=1 << 16):
                fh.write(pedaco)
    return destino


def processar(bx, cliente_ia, ligacao: dict, modelo: str, dry_run: bool) -> ResumoLigacao | None:
    """Transcreve, resume e registra uma ligação."""
    url = ligacao.get("CALL_RECORD_URL") or ligacao.get("RECORD_FILE_ID")
    if not url:
        log.info("ligacao %s sem gravacao", ligacao.get("ID"))
        return None

    with tempfile.TemporaryDirectory() as tmp:
        caminho = baixar_gravacao(str(url), Path(tmp) / f"{ligacao['ID']}.mp3")
        transcricao = transcrever(caminho, modelo=modelo)

    if not transcricao.trechos:
        log.warning("ligacao %s: transcricao vazia", ligacao.get("ID"))
        return None

    contexto = f"Ligacao de {transcricao.duracao / 60:.0f} minutos. "
    contexto += transcricao.resumo_estrutural()
    resumo = resumir(cliente_ia, limpar_para_resumo(transcricao.texto), contexto)

    if dry_run:
        print(f"\n--- ligacao {ligacao['ID']} ---")
        print(transcricao.resumo_estrutural())
        print(resumo.para_timeline())
        return resumo

    entidade_id = ligacao.get("CRM_ENTITY_ID")
    if entidade_id:
        bx.call(
            "crm.timeline.comment.add",
            {
                "fields": {
                    "ENTITY_ID": entidade_id,
                    "ENTITY_TYPE": str(ligacao.get("CRM_ENTITY_TYPE", "deal")).lower(),
                    "COMMENT": resumo.para_timeline(),
                }
            },
        )
    return resumo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="resumir-ligacoes",
        description="Transcreve e resume ligacoes gravadas no Bitrix24.",
    )
    p.add_argument("--desde", help="data ISO inicial (padrao: ontem)")
    p.add_argument("--limite", type=int, default=20)
    p.add_argument("--modelo-whisper", default=MODELO_PADRAO,
                   choices=["tiny", "base", "small", "medium", "large"])
    p.add_argument("--executar", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("defina ANTHROPIC_API_KEY", file=sys.stderr)
        return 2

    from anthropic import Anthropic
    from datetime import date, timedelta

    desde = args.desde or (date.today() - timedelta(days=1)).isoformat()

    try:
        bx = from_env()
        ligacoes = list(
            bx.fetch_all(
                "voximplant.statistic.get",
                {"FILTER": {">=CALL_START_DATE": desde, "CALL_FAILED_CODE": "200"}},
            )
        )[: args.limite]
    except BitrixError as exc:
        print(f"erro no portal: {exc}", file=sys.stderr)
        return 2

    print(f"{len(ligacoes)} ligacoes desde {desde}")

    cliente_ia = Anthropic()
    resumidas, atencao, falhas = 0, 0, 0

    for ligacao in ligacoes:
        try:
            resumo = processar(bx, cliente_ia, ligacao, args.modelo_whisper,
                               not args.executar)
        except Exception as exc:  # noqa: BLE001 - uma ligacao nao para o lote
            log.exception("falha na ligacao %s", ligacao.get("ID"))
            falhas += 1
            continue

        if resumo is None:
            continue
        resumidas += 1
        if resumo.merece_atencao:
            atencao += 1
            print(
                f"  [!] ligacao {ligacao['ID']}: {resumo.sentimento}, "
                f"interesse {resumo.interesse}, "
                f"{len(resumo.proximos_passos)} proximos passos"
            )

    modo = "EXECUTADO" if args.executar else "SIMULACAO (use --executar)"
    print(f"\n{modo}\n{resumidas} resumidas | {atencao} merecem atencao | {falhas} falhas")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
