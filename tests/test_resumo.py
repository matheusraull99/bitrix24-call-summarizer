"""Testes do resumo estruturado — sem chamar a API."""

from __future__ import annotations

import pytest

from ligacao.resumo import ESQUEMA, ResumoLigacao, extrair_json, resumir

COMPLETO = {
    "resumo": "Cliente pediu orcamento para reforma de 320 m2. Achou o prazo longo.",
    "assunto": "Reforma Ed. Aurora",
    "sentimento": "positivo",
    "interesse": "alto",
    "objecoes": ["prazo de 45 dias e longo demais"],
    "proximos_passos": ["enviar proposta ate sexta"],
    "prazo_citado": "45 dias uteis",
    "valor_citado": "R$ 85.000",
    "confianca": "alta",
}


class TestConstrucao:
    def test_json_completo(self):
        resumo = ResumoLigacao.do_json(COMPLETO)
        assert resumo.assunto == "Reforma Ed. Aurora"
        assert resumo.objecoes == ["prazo de 45 dias e longo demais"]
        assert resumo.confianca == "alta"

    def test_campos_ausentes_caem_no_padrao(self):
        resumo = ResumoLigacao.do_json({"resumo": "conversa curta"})
        assert resumo.sentimento == "neutro"
        assert resumo.interesse == "indefinido"
        assert resumo.objecoes == []

    def test_string_onde_o_esquema_pede_lista(self):
        """O modelo as vezes devolve string; um lote nao pode cair por isso."""
        resumo = ResumoLigacao.do_json({**COMPLETO, "objecoes": "preco alto"})
        assert resumo.objecoes == ["preco alto"]

    def test_lista_com_item_vazio_e_limpa(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "proximos_passos": ["", "  ", "ligar"]})
        assert resumo.proximos_passos == ["ligar"]

    def test_enum_invalido_cai_no_padrao(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "sentimento": "eufórico"})
        assert resumo.sentimento == "neutro"

    def test_enum_com_caixa_diferente(self):
        assert ResumoLigacao.do_json({**COMPLETO, "sentimento": "POSITIVO"}).sentimento == (
            "positivo"
        )


class TestSinalizacao:
    def test_com_proximo_passo_e_acionavel(self):
        assert ResumoLigacao.do_json(COMPLETO).acionavel

    def test_confianca_baixa_nao_e_acionavel(self):
        """Proximo passo inventado sobre transcricao ruim e pior que nenhum."""
        resumo = ResumoLigacao.do_json({**COMPLETO, "confianca": "baixa"})
        assert not resumo.acionavel

    def test_sem_proximo_passo_nao_e_acionavel(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "proximos_passos": []})
        assert not resumo.acionavel

    def test_interesse_alto_sem_proximo_passo_merece_atencao(self):
        """Oportunidade escapando: o gestor precisa ver."""
        resumo = ResumoLigacao.do_json({**COMPLETO, "proximos_passos": []})
        assert resumo.merece_atencao

    def test_sentimento_negativo_merece_atencao(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "sentimento": "negativo"})
        assert resumo.merece_atencao

    def test_ligacao_normal_nao_merece_atencao(self):
        assert not ResumoLigacao.do_json(COMPLETO).merece_atencao


class TestTimeline:
    def test_usa_bbcode_e_nao_markdown(self):
        texto = ResumoLigacao.do_json(COMPLETO).para_timeline()
        assert "[B]" in texto and "**" not in texto

    def test_lista_objecoes_e_proximos_passos(self):
        texto = ResumoLigacao.do_json(COMPLETO).para_timeline()
        assert "prazo de 45 dias" in texto
        assert "enviar proposta ate sexta" in texto

    def test_avisa_quando_nao_houve_proximo_passo(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "proximos_passos": []})
        assert "Nenhum proximo passo" in resumo.para_timeline()

    def test_mostra_a_confianca(self):
        texto = ResumoLigacao.do_json({**COMPLETO, "confianca": "baixa"}).para_timeline()
        assert "Confianca do resumo: baixa" in texto

    def test_omite_prazo_e_valor_quando_vazios(self):
        resumo = ResumoLigacao.do_json({**COMPLETO, "prazo_citado": "", "valor_citado": ""})
        texto = resumo.para_timeline()
        assert "Prazo citado" not in texto


class TestExtrairJson:
    def test_json_puro(self):
        assert extrair_json('{"resumo": "x"}') == {"resumo": "x"}

    def test_json_em_bloco_de_codigo(self):
        texto = 'Aqui esta:\n```json\n{"resumo": "x"}\n```'
        assert extrair_json(texto) == {"resumo": "x"}

    def test_json_com_texto_antes(self):
        assert extrair_json('Segue o resumo: {"resumo": "x"}') == {"resumo": "x"}

    def test_sem_json_levanta(self):
        with pytest.raises(ValueError, match="nenhum JSON"):
            extrair_json("nao consegui resumir esta ligacao")

    def test_lista_no_topo_nao_serve(self):
        with pytest.raises(ValueError):
            extrair_json("[1, 2, 3]")


class ClienteFalso:
    """Dublê do SDK da Anthropic."""

    def __init__(self, blocos):
        self._blocos = blocos
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        return type("Resposta", (), {"content": self._blocos})()


class BlocoFerramenta:
    type = "tool_use"

    def __init__(self, entrada):
        self.input = entrada


class BlocoTexto:
    type = "text"

    def __init__(self, texto):
        self.text = texto


class TestResumir:
    def test_le_o_bloco_de_ferramenta(self):
        cliente = ClienteFalso([BlocoFerramenta(COMPLETO)])
        resumo = resumir(cliente, "transcricao aqui")
        assert resumo.assunto == "Reforma Ed. Aurora"

    def test_forca_o_uso_da_ferramenta(self):
        """`tool_choice` e a diferenca entre 95% e 100% de respostas validas."""
        cliente = ClienteFalso([BlocoFerramenta(COMPLETO)])
        resumir(cliente, "x")
        chamada = cliente.chamadas[0]
        assert chamada["tool_choice"]["name"] == "registrar_resumo"
        assert chamada["tools"][0]["input_schema"] is ESQUEMA

    def test_plano_b_quando_o_modelo_responde_em_texto(self):
        cliente = ClienteFalso([BlocoTexto('```json\n{"resumo": "ok"}\n```')])
        assert resumir(cliente, "x").resumo == "ok"

    def test_contexto_entra_no_prompt(self):
        cliente = ClienteFalso([BlocoFerramenta(COMPLETO)])
        resumir(cliente, "transcricao", contexto="Negocio 1042 — Aurora")
        conteudo = cliente.chamadas[0]["messages"][0]["content"]
        assert "Aurora" in conteudo

    def test_instrucao_proibe_inferir_intencao(self):
        cliente = ClienteFalso([BlocoFerramenta(COMPLETO)])
        resumir(cliente, "x")
        assert "Nao infira" in cliente.chamadas[0]["system"]
