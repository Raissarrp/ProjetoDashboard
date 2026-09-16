import os
import math
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


# ============================================================
# CONFIGURAÇÃO
# ============================================================

load_dotenv()

from indicadores import (
    calcular_roe,
    calcular_roa,
    calcular_margem_liquida,
    calcular_crescimento_receita,
    calcular_crescimento_lucro,
    calcular_dividend_yield,
    calcular_payout,
    calcular_retorno,
    calcular_volatilidade,
    calcular_drawdown
)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5439")
DB_NAME = os.getenv("DB_NAME", "ibovespa_dashboard")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)


EMPRESAS = {
    "PETR4": {
        "ticker_yahoo": "PETR4.SA",
        "nome": "Petrobras",
        "setor": "Petróleo, Gás e Biocombustíveis",
        "subsetor": "Exploração, Refino e Distribuição"
    },
    "VALE3": {
        "ticker_yahoo": "VALE3.SA",
        "nome": "Vale",
        "setor": "Materiais Básicos",
        "subsetor": "Mineração"
    },
    "ITUB4": {
        "ticker_yahoo": "ITUB4.SA",
        "nome": "Itaú Unibanco",
        "setor": "Financeiro",
        "subsetor": "Bancos"
    },
    "WEGE3": {
        "ticker_yahoo": "WEGE3.SA",
        "nome": "WEG",
        "setor": "Bens Industriais",
        "subsetor": "Máquinas e Equipamentos"
    },
    "ABEV3": {
        "ticker_yahoo": "ABEV3.SA",
        "nome": "Ambev",
        "setor": "Consumo não Cíclico",
        "subsetor": "Bebidas"
    }
}


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def limpar_valor(valor):
    """
    Converte valores do pandas/numpy para tipos compatíveis
    com PostgreSQL.
    """
    if pd.isna(valor):
        return None

    try:
        valor = float(valor)

        if math.isnan(valor) or math.isinf(valor):
            return None

        return valor

    except (ValueError, TypeError):
        return None


