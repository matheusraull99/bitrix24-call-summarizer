# bitrix24-call-summarizer

Transcreve as ligações gravadas no Bitrix24 com Whisper e resume com Claude —
em **JSON estruturado**, não em texto livre.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Whisper](https://img.shields.io/badge/whisper-small-purple)
![Testes](https://img.shields.io/badge/testes-39%20passando-brightgreen)
![Licença](https://img.shields.io/badge/licença-MIT-lightgrey)

---

## Por que estruturado e não texto livre

Um resumo em prosa é bonito na demonstração e inútil no CRM. Não dá para
filtrar por "teve objeção de preço", nem alertar o gestor quando uma ligação
de interesse alto terminou **sem próximo passo combinado**.

```json
{
  "resumo": "Cliente pediu orçamento para reforma de 320 m². Achou o prazo longo.",
  "assunto": "Reforma Ed. Aurora",
  "sentimento": "positivo",
  "interesse": "alto",
  "objecoes": ["prazo de 45 dias é longo demais"],
  "proximos_passos": ["enviar proposta até sexta"],
  "prazo_citado": "45 dias úteis",
  "valor_citado": "R$ 85.000",
  "confianca": "alta"
}
```

O campo que a maioria dos resumos esquece é `confianca`. O modelo precisa
poder dizer "a transcrição estava ruim demais para eu afirmar isso" — em vez
de inventar um próximo passo plausível que ninguém combinou.

E a regra do prompt é explícita: **"vou pensar" não é próximo passo.** Só
compromisso declarado entra.

---

## Diarização de graça

Gravação de call center é estéreo com um interlocutor por canal. Separar os
canais antes de transcrever dá "quem falou o quê" sem modelo de diarização
nenhum. Os trechos são intercalados pelo tempo depois — sem isso o resumo
leria o vendedor inteiro e depois o cliente inteiro, e a conversa perderia o
sentido.

Quando o áudio é mono, o robô rotula tudo como `Participante` e diz isso.
Inventar "Vendedor"/"Cliente" seria atribuir fala a quem não disse.

Do lado prático, isso libera a métrica que mais revela sobre uma ligação
comercial:

```
7.3 min, 1284 palavras, 42 trechos | Cliente: 27% | Vendedor: 73%
```

Vendedor falando 73% do tempo é sintoma, não estilo.

---

## Uso

```bash
pip install -e ".[dev]"
cp .env.example .env   # BITRIX_WEBHOOK e ANTHROPIC_API_KEY
# ffmpeg precisa estar no PATH (dependência do Whisper)

resumir-ligacoes --desde 2026-09-01              # simula
resumir-ligacoes --desde 2026-09-01 --executar   # grava na timeline
resumir-ligacoes --modelo-whisper medium --executar
```

```
18 ligacoes desde 2026-09-24
  [!] ligacao 8871: positivo, interesse alto, 0 proximos passos
  [!] ligacao 8903: negativo, interesse medio, 1 proximos passos

12 resumidas | 2 merecem atencao | 0 falhas
```

---

## Decisões técnicas

**`tool_choice` em vez de "responda em JSON".** Forçar a chamada de
ferramenta com esquema é a diferença entre 95% e 100% de respostas válidas.
Ainda assim há um plano B que extrai JSON de bloco de código — falhar por
formatação desperdiça a chamada, que é a parte cara do processo.

**`condition_on_previous_text=False` no Whisper.** Sem isso o modelo entra em
loop de repetição em áudio com silêncio longo — começa a repetir a última
frase por minutos. A limpeza remove a repetição literal que ainda escapa.

**Whisper `small`, não `base` nem `medium`.** `base` erra nomes próprios
demais em português; `medium` triplica o tempo sem ganho proporcional em
áudio de telefonia (8 kHz, comprimido).

**Corta o meio, nunca o fim.** Ligação de uma hora ultrapassa o contexto
útil. O fechamento — próximos passos, objeções finais — é a parte mais
informativa do resumo, e é a que a maioria dos truncamentos joga fora.

**Tolerância de formato na desserialização.** Modelo de linguagem às vezes
devolve string onde o esquema pede lista. Normalizar evita que uma variação
derrube o processamento de um lote inteiro.

**Uma ligação que falha não para o lote.** Áudio corrompido acontece; o robô
registra e segue.

---

## Testes

```bash
pytest -q
```

39 testes, sem carregar o Whisper nem chamar a API. Um dublê do SDK verifica
que o `tool_choice` está sendo forçado e que a instrução proíbe inferir
intenção; os da transcrição cobrem repetição do Whisper, hesitação e o corte
que preserva o fechamento.

## Licença

MIT.
