import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

TICKERS = {
    "PETR4.SA": "Petróleo Brasileiro S.A. - Petrobras",
    "VALE3.SA": "Vale S.A.",
    "ITUB4.SA": "Itaú Unibanco Holding S.A.",
    "BBDC4.SA": "Banco Bradesco S.A.",
    "ABEV3.SA": "Ambev S.A.",
}

ANOS_HISTORICO = 4
DATA_FIM = datetime.today()
DATA_INICIO = DATA_FIM - timedelta(days=365 * ANOS_HISTORICO)

ARQUIVO_SAIDA = "dados_ibovespa_bruto.xlsx"


def buscar_precos_diarios(ticker: str) -> pd.DataFrame:
    ativo = yf.Ticker(ticker)

    hist = ativo.history(start=DATA_INICIO, end=DATA_FIM, interval="1d", auto_adjust=False)

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
    hist["Data"] = pd.to_datetime(hist["Data"]).dt.tz_localize(None)

    return hist[["Ticker", "Data", "Abertura", "Maxima", "Minima", "Fechamento", "Volume"]]


def buscar_demonstrativos_anuais(ticker: str) -> pd.DataFrame:
    ativo = yf.Ticker(ticker)

    dre = ativo.financials
    bp = ativo.balance_sheet

    if dre is None or dre.empty or bp is None or bp.empty:
        print(f"[AVISO] Demonstrativos financeiros não encontrados para {ticker}")
        return pd.DataFrame()

    def pegar_linha(df, nomes_possiveis):
        for nome in nomes_possiveis:
            if nome in df.index:
                return df.loc[nome]
        return pd.Series(dtype="float64")

    receita = pegar_linha(dre, ["Total Revenue", "TotalRevenue", "Operating Revenue"])
    lucro_liquido = pegar_linha(dre, ["Net Income", "NetIncome", "Net Income Common Stockholders"])
    patrimonio_liquido = pegar_linha(
        bp, ["Total Stockholder Equity", "Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"]
    )
    ativo_total = pegar_linha(bp, ["Total Assets", "TotalAssets"])

    acoes_por_ano = pegar_linha(
        bp,
        [
            "Ordinary Shares Number",
            "Share Issued",
            "ShareIssued",
            "OrdinarySharesNumber",
            "Common Stock Shares Outstanding",
            "Common Stock",
            "Capital Stock"
        ],
    )

    serie_historica_acoes = None
    if acoes_por_ano.empty:
        try:
            serie_historica_acoes = ativo.get_shares_full(start="2020-01-01")
        except Exception:
            serie_historica_acoes = None

    acoes_fallback = ativo.info.get("sharesOutstanding", None)

    ano_atual_corrido = datetime.today().year
    anos = [col for col in dre.columns if pd.to_datetime(col).year < ano_atual_corrido]

    linhas = []
    for ano_col in anos:
        ano = pd.to_datetime(ano_col).year
        acoes_ano = None

        if not acoes_por_ano.empty and ano_col in acoes_por_ano.index:
            acoes_ano = acoes_por_ano.get(ano_col)

        elif serie_historica_acoes is not None and not serie_historica_acoes.empty:
            dados_ano = serie_historica_acoes[serie_historica_acoes.index.year == ano]
            if not dados_ano.empty:
                acoes_ano = dados_ano.iloc[-1]

        if pd.isna(acoes_ano) or acoes_ano is None:
            acoes_ano = acoes_fallback

        if ticker in ["PETR4.SA", "PETR3.SA"] and acoes_ano and acoes_ano > 8_000_000_000:
            acoes_ano = acoes_ano / 2

        linhas.append(
            {
                "Ticker": ticker,
                "Ano": ano,
                "Receita": receita.get(ano_col, None),
                "LucroLiquido": lucro_liquido.get(ano_col, None),
                "PatrimonioLiquido": patrimonio_liquido.get(ano_col, None),
                "AtivoTotal": ativo_total.get(ano_col, None),
                "AcoesEmCirculacao": acoes_ano,
            }
        )

    df_final = pd.DataFrame(linhas).sort_values(["Ticker", "Ano"])
    return df_final

def buscar_dividendos(ticker: str) -> pd.DataFrame:
    ativo = yf.Ticker(ticker)
    divs = ativo.dividends

    if divs.empty:
        print(f"[AVISO] Nenhum dividendo encontrado para {ticker}")
        return pd.DataFrame()

    divs = divs.reset_index()
    divs.columns = ["Data", "ValorDividendo"]
    divs["Ticker"] = ticker

    divs["Data"] = pd.to_datetime(divs["Data"]).dt.tz_localize(None)

    data_corte = pd.to_datetime("2022-01-01")
    divs = divs[divs["Data"] >= data_corte]

    return divs[["Ticker", "Data", "ValorDividendo"]]


def montar_tabela_empresas() -> pd.DataFrame:
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