def conectar_banco():
    """
    Testa a conexão com PostgreSQL.
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    print("✓ Conexão com PostgreSQL realizada.")


# ============================================================
# EMPRESAS
# ============================================================

def cadastrar_empresas():
    """
    Insere as empresas caso ainda não existam.
    """

    sql = text("""
        INSERT INTO empresa (
            ticker,
            nome_empresa,
            setor,
            subsetor
        )
        VALUES (
            :ticker,
            :nome,
            :setor,
            :subsetor
        )
        ON CONFLICT (ticker)
        DO UPDATE SET
            nome_empresa = EXCLUDED.nome_empresa,
            setor = EXCLUDED.setor,
            subsetor = EXCLUDED.subsetor
    """)

    with engine.begin() as conn:

        for ticker, dados in EMPRESAS.items():

            conn.execute(
                sql,
                {
                    "ticker": ticker,
                    "nome": dados["nome"],
                    "setor": dados["setor"],
                    "subsetor": dados["subsetor"]
                }
            )

    print("✓ Empresas cadastradas.")


def buscar_id_empresa(ticker):
    """
    Retorna o ID da empresa no PostgreSQL.
    """

    sql = text("""
        SELECT id_empresa
        FROM empresa
        WHERE ticker = :ticker
    """)

    with engine.connect() as conn:

        resultado = conn.execute(
            sql,
            {"ticker": ticker}
        ).fetchone()

    if resultado is None:
        raise Exception(f"Empresa {ticker} não encontrada.")

    return resultado[0]


# ============================================================
# COTAÇÕES
# ============================================================

def coletar_precos(ticker, ticker_yahoo, id_empresa):
    """
    Busca aproximadamente 5 anos de preços diários.
    """

    print(f"\nBuscando preços: {ticker}")

    dados = yf.download(
        ticker_yahoo,
        period="5y",
        interval="1d",
        auto_adjust=False,
        progress=False
    )

    if dados.empty:
        print(f"⚠ Nenhum preço encontrado para {ticker}")
        return 0

    # Algumas versões do yfinance retornam MultiIndex
    if isinstance(dados.columns, pd.MultiIndex):
        dados.columns = dados.columns.get_level_values(0)

    dados = dados.reset_index()

    dados["Date"] = pd.to_datetime(
        dados["Date"]
    ).dt.date

    registros = []

    for _, linha in dados.iterrows():

        registro = {
            "id_empresa": id_empresa,
            "data": linha["Date"],
            "preco_abertura": limpar_valor(linha.get("Open")),
            "preco_maximo": limpar_valor(linha.get("High")),
            "preco_minimo": limpar_valor(linha.get("Low")),
            "preco_fechamento": limpar_valor(linha.get("Close")),
            "preco_ajustado": limpar_valor(linha.get("Adj Close")),
            "volume": (
                int(linha["Volume"])
                if not pd.isna(linha.get("Volume"))
                else None
            ),
            "fonte": "Yahoo Finance"
        }

        registros.append(registro)

    sql = text("""
        INSERT INTO preco_acao (
            id_empresa,
            data,
            preco_abertura,
            preco_maximo,
            preco_minimo,
            preco_fechamento,
            preco_ajustado,
            volume,
            fonte
        )
        VALUES (
            :id_empresa,
            :data,
            :preco_abertura,
            :preco_maximo,
            :preco_minimo,
            :preco_fechamento,
            :preco_ajustado,
            :volume,
            :fonte
        )
        ON CONFLICT (id_empresa, data)
        DO UPDATE SET
            preco_abertura = EXCLUDED.preco_abertura,
            preco_maximo = EXCLUDED.preco_maximo,
            preco_minimo = EXCLUDED.preco_minimo,
            preco_fechamento = EXCLUDED.preco_fechamento,
            preco_ajustado = EXCLUDED.preco_ajustado,
            volume = EXCLUDED.volume,
            fonte = EXCLUDED.fonte,
            data_coleta = CURRENT_TIMESTAMP
    """)

    with engine.begin() as conn:

        for registro in registros:
            conn.execute(sql, registro)

    print(f"✓ {len(registros)} cotações carregadas.")

    return len(registros)


# ============================================================
# DIVIDENDOS
# ============================================================

def coletar_dividendos(ticker, ticker_yahoo, id_empresa):


    print(f"Buscando dividendos: {ticker}")

    ativo = yf.Ticker(ticker_yahoo)

    dividendos = ativo.dividends

    if dividendos is None or dividendos.empty:
        print(f"⚠ Nenhum dividendo encontrado para {ticker}")
        return 0
#
    datas = pd.to_datetime(dividendos.index)

    if datas.tz is not None:
        datas = datas.tz_localize(None)

    dividendos.index = datas

    # Data limite: aproximadamente 3 anos
    data_limite = pd.Timestamp.today().normalize() - pd.DateOffset(years=3)

    dividendos = dividendos[
        dividendos.index >= data_limite
    ]

    if dividendos.empty:
        print(f"⚠ Nenhum dividendo nos últimos 3 anos para {ticker}")
        return 0

    # ========================================================
    # PREPARAÇÃO DOS REGISTROS
    # ========================================================

    registros = []

    for data, valor in dividendos.items():

        valor_limpo = limpar_valor(valor)

        if valor_limpo is None:
            continue

        registros.append({
            "id_empresa": id_empresa,
            "data_pagamento": data.date(),
            "data_ex": data.date(),
            "valor_por_acao": valor_limpo,
            "tipo": "DIVIDENDO",
            "fonte": "Yahoo Finance",
            "url_fonte": "https://finance.yahoo.com/"
        })

    # ========================================================
    # INSERÇÃO NO POSTGRESQL
    # ========================================================

    sql = text("""
        INSERT INTO dividendos (
            id_empresa,
            data_pagamento,
            data_ex,
            valor_por_acao,
            tipo,
            fonte,
            url_fonte
        )
        VALUES (
            :id_empresa,
            :data_pagamento,
            :data_ex,
            :valor_por_acao,
            :tipo,
            :fonte,
            :url_fonte
        )
        ON CONFLICT (id_empresa, data_ex, valor_por_acao, tipo)
        DO NOTHING
    """)

    inseridos = 0

    with engine.begin() as conn:

        for registro in registros:

            resultado = conn.execute(sql, registro)

            if resultado.rowcount > 0:
                inseridos += 1

    print(f"✓ {inseridos} dividendos inseridos.")

    return inseridos

# ============================================================
# DADOS FINANCEIROS
# ============================================================

def coletar_financeiro(ticker, ticker_yahoo, id_empresa):
    """
    Busca dados financeiros anuais disponíveis no Yahoo Finance.

    Nesta primeira versão vamos trabalhar apenas com:
    - Receita líquida
    - Lucro líquido
    - Ativo total
    - Patrimônio líquido
    """

    print(f"Buscando dados financeiros: {ticker}")

    ativo = yf.Ticker(ticker_yahoo)

    income = ativo.income_stmt
    balance = ativo.balance_sheet

    if income is None or income.empty:
        print(f"⚠ DRE não encontrada para {ticker}")
        return 0

    registros = []

    periodos = income.columns

    for periodo in periodos:

        periodo_coluna = periodo
        periodo = pd.Timestamp(periodo_coluna).date()

        receita = None
        lucro = None
        ativo_total = None
        patrimonio = None
        ebitda = None
        divida_bruta = None
        caixa = None

        # Receita
        if "Total Revenue" in income.index:
            receita = limpar_valor(
                income.loc["Total Revenue", periodo_coluna]
            )

        # Lucro líquido
        if "Net Income" in income.index:
            lucro = limpar_valor(
                income.loc["Net Income", periodo_coluna]
            )

        for nome_ebitda in ("EBITDA", "Normalized EBITDA"):
            if nome_ebitda in income.index:
                ebitda = limpar_valor(
                    income.loc[nome_ebitda, periodo_coluna]
                )
                if ebitda is not None:
                    break

        # Ativo
        if (
            balance is not None
            and not balance.empty
            and "Total Assets" in balance.index
            and periodo_coluna in balance.columns
        ):
            ativo_total = limpar_valor(
                balance.loc["Total Assets", periodo_coluna]
            )

        # Patrimônio
        if (
            balance is not None
            and not balance.empty
            and "Stockholders Equity" in balance.index
            and periodo_coluna in balance.columns
        ):
            patrimonio = limpar_valor(
                balance.loc["Stockholders Equity", periodo_coluna]
            )

        if (
            balance is not None
            and not balance.empty
            and "Total Debt" in balance.index
            and periodo_coluna in balance.columns
        ):
            divida_bruta = limpar_valor(
                balance.loc["Total Debt", periodo_coluna]
            )

        for nome_caixa in (
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents"
        ):
            if (
                balance is not None
                and not balance.empty
                and nome_caixa in balance.index
                and periodo_coluna in balance.columns
            ):
                caixa = limpar_valor(
                    balance.loc[nome_caixa, periodo_coluna]
                )
                if caixa is not None:
                    break

        registros.append({
            "id_empresa": id_empresa,
            "periodo": periodo,
            "tipo_periodo": "ANUAL",
            "receita_liquida": receita,
            "lucro_liquido": lucro,
            "ativo_total": ativo_total,
            "passivo_total": None,
            "patrimonio_liquido": patrimonio,
            "ebit": None,
            "ebitda": ebitda,
            "divida_bruta": divida_bruta,
            "caixa": caixa,
            "fonte": "Yahoo Finance",
            "url_fonte": "https://finance.yahoo.com/"
        })

    sql = text("""
        INSERT INTO demonstrativo (
            id_empresa,
            periodo,
            tipo_periodo,
            receita_liquida,
            lucro_liquido,
            ativo_total,
            passivo_total,
            patrimonio_liquido,
            ebit,
            ebitda,
            divida_bruta,
            caixa,
            fonte,
            url_fonte
        )
        VALUES (
            :id_empresa,
            :periodo,
            :tipo_periodo,
            :receita_liquida,
            :lucro_liquido,
            :ativo_total,
            :passivo_total,
            :patrimonio_liquido,
            :ebit,
            :ebitda,
            :divida_bruta,
            :caixa,
            :fonte,
            :url_fonte
        )
        ON CONFLICT (id_empresa, periodo, tipo_periodo)
        DO UPDATE SET
            receita_liquida = EXCLUDED.receita_liquida,
            lucro_liquido = EXCLUDED.lucro_liquido,
            ativo_total = EXCLUDED.ativo_total,
            patrimonio_liquido = EXCLUDED.patrimonio_liquido,
            ebitda = EXCLUDED.ebitda,
            divida_bruta = EXCLUDED.divida_bruta,
            caixa = EXCLUDED.caixa,
            fonte = EXCLUDED.fonte,
            url_fonte = EXCLUDED.url_fonte,
            data_coleta = CURRENT_TIMESTAMP
    """)

    with engine.begin() as conn:

        for registro in registros:
            conn.execute(sql, registro)

    print(f"✓ {len(registros)} períodos financeiros carregados.")

    return len(registros)


# ============================================================
# INDICADORES
# ============================================================

def calcular_indicadores(ticker, id_empresa):
    """
    Calcula os indicadores básicos definidos no guia.

    Indicadores:
    - ROE
    - ROA
    - Margem Líquida
    - Crescimento de Receita
    - Dividend Yield
    """

    print(f"Calculando indicadores: {ticker}")

    sql = text("""
        SELECT
            periodo,
            receita_liquida,
            lucro_liquido,
            ativo_total,
            patrimonio_liquido
            , ebitda
            , divida_bruta
            , caixa
        FROM demonstrativo
        WHERE id_empresa = :id_empresa
          AND tipo_periodo = 'ANUAL'
        ORDER BY periodo
    """)

    with engine.connect() as conn:

        df = pd.read_sql(
            sql,
            conn,
            params={"id_empresa": id_empresa}
        )

    if df.empty:
        print(f"⚠ Sem dados financeiros para {ticker}")
        return 0

    colunas_financeiras = [
        "receita_liquida",
        "lucro_liquido",
        "ativo_total",
        "patrimonio_liquido"
    ]
    df = df.dropna(subset=colunas_financeiras, how="all")

    if df.empty:
        print(f"⚠ Sem dados financeiros válidos para {ticker}")
        return 0

    with engine.connect() as conn:
        ativo = yf.Ticker(EMPRESAS[ticker]["ticker_yahoo"])
        balance = ativo.balance_sheet
        dividendos_df = pd.read_sql(
            text("""
                SELECT EXTRACT(YEAR FROM data_pagamento)::int AS ano,
                       SUM(valor_por_acao) AS dividendos_por_acao
                FROM dividendos
                  WHERE id_empresa = :id_empresa
                    AND data_pagamento IS NOT NULL
                GROUP BY EXTRACT(YEAR FROM data_pagamento)
            """),
            conn,
            params={"id_empresa": id_empresa}
        )
        precos_df = pd.read_sql(
            text("""
                SELECT data, preco_fechamento
                FROM preco_acao
                WHERE id_empresa = :id_empresa
                ORDER BY data
            """),
            conn,
            params={"id_empresa": id_empresa}
        )

    dividendos_por_ano = {
        int(linha["ano"]): linha["dividendos_por_acao"]
        for _, linha in dividendos_df.iterrows()
        if pd.notna(linha["ano"])
    }
    precos_por_ano = {}
    precos_historicos = precos_df.copy()
    precos_historicos["data"] = pd.to_datetime(precos_historicos["data"])
    precos_historicos = precos_historicos.dropna(
        subset=["preco_fechamento"]
    ).sort_values("data")

    for _, linha in precos_df.iterrows():
        if pd.notna(linha["preco_fechamento"]):
            precos_por_ano[linha["data"].year] = linha["preco_fechamento"]

    acoes_por_ano = {}
    if balance is not None and not balance.empty:
        if "Ordinary Shares Number" in balance.index:
            for periodo in balance.columns:
                valor = limpar_valor(
                    balance.loc["Ordinary Shares Number", periodo]
                )
                if valor is not None:
                    acoes_por_ano[pd.Timestamp(periodo).year] = valor

    registros = []
    receita_anterior = None
    lucro_anterior = None

    for _, linha in df.iterrows():

        receita = linha["receita_liquida"]
        lucro = linha["lucro_liquido"]
        ativo = linha["ativo_total"]
        patrimonio = linha["patrimonio_liquido"]

        ano = linha["periodo"].year
        dividendos_por_acao = dividendos_por_ano.get(ano)
        preco_acao = precos_por_ano.get(ano)
        acoes = acoes_por_ano.get(ano)

        roe = calcular_roe(lucro, patrimonio)
        roa = calcular_roa(lucro, ativo)
        margem = calcular_margem_liquida(lucro, receita)
        crescimento_receita = calcular_crescimento_receita(
            receita,
            receita_anterior
        )
        crescimento_lucro = calcular_crescimento_lucro(
            lucro,
            lucro_anterior
        )
        dividend_yield = calcular_dividend_yield(
            dividendos_por_acao,
            preco_acao
        )
        lucro_por_acao = (
            lucro / acoes
            if pd.notna(lucro)
            and acoes is not None
            and acoes != 0
            else None
        )
        valor_mercado = (
            preco_acao * acoes
            if preco_acao is not None and acoes is not None
            else None
        )
        pl = (
            valor_mercado / lucro
            if valor_mercado is not None
            and pd.notna(lucro)
            and lucro != 0
            else None
        )
        pvp = (
            valor_mercado / patrimonio
            if valor_mercado is not None
            and pd.notna(patrimonio)
            and patrimonio != 0
            else None
        )
        ev_ebitda = (
            (valor_mercado + linha["divida_bruta"] - linha["caixa"])
            / linha["ebitda"]
            if valor_mercado is not None
            and pd.notna(linha["divida_bruta"])
            and pd.notna(linha["caixa"])
            and pd.notna(linha["ebitda"])
            and linha["ebitda"] != 0
            else None
        )
        payout = calcular_payout(
            dividendos_por_acao,
            lucro_por_acao
        )

        precos_ate_periodo = precos_historicos[
            precos_historicos["data"] <= pd.Timestamp(linha["periodo"])
        ]["preco_fechamento"]
        preco_atual = (
            precos_ate_periodo.iloc[-1]
            if not precos_ate_periodo.empty
            else None
        )

        def preco_anterior(dias):
            if len(precos_ate_periodo) <= dias:
                return None
            return precos_ate_periodo.iloc[-dias - 1]

        retorno_1m = calcular_retorno(
            preco_atual,
            preco_anterior(21)
        )
        retorno_6m = calcular_retorno(
            preco_atual,
            preco_anterior(126)
        )
        retorno_12m = calcular_retorno(
            preco_atual,
            preco_anterior(252)
        )
        retorno_3y = calcular_retorno(
            preco_atual,
            preco_anterior(756)
        )
        volatilidade = calcular_volatilidade(precos_ate_periodo)
        drawdown = calcular_drawdown(precos_ate_periodo)

        if pd.notna(receita):
            receita_anterior = receita
        if pd.notna(lucro):
            lucro_anterior = lucro

        registros.append({
            "id_empresa": id_empresa,
            "periodo": linha["periodo"],
            "pl": limpar_valor(pl),
            "pvp": limpar_valor(pvp),
            "ev_ebitda": limpar_valor(ev_ebitda),
            "roe": limpar_valor(roe),
            "roa": limpar_valor(roa),
            "margem_liquida": limpar_valor(margem),
            "dividend_yield": limpar_valor(dividend_yield),
            "payout": limpar_valor(payout),
            "crescimento_receita": limpar_valor(crescimento_receita),
            "crescimento_lucro": limpar_valor(crescimento_lucro),
            "retorno_1m": limpar_valor(retorno_1m),
            "retorno_6m": limpar_valor(retorno_6m),
            "retorno_12m": limpar_valor(retorno_12m),
            "retorno_3y": limpar_valor(retorno_3y),
            "volatilidade": limpar_valor(volatilidade),
            "drawdown": limpar_valor(drawdown)
        })

    sql_insert = text("""
        INSERT INTO indicadores (
            id_empresa,
            periodo,
            pl,
            pvp,
            ev_ebitda,
            roe,
            roa,
            margem_liquida,
            dividend_yield,
            payout,
            crescimento_receita,
            crescimento_lucro,
            retorno_1m,
            retorno_6m,
            retorno_12m,
            retorno_3y,
            volatilidade,
            drawdown
        )
        VALUES (
            :id_empresa,
            :periodo,
            :pl,
            :pvp,
            :ev_ebitda,
            :roe,
            :roa,
            :margem_liquida,
            :dividend_yield,
            :payout,
            :crescimento_receita,
            :crescimento_lucro,
            :retorno_1m,
            :retorno_6m,
            :retorno_12m,
            :retorno_3y,
            :volatilidade,
            :drawdown
        )
        ON CONFLICT (id_empresa, periodo)
        DO UPDATE SET
            pl = EXCLUDED.pl,
            pvp = EXCLUDED.pvp,
            ev_ebitda = EXCLUDED.ev_ebitda,
            roe = EXCLUDED.roe,
            roa = EXCLUDED.roa,
            margem_liquida = EXCLUDED.margem_liquida,
            dividend_yield = EXCLUDED.dividend_yield,
            payout = EXCLUDED.payout,
            crescimento_receita = EXCLUDED.crescimento_receita,
            crescimento_lucro = EXCLUDED.crescimento_lucro,
            retorno_1m = EXCLUDED.retorno_1m,
            retorno_6m = EXCLUDED.retorno_6m,
            retorno_12m = EXCLUDED.retorno_12m,
            retorno_3y = EXCLUDED.retorno_3y,
            volatilidade = EXCLUDED.volatilidade,
            drawdown = EXCLUDED.drawdown,
            data_calculo = CURRENT_TIMESTAMP
    """)

    with engine.begin() as conn:

        conn.execute(
            text("""
                DELETE FROM indicadores
                WHERE id_empresa = :id_empresa
                  AND roe IS NULL
                  AND roa IS NULL
                  AND margem_liquida IS NULL
                  AND crescimento_receita IS NULL
            """),
            {"id_empresa": id_empresa}
        )

        for registro in registros:
            conn.execute(sql_insert, registro)

    print(f"✓ {len(registros)} registros de indicadores calculados.")

    return len(registros)


# ============================================================
# PROCESSAMENTO DE UMA EMPRESA
# ============================================================

def processar_empresa(ticker):

    dados = EMPRESAS[ticker]

    ticker_yahoo = dados["ticker_yahoo"]

    print("\n" + "=" * 60)
    print(f"PROCESSANDO {ticker} - {dados['nome']}")
    print("=" * 60)

    id_empresa = buscar_id_empresa(ticker)

    precos = coletar_precos(
        ticker,
        ticker_yahoo,
        id_empresa
    )

    dividendos = coletar_dividendos(
        ticker,
        ticker_yahoo,
        id_empresa
    )

    financeiros = coletar_financeiro(
        ticker,
        ticker_yahoo,
        id_empresa
    )

    indicadores = calcular_indicadores(
        ticker,
        id_empresa
    )

    return {
        "ticker": ticker,
        "precos": precos,
        "dividendos": dividendos,
        "financeiros": financeiros,
        "indicadores": indicadores
    }


# ============================================================
# MAIN
# ============================================================

def main():

    inicio = datetime.now()

    print("\n")
    print("=" * 60)
    print("IBOVESPA DASHBOARD")
    print("ETL - Python -> PostgreSQL")
    print("=" * 60)

    try:

        conectar_banco()

        cadastrar_empresas()

        resultados = []

        for ticker in EMPRESAS:

            try:

                resultado = processar_empresa(ticker)

                resultados.append(resultado)

            except Exception as erro:

                print(
                    f"❌ Erro ao processar {ticker}: {erro}"
                )

        print("\n")
        print("=" * 60)
        print("RESUMO DA EXECUÇÃO")
        print("=" * 60)

        for resultado in resultados:

            print(
                f"""
{resultado['ticker']}
  Preços:       {resultado['precos']}
  Dividendos:   {resultado['dividendos']}
  Financeiros:  {resultado['financeiros']}
  Indicadores:  {resultado['indicadores']}
"""
            )

        fim = datetime.now()

        print("=" * 60)
        print(f"Início: {inicio}")
        print(f"Fim:    {fim}")
        print("=" * 60)

    except Exception as erro:

        print("\n❌ ERRO GERAL:")
        print(erro)


if __name__ == "__main__":
    main()
    
  