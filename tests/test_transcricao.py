"""Testes da transcrição — o que dá para testar sem carregar o Whisper."""

from __future__ import annotations

from ligacao.transcricao import Transcricao, Trecho, limpar_para_resumo


def trecho(falante="Vendedor", inicio=0.0, fim=5.0, texto="ola") -> Trecho:
    return Trecho(falante, inicio, fim, texto)


class TestTrecho:
    def test_duracao(self):
        assert trecho(inicio=10.0, fim=25.5).duracao == 15.5

    def test_formato_com_carimbo(self):
        assert trecho(inicio=125.0, texto="bom dia").formatado() == (
            "[02:05] Vendedor: bom dia"
        )


class TestTranscricao:
    def _conversa(self) -> Transcricao:
        return Transcricao(
            trechos=[
                trecho("Vendedor", 0, 40, "apresentacao do servico"),
                trecho("Cliente", 40, 50, "entendi"),
                trecho("Vendedor", 50, 90, "detalhes do prazo"),
                trecho("Cliente", 90, 110, "vou avaliar com meu socio"),
            ],
            duracao=110,
        )

    def test_tempo_por_falante(self):
        tempos = self._conversa().tempo_por_falante()
        assert tempos["Vendedor"] == 80
        assert tempos["Cliente"] == 30

    def test_resumo_estrutural_mostra_a_proporcao(self):
        """Vendedor falando 73% do tempo e sintoma, nao estilo."""
        resumo = self._conversa().resumo_estrutural()
        assert "Vendedor: 73%" in resumo
        assert "Cliente: 27%" in resumo

    def test_contagem_de_palavras(self):
        assert self._conversa().palavras == 12

    def test_texto_intercala_os_falantes(self):
        linhas = self._conversa().texto.splitlines()
        assert linhas[0].startswith("[00:00] Vendedor")
        assert linhas[1].startswith("[00:40] Cliente")

    def test_transcricao_vazia_nao_divide_por_zero(self):
        assert "0.0 min" in Transcricao().resumo_estrutural()


class TestLimpeza:
    def test_remove_repeticao_literal(self):
        """O Whisper repete a ultima frase quando ha silencio longo."""
        texto = (
            "[00:00] Cliente: obrigado\n"
            "[00:05] Cliente: obrigado\n"
            "[00:10] Cliente: obrigado\n"
            "[00:15] Cliente: ate mais"
        )
        limpo = limpar_para_resumo(texto)
        assert limpo.count("obrigado") == 1
        assert "ate mais" in limpo

    def test_remove_hesitacao(self):
        limpo = limpar_para_resumo("[00:00] Cliente: eh, hum, entao o prazo")
        assert "hum" not in limpo
        assert "prazo" in limpo

    def test_texto_curto_passa_inteiro(self):
        texto = "[00:00] Cliente: bom dia"
        assert "bom dia" in limpar_para_resumo(texto)

    def test_corta_o_meio_e_preserva_o_fim(self):
        """O fechamento — proximos passos, objecoes finais — e o que importa."""
        comeco = "[00:00] Vendedor: INICIO " + "x " * 5000
        fim = "y " * 5000 + " FECHAMENTO combinado enviar proposta"
        limpo = limpar_para_resumo(comeco + fim, limite_caracteres=2000)

        assert len(limpo) < 2200
        assert "INICIO" in limpo
        assert "FECHAMENTO" in limpo
        assert "omitido por tamanho" in limpo

    def test_texto_vazio(self):
        assert limpar_para_resumo("") == ""
