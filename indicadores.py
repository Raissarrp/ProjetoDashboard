def calcular_roe(lucro_liquido, patrimonio_liquido):
    if patrimonio_liquido is None or patrimonio_liquido == 0:
        return None

    return (lucro_liquido / patrimonio_liquido) * 100


def calcular_roa(lucro_liquido, ativo_total):
    if ativo_total is None or ativo_total == 0:
        return None

    return (lucro_liquido / ativo_total) * 100


def calcular_margem_liquida(lucro_liquido, receita_liquida):
    if receita_liquida is None or receita_liquida == 0:
        return None

    return (lucro_liquido / receita_liquida) * 100


def calcular_crescimento_receita(receita_atual, receita_anterior):
    if receita_anterior is None or receita_anterior == 0:
        return None

    return ((receita_atual / receita_anterior) - 1) * 100


def calcular_crescimento_lucro(lucro_atual, lucro_anterior):
    if lucro_anterior is None or lucro_anterior == 0:
        return None

    return ((lucro_atual / lucro_anterior) - 1) * 100


def calcular_retorno(preco_atual, preco_anterior):
    if preco_atual is None or preco_anterior is None or preco_anterior == 0:
        return None

    return ((preco_atual / preco_anterior) - 1) * 100


def calcular_volatilidade(precos, janela=252):
    retornos = precos.pct_change().dropna().tail(janela)
    if retornos.empty:
        return None

    return retornos.std() * (252 ** 0.5) * 100


def calcular_drawdown(precos):
    if precos.empty:
        return None

    maxima = precos.cummax()
    drawdowns = (precos / maxima) - 1
    return drawdowns.min() * 100


def calcular_dividend_yield(dividendos_por_acao, preco_acao):
    if (
        dividendos_por_acao is None
        or preco_acao is None
        or preco_acao == 0
    ):
        return None

    return (dividendos_por_acao / preco_acao) * 100


def calcular_payout(dividendos_por_acao, lpa):
    if (
        dividendos_por_acao is None
        or lpa is None
        or lpa == 0
    ):
        return None

    return (dividendos_por_acao / lpa) * 100