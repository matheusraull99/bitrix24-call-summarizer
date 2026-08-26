"""Resumo estruturado da ligação com a API da Anthropic.

A escolha de design que importa: o modelo devolve **JSON com esquema fixo**,
não texto livre. Texto livre é bonito na demonstração e inútil no CRM — não
dá para filtrar por "teve objeção de preço" nem alertar quando não há
próximo passo definido.

E o esquema tem um campo obrigatório que a maioria dos resumos esquece:
``confianca``. O modelo precisa poder dizer "a transcrição estava ruim demais
para eu afirmar isso", em vez de inventar um próximo passo plausível.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("ligacao")

#: Modelo usado. Sonnet dá conta de resumo estruturado com folga e custa uma
#: fração de Opus num volume de centenas de ligações por dia.
MODELO = "claude-sonnet-5"

ESQUEMA = {
    "type": "object",
    "required": ["resumo", "sentimento", "confianca"],
    "properties": {
        "resumo": {"type": "string", "description": "2 a 4 frases sobre a conversa"},
        "assunto": {"type": "string", "description": "tema principal, em ate 6 palavras"},
        "sentimento": {"type": "string", "enum": ["positivo", "neutro", "negativo"]},
        "interesse": {"type": "string", "enum": ["alto", "medio", "baixo", "indefinido"]},
        "objecoes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "objecoes que o cliente levantou, uma por item",
        },
        "proximos_passos": {
            "type": "array",
            "items": {"type": "string"},
            "description": "compromissos assumidos na ligacao",
        },
        "prazo_citado": {
            "type": "string",
            "description": "prazo mencionado, ou vazio se nenhum",
        },
        "valor_citado": {
            "type": "string",
            "description": "valor mencionado, ou vazio se nenhum",
        },
        "confianca": {
            "type": "string",
            "enum": ["alta", "media", "baixa"],
            "description": "baixa quando a transcricao estava ruim ou truncada",
        },
    },
}

INSTRUCAO = """Voce resume ligacoes comerciais para um CRM.

