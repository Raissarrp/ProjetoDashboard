"""
=====================================================================================
ETL - Coleta de Dados Financeiros de Empresas do Ibovespa (yfinance)
=====================================================================================

OBJETIVO
--------
Este script é responsável SOMENTE pela etapa de coleta e ETL (Extract, Transform,
Load). Ele NÃO calcula indicadores fundamentalistas (P/L, P/VP, ROE, ROA,
Dividend Yield, Margem Líquida, Crescimento de Receita) — esse cálculo é feito
no Power BI através de medidas DAX, usando os dados brutos que este script exporta.

O script gera um único arquivo Excel (.xlsx) com as seguintes abas, prontas para
serem importadas no Power BI (Obter Dados > Excel):

    1. Empresas             -> tabela dimensão (Ticker, Nome, Setor, Indústria)
    2. Precos_Diarios       -> série histórica diária (OHLCV) dos últimos 3 anos
    3. Demonstrativos_Anuais-> dados brutos de resultado e balanço por ano
    4. Dividendos           -> histórico bruto de proventos pagos (para o cálculo de DY)

REQUISITOS (rodar em um ambiente COM internet):
    pip install yfinance pandas openpyxl

COMO RODAR:
    python coleta_etl_ibovespa.py

SAÍDA:
    dados_ibovespa_bruto.xlsx (na mesma pasta do script)

=====================================================================================
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

# -------------------------------------------------------------------------------------
# 1. CONFIGURAÇÃO — 5 empresas do Ibovespa escolhidas (setores distintos, alta liquidez)
# -------------------------------------------------------------------------------------
TICKERS = {
    "PETR4.SA": "Petróleo Brasileiro S.A. - Petrobras",
    "VALE3.SA": "Vale S.A.",
    "ITUB4.SA": "Itaú Unibanco Holding S.A.",
    "BBDC4.SA": "Banco Bradesco S.A.",
    "ABEV3.SA": "Ambev S.A.",
}

ANOS_HISTORICO = 3
DATA_FIM = datetime.today()
DATA_INICIO = DATA_FIM - timedelta(days=365 * ANOS_HISTORICO)

ARQUIVO_SAIDA = "dados_ibovespa_bruto.xlsx"


def buscar_precos_diarios(ticker: str) -> pd.DataFrame:
    """Coleta o histórico diário de preços (OHLCV) dos últimos 3 anos."""
    ativo = yf.Ticker(ticker)
    hist = ativo.history(start=DATA_INICIO, end=DATA_FIM, interval="1d")

    if hist.empty:
        print(f"[AVISO] Nenhum dado de preço encontrado para {ticker}")
        return pd.DataFrame()

    hist = hist.reset_index()
    hist["Ticker"] = ticker
    hist = hist.rename(
        columns={
            "Date": "Data",
            "Open": "Abertura",
            "High": "Maxima",
            "Low": "Minima",
            "Close": "Fechamento",
            "Volume": "Volume",
        }
    )
    # Remove timezone (o Power BI não lida bem com datas com fuso horário)
    hist["Data"] = pd.to_datetime(hist["Data"]).dt.tz_localize(None)

    return hist[["Ticker", "Data", "Abertura", "Maxima", "Minima", "Fechamento", "Volume"]]


def buscar_demonstrativos_anuais(ticker: str) -> pd.DataFrame:
    """
    Coleta dados brutos de resultado e balanço patrimonial (últimos anos fiscais
    disponíveis na API do Yahoo Finance — normalmente 4 anos).

    Linhas coletadas (todas em valores absolutos, moeda original — BRL):
        - Receita Total (Total Revenue)
        - Lucro Líquido (Net Income)
        - Patrimônio Líquido (Total Equity)
        - Ativo Total (Total Assets)
        - Quantidade de Ações em Circulação (Shares Outstanding) — snapshot atual,
          usado como aproximação para todos os anos (limitação a ser citada na
          metodologia do artigo).
    """
    ativo = yf.Ticker(ticker)

    # --- Demonstração de resultados (anual) ---
    dre = ativo.financials  # linhas = contas, colunas = anos (mais recente primeiro)
    # --- Balanço patrimonial (anual) ---
    bp = ativo.balance_sheet

    if dre is None or dre.empty or bp is None or bp.empty:
        print(f"[AVISO] Demonstrativos financeiros não encontrados para {ticker}")
        return pd.DataFrame()

    def pegar_linha(df, nomes_possiveis):
        """Tenta várias grafias possíveis do nome da conta (a API do Yahoo muda com o tempo)."""
        for nome in nomes_possiveis:
            if nome in df.index:
                return df.loc[nome]
        return pd.Series(dtype="float64")

    receita = pegar_linha(dre, ["Total Revenue", "TotalRevenue"])
    lucro_liquido = pegar_linha(dre, ["Net Income", "NetIncome", "Net Income Common Stockholders"])
    patrimonio_liquido = pegar_linha(
        bp, ["Total Stockholder Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"]
    )
    ativo_total = pegar_linha(bp, ["Total Assets", "TotalAssets"])

    anos = sorted(set(receita.index.tolist() + lucro_liquido.index.tolist()))

    acoes_em_circulacao = ativo.info.get("sharesOutstanding", None)

    linhas = []
    for ano_col in anos:
        ano = pd.to_datetime(ano_col).year
        linhas.append(
            {
                "Ticker": ticker,
                "Ano": ano,
                "Receita": receita.get(ano_col, None),
                "LucroLiquido": lucro_liquido.get(ano_col, None),
                "PatrimonioLiquido": patrimonio_liquido.get(ano_col, None),
                "AtivoTotal": ativo_total.get(ano_col, None),
                "AcoesEmCirculacao": acoes_em_circulacao,
            }
        )

    df_final = pd.DataFrame(linhas).sort_values(["Ticker", "Ano"])
    return df_final


def buscar_dividendos(ticker: str) -> pd.DataFrame:
    """Coleta o histórico bruto de dividendos/JCP pagos (para cálculo do Dividend Yield no DAX)."""
    ativo = yf.Ticker(ticker)
    divs = ativo.dividends

    if divs.empty:
        print(f"[AVISO] Nenhum dividendo encontrado para {ticker}")
        return pd.DataFrame()

    divs = divs.reset_index()
    divs.columns = ["Data", "ValorDividendo"]
    divs["Ticker"] = ticker
    divs["Data"] = pd.to_datetime(divs["Data"]).dt.tz_localize(None)

    # Mantém apenas os dividendos dentro da janela de 3 anos analisada
    divs = divs[divs["Data"] >= DATA_INICIO]

    return divs[["Ticker", "Data", "ValorDividendo"]]


def montar_tabela_empresas() -> pd.DataFrame:
    """Tabela dimensão com metadados das empresas (setor, indústria, nome completo)."""
    linhas = []
    for ticker, nome in TICKERS.items():
        info = yf.Ticker(ticker).info
        linhas.append(
            {
                "Ticker": ticker,
                "Nome": nome,
                "Setor": info.get("sector", "N/D"),
                "Industria": info.get("industry", "N/D"),
            }
        )
    return pd.DataFrame(linhas)


def main():
    print("Iniciando coleta de dados (ETL)...\n")

    df_empresas = montar_tabela_empresas()

    lista_precos = []
    lista_demonstrativos = []
    lista_dividendos = []

    for ticker in TICKERS:
        print(f"-> Coletando {ticker} ...")

        precos = buscar_precos_diarios(ticker)
        if not precos.empty:
            lista_precos.append(precos)

        demo = buscar_demonstrativos_anuais(ticker)
        if not demo.empty:
            lista_demonstrativos.append(demo)

        divs = buscar_dividendos(ticker)
        if not divs.empty:
            lista_dividendos.append(divs)

    df_precos = pd.concat(lista_precos, ignore_index=True) if lista_precos else pd.DataFrame()
    df_demonstrativos = (
        pd.concat(lista_demonstrativos, ignore_index=True) if lista_demonstrativos else pd.DataFrame()
    )
    df_dividendos = pd.concat(lista_dividendos, ignore_index=True) if lista_dividendos else pd.DataFrame()

    print("\nSalvando arquivo Excel estruturado...")
    with pd.ExcelWriter(ARQUIVO_SAIDA, engine="openpyxl") as writer:
        df_empresas.to_excel(writer, sheet_name="Empresas", index=False)
        df_precos.to_excel(writer, sheet_name="Precos_Diarios", index=False)
        df_demonstrativos.to_excel(writer, sheet_name="Demonstrativos_Anuais", index=False)
        df_dividendos.to_excel(writer, sheet_name="Dividendos", index=False)

    print(f"\nConcluído! Arquivo gerado: {ARQUIVO_SAIDA}")
    print("\nResumo da coleta:")
    print(f"  Empresas:              {len(df_empresas)} linhas")
    print(f"  Preços diários:        {len(df_precos)} linhas")
    print(f"  Demonstrativos anuais: {len(df_demonstrativos)} linhas")
    print(f"  Dividendos:            {len(df_dividendos)} linhas")
    print("\nEste arquivo NÃO contém indicadores calculados (P/L, ROE, etc.).")
    print("Os indicadores devem ser calculados no Power BI via medidas DAX,")
    print("conforme o guia 'guia_powerbi_dax.md'.")


if __name__ == "__main__":
    main()