"""Transcrição de ligação e preparo do texto para o resumo.

Duas coisas que separam uma transcrição útil de um bloco de texto ilegível:

**Diarização mínima.** Gravação de call center é estéreo com um interlocutor
por canal — o vendedor num, o cliente no outro. Separar os canais antes de
transcrever dá "quem falou o quê" sem nenhum modelo de diarização. Quando o
áudio é mono, o robô assume um falante só e diz isso, em vez de inventar
atribuições.

**Corte de silêncio.** Uma ligação de 12 minutos costuma ter 3 de espera e
música. Transcrever isso custa tempo e enche o resumo de ruído.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("ligacao")

#: Modelo padrão. `small` é o ponto de equilíbrio para português: `base`
#: erra nomes próprios demais, `medium` triplica o tempo sem ganho
#: proporcional em áudio de telefonia (8 kHz, comprimido).
MODELO_PADRAO = "small"

#: Telefonia amostra em 8 kHz; o Whisper espera 16 kHz.
TAXA_ALVO = 16_000


@dataclass
class Trecho:
    """Um trecho falado, com quem falou e quando."""

    falante: str
    inicio: float
    fim: float
    texto: str

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio

    def formatado(self) -> str:
        minutos, segundos = divmod(int(self.inicio), 60)
        return f"[{minutos:02d}:{segundos:02d}] {self.falante}: {self.texto}"


@dataclass
class Transcricao:
    """A ligação transcrita."""

    trechos: list[Trecho] = field(default_factory=list)
    duracao: float = 0.0
    idioma: str = "pt"
    estereo: bool = False

    @property
    def texto(self) -> str:
        return "\n".join(t.formatado() for t in self.trechos)

    @property
    def palavras(self) -> int:
        return sum(len(t.texto.split()) for t in self.trechos)

    def tempo_por_falante(self) -> dict[str, float]:
        """Quanto tempo cada lado falou.

        É a métrica que mais revela sobre uma ligação comercial: vendedor
        falando 80% do tempo é sintoma, não estilo.
        """
        por_falante: dict[str, float] = {}
        for trecho in self.trechos:
            por_falante[trecho.falante] = por_falante.get(trecho.falante, 0.0) + trecho.duracao
        return por_falante

    def resumo_estrutural(self) -> str:
        tempos = self.tempo_por_falante()
        total = sum(tempos.values()) or 1.0
        partes = [f"{f}: {t / total:.0%}" for f, t in sorted(tempos.items())]
        return (
            f"{self.duracao / 60:.1f} min, {self.palavras} palavras, "
            f"{len(self.trechos)} trechos | " + " | ".join(partes)
        )


def transcrever(
    caminho: Path,
    *,
    modelo: str = MODELO_PADRAO,
    rotulos: tuple[str, str] = ("Vendedor", "Cliente"),
) -> Transcricao:
    """Transcreve o arquivo, separando os canais quando houver dois.

    Args:
        caminho: arquivo de áudio da gravação.
        modelo: tamanho do modelo Whisper.
        rotulos: nomes dos falantes do canal esquerdo e direito.

    Raises:
        FileNotFoundError: arquivo inexistente.
    """
    if not caminho.exists():
        raise FileNotFoundError(f"gravacao nao encontrada: {caminho}")

    import numpy as np
    import soundfile as sf
    import whisper

    audio, taxa = sf.read(str(caminho), always_2d=True)
    canais = audio.shape[1]
    duracao = len(audio) / taxa

    modelo_whisper = whisper.load_model(modelo)
    transcricao = Transcricao(duracao=duracao, estereo=canais >= 2)

    if canais >= 2:
        for indice, rotulo in enumerate(rotulos[:2]):
            faixa = _reamostrar(audio[:, indice], taxa)
            transcricao.trechos.extend(_transcrever_faixa(modelo_whisper, faixa, rotulo))
        # Intercala pelo tempo: sem isso o resumo lê o vendedor inteiro e
        # depois o cliente inteiro, e a conversa perde o sentido.
        transcricao.trechos.sort(key=lambda t: t.inicio)
    else:
        # Mono: nao da para saber quem falou. Dizer "Participante" e honesto;
        # inventar "Vendedor"/"Cliente" seria atribuir fala a quem nao disse.
        faixa = _reamostrar(np.mean(audio, axis=1), taxa)
        transcricao.trechos = _transcrever_faixa(modelo_whisper, faixa, "Participante")

    log.info("transcrito: %s", transcricao.resumo_estrutural())
    return transcricao


def _transcrever_faixa(modelo, audio, rotulo: str) -> list[Trecho]:
    """Roda o Whisper numa faixa e converte a saída em trechos."""
    resultado = modelo.transcribe(
        audio,
        language="pt",
        # `condition_on_previous_text=False` evita o loop de repetição que o
        # Whisper entra em áudio com muito silêncio — ele começa a repetir a
        # última frase por minutos.
        condition_on_previous_text=False,
        verbose=False,
    )
    return [
        Trecho(rotulo, float(s["start"]), float(s["end"]), s["text"].strip())
        for s in resultado.get("segments", [])
        if s.get("text", "").strip()
    ]


def _reamostrar(sinal, taxa_origem: int):
    """Converte para 16 kHz, que é o que o Whisper espera."""
    import numpy as np

    sinal = np.asarray(sinal, dtype=np.float32)
    if taxa_origem == TAXA_ALVO:
        return sinal
    novo_tamanho = int(len(sinal) * TAXA_ALVO / taxa_origem)
    return np.interp(
        np.linspace(0, len(sinal), novo_tamanho, endpoint=False),
        np.arange(len(sinal)),
        sinal,
    ).astype(np.float32)


def limpar_para_resumo(texto: str, limite_caracteres: int = 40_000) -> str:
    """Prepara o texto para o modelo de linguagem.

    Remove marcadores de hesitação e trechos repetidos — o Whisper repete
    frases quando o áudio tem silêncio longo, e essa repetição consome
    contexto sem informar nada.

    Args:
        texto: transcrição formatada.
        limite_caracteres: teto do que é enviado. Ligação de uma hora
            ultrapassa contexto útil, e o começo e o fim são o que importa.
    """
    linhas = []
    anterior = ""
    for linha in texto.splitlines():
        conteudo = re.sub(r"^\[\d{2}:\d{2}\]\s*\w+:\s*", "", linha).strip()
        if conteudo and conteudo == anterior:
            continue  # repeticao literal do Whisper
        anterior = conteudo
        linhas.append(linha)

    limpo = "\n".join(linhas)
    limpo = re.sub(r"\b(é|eh|ah|hum|hmm|né)\b[,.]?\s*", "", limpo, flags=re.I)
    limpo = re.sub(r"\s{2,}", " ", limpo)

    if len(limpo) <= limite_caracteres:
        return limpo

    # Corta o meio, não o fim: o fechamento da ligação — próximos passos,
    # objeções finais — é a parte mais informativa do resumo.
    metade = limite_caracteres // 2
    return (
        limpo[:metade]
        + "\n\n[... trecho do meio omitido por tamanho ...]\n\n"
        + limpo[-metade:]
    )