Regras:
- Baseie-se APENAS no que foi dito. Nao infira intencao nao expressa.
- Se a transcricao estiver truncada ou confusa, marque confianca "baixa".
- "proximos_passos" so recebe compromisso explicito ("mando a proposta ate
  sexta"). Intencao vaga ("vou pensar") nao e proximo passo.
- "objecoes" so recebe objecao real do cliente, nao duvida operacional.
- Escreva em portugues do Brasil, direto, sem adjetivo de venda."""


@dataclass
class ResumoLigacao:
    """O resumo estruturado, pronto para virar campo e timeline."""

    resumo: str = ""
    assunto: str = ""
    sentimento: str = "neutro"
    interesse: str = "indefinido"
    objecoes: list[str] = field(default_factory=list)
    proximos_passos: list[str] = field(default_factory=list)
    prazo_citado: str = ""
    valor_citado: str = ""
    confianca: str = "media"

    @property
    def acionavel(self) -> bool:
        """``True`` quando há compromisso explícito e confiança suficiente."""
        return bool(self.proximos_passos) and self.confianca != "baixa"

    @property
    def merece_atencao(self) -> bool:
        """Ligação que o gestor deveria olhar.

        Interesse alto sem próximo passo é oportunidade escapando; sentimento
        negativo é risco. As duas valem interromper alguém.
        """
        return (self.interesse == "alto" and not self.proximos_passos) or (
            self.sentimento == "negativo"
        )

    def para_timeline(self) -> str:
        """Texto BBCode para o comentário no CRM."""
        linhas = [f"[B]Resumo da ligacao[/B] — {self.assunto or 'sem assunto definido'}", ""]
        linhas.append(self.resumo)
        linhas.append("")
        linhas.append(
            f"Sentimento: {self.sentimento} | Interesse: {self.interesse} "
            f"| Confianca do resumo: {self.confianca}"
        )

        if self.objecoes:
            linhas += ["", "[B]Objecoes[/B]"] + [f"  - {o}" for o in self.objecoes]
        if self.proximos_passos:
            linhas += ["", "[B]Proximos passos[/B]"] + [
                f"  - {p}" for p in self.proximos_passos
            ]
        else:
            linhas += ["", "[!] Nenhum proximo passo foi combinado na ligacao."]

        extras = [
            f"Prazo citado: {self.prazo_citado}" if self.prazo_citado else "",
            f"Valor citado: {self.valor_citado}" if self.valor_citado else "",
        ]
        extras = [e for e in extras if e]
        if extras:
            linhas += ["", " | ".join(extras)]

        return "\n".join(linhas)

    @classmethod
    def do_json(cls, dados: dict[str, Any]) -> ResumoLigacao:
        """Constrói tolerando campo ausente e tipo trocado.

        Modelo de linguagem às vezes devolve string onde o esquema pede
        lista. Normalizar aqui evita que uma variação de formato derrube o
        processamento de um lote inteiro de ligações.
        """
        def lista(chave: str) -> list[str]:
            valor = dados.get(chave) or []
            if isinstance(valor, str):
                return [valor] if valor.strip() else []
            return [str(v).strip() for v in valor if str(v).strip()]

        return cls(
            resumo=str(dados.get("resumo", "")).strip(),
            assunto=str(dados.get("assunto", "")).strip(),
            sentimento=_de_enum(dados.get("sentimento"), ("positivo", "neutro", "negativo"),
                                "neutro"),
            interesse=_de_enum(dados.get("interesse"),
                               ("alto", "medio", "baixo", "indefinido"), "indefinido"),
            objecoes=lista("objecoes"),
            proximos_passos=lista("proximos_passos"),
            prazo_citado=str(dados.get("prazo_citado", "")).strip(),
            valor_citado=str(dados.get("valor_citado", "")).strip(),
            confianca=_de_enum(dados.get("confianca"), ("alta", "media", "baixa"), "media"),
        )


def extrair_json(texto: str) -> dict[str, Any]:
    """Recupera o objeto JSON de uma resposta que pode ter texto em volta.

    Mesmo pedindo só JSON, o modelo às vezes embrulha em bloco de código ou
    escreve uma frase antes. Falhar por isso desperdiça a chamada — que é a
    parte cara do processo.

    Raises:
        ValueError: nenhum objeto JSON reconhecível na resposta.
    """
    tentativas = [texto]

    cerca = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
    if cerca:
        tentativas.insert(0, cerca.group(1))

    chaves = re.search(r"\{.*\}", texto, re.S)
    if chaves:
        tentativas.append(chaves.group())

    for tentativa in tentativas:
        try:
            dados = json.loads(tentativa)
        except json.JSONDecodeError:
            continue
        if isinstance(dados, dict):
            return dados

    raise ValueError(f"nenhum JSON valido na resposta: {texto[:200]}")


def resumir(cliente, transcricao_texto: str, contexto: str = "") -> ResumoLigacao:
    """Chama o modelo e devolve o resumo estruturado.

    Args:
        cliente: instância do SDK ``anthropic.Anthropic``.
        transcricao_texto: transcrição já limpa.
        contexto: informação do negócio, para o resumo ficar específico.
    """
    prompt = (
        (f"Contexto do negocio: {contexto}\n\n" if contexto else "")
        + "Transcricao da ligacao:\n\n"
        + transcricao_texto
        + "\n\nResponda APENAS com o objeto JSON no esquema pedido."
    )

    resposta = cliente.messages.create(
        model=MODELO,
        max_tokens=2000,
        system=INSTRUCAO,
        # `tools` + `tool_choice` forca a estrutura, em vez de pedir JSON no
        # texto e torcer. E a diferenca entre 95% e 100% de respostas validas.
        tools=[
            {
                "name": "registrar_resumo",
                "description": "Registra o resumo estruturado da ligacao",
                "input_schema": ESQUEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "registrar_resumo"},
        messages=[{"role": "user", "content": prompt}],
    )

    for bloco in resposta.content:
        if getattr(bloco, "type", "") == "tool_use":
            return ResumoLigacao.do_json(bloco.input)

    # Plano B: o modelo respondeu em texto apesar do tool_choice.
    texto = "".join(getattr(b, "text", "") for b in resposta.content)
    return ResumoLigacao.do_json(extrair_json(texto))


def _de_enum(valor: Any, validos: tuple[str, ...], padrao: str) -> str:
    """Normaliza um valor de enumeração, caindo no padrão quando não bate."""
    texto = str(valor or "").strip().lower()
    return texto if texto in validos else padrao
