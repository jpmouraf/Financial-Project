import datetime
import math

import numpy as np
import pandas as pd
import yfinance as yf
from pypfopt import EfficientFrontier
from scipy.stats import linregress

# ── Ticker universe ───────────────────────────────────────────────────────────

TICKERS_DEFAULT = [
    "ABEV3", "ALPA4", "AMER3", "ASAI3", "AZUL4",
    "B3SA3", "BBAS3", "BBDC3", "BBDC4", "BBSE3",
    "BEEF3", "BPAC11", "BRAP4", "BRFS3", "BRKM5",
    "BRML3", "CASH3", "CCRO3", "CIEL3", "CMIG4",
    "CMIN3", "COGN3", "CPFE3", "CPLE6", "CRFB3",
    "CSAN3", "CSNA3", "CVCB3", "CYRE3", "DXCO3",
    "EGIE3", "ELET3", "ELET6", "EMBR3", "ENEV3",
    "ENGI11", "EQTL3", "EZTC3", "FLRY3", "GGBR4",
    "GOAU4", "GOLL4", "HAPV3", "HYPE3", "IGTI11",
    "IRBR3", "ITSA4", "ITUB4", "JBSS3", "KLBN11",
    "LREN3", "LWSA3", "MGLU3", "MRFG3", "MRVE3",
    "MULT3", "MYPK3", "NTCO3", "PCAR3", "PETR3",
    "PETR4", "PETZ3", "PRIO3", "QUAL3", "RADL3",
    "RAIL3", "RDOR3", "RENT3", "RRRP3", "SANB11",
    "SBSP3", "SLCE3", "SMFT3", "SMLS3", "SOMA3",
    "SUZB3", "TAEE11", "TIMS3", "TOTS3", "UGPA3",
    "USIM5", "VALE3", "VBBR3", "VIIA3", "VIVT3",
    "WEGE3", "YDUQ3",
]

TICKERS_SELECAO_INICIAL = ["VALE3", "PETR4", "ITUB4", "BBDC4", "WEGE3"]

SETORES: dict[str, list[str]] = {
    "Bancos":                  ["BBAS3", "BBDC3", "BBDC4", "BPAC11", "ITSA4", "ITUB4", "SANB11"],
    "Seguros":                 ["BBSE3", "IRBR3"],
    "Serviços Financeiros":    ["B3SA3", "CIEL3"],
    "Petróleo e Gás":          ["PETR3", "PETR4", "PRIO3", "RRRP3"],
    "Combustíveis":            ["CSAN3", "UGPA3", "VBBR3"],
    "Mineração":               ["BRAP4", "CMIN3", "VALE3"],
    "Siderurgia":              ["CSNA3", "GGBR4", "GOAU4", "USIM5"],
    "Energia Elétrica":        ["CMIG4", "CPFE3", "CPLE6", "EGIE3", "ELET3", "ELET6",
                                "ENEV3", "ENGI11", "EQTL3", "TAEE11"],
    "Saneamento":              ["SBSP3"],
    "Telecomunicações":        ["TIMS3", "VIVT3"],
    "Varejo":                  ["AMER3", "LREN3", "MGLU3", "NTCO3", "PETZ3", "SOMA3", "VIIA3"],
    "Supermercados":           ["ASAI3", "CRFB3", "PCAR3"],
    "Alimentação e Bebidas":   ["ABEV3", "BEEF3", "BRFS3", "JBSS3", "MRFG3"],
    "Saúde":                   ["FLRY3", "HAPV3", "QUAL3", "RDOR3"],
    "Farmácias":               ["HYPE3", "RADL3"],
    "Construção Civil":        ["CYRE3", "EZTC3", "MRVE3"],
    "Logística e Transporte":  ["AZUL4", "CCRO3", "GOLL4", "RAIL3", "RENT3"],
    "Aeroespacial":            ["EMBR3"],
    "Educação":                ["COGN3", "YDUQ3"],
    "Papel e Celulose":        ["DXCO3", "KLBN11", "SUZB3"],
    "Petroquímica":            ["BRKM5"],
    "Tecnologia":              ["LWSA3", "TOTS3"],
    "Shopping e Imóveis":      ["BRML3", "IGTI11", "MULT3", "SMFT3", "SMLS3"],
    "Máquinas e Equipamentos": ["MYPK3", "WEGE3"],
    "Agronegócio":             ["SLCE3"],
    "Outros":                  ["ALPA4", "CASH3", "CVCB3"],
}

# ── Constants ─────────────────────────────────────────────────────────────────

IBOV_TICKER = "^BVSP"
PERIODOS    = {"1A": "1y", "2A": "2y", "5A": "5y"}
DIAS_UTEIS  = 252
RF_DEFAULT  = 10.75

GLOSSARIO = [
    ("Fronteira Eficiente",
     "Conjunto de portfólios que oferecem o maior retorno possível para cada nível de risco "
     "(volatilidade). Portfólios abaixo da curva são ineficientes."),
    ("Max-Sharpe (portfólio tangente)",
     "Portfólio que maximiza o Índice de Sharpe: SR = (Ret − Rƒ) / Vol. "
     "Ponto de tangência entre a CML e a fronteira eficiente."),
    ("Min-Vol (variância mínima)",
     "Portfólio com a menor volatilidade possível, independentemente do retorno. "
     "Vértice esquerdo da fronteira eficiente."),
    ("1/N (benchmark ingênuo)",
     "Alocação uniforme: peso igual para todos os ativos. "
     "Sem otimização — baseline para avaliar ganho dos portfólios otimizados."),
    ("CML — Capital Market Line",
     "Reta de (vol=0, Rƒ) ao portfólio tangente. "
     "Inclinação = Índice de Sharpe do portfólio tangente."),
    ("Beta (β)",
     "Sensibilidade ao mercado. β > 1 → amplifica movimentos; β < 1 → defensivo."),
    ("Alpha (α)",
     "Retorno anualizado acima do esperado pelo CAPM (Jensen's Alpha)."),
    ("R²",
     "Fração da variância do ativo explicada pelo Ibovespa."),
    ("Índice de Sharpe (SR)",
     "SR = (Retorno − Rƒ) / Volatilidade. Quanto maior, melhor a relação risco/retorno."),
    ("Volatilidade (σ)",
     "Desvio-padrão anualizado dos retornos. Calculada como √(wᵀΣw)."),
    ("Taxa livre de risco (Rƒ)",
     "Proxy da SELIC no Brasil. Origem da CML e denominador do excesso de retorno."),
]

# ── Solver ────────────────────────────────────────────────────────────────────

# OSQP with high iter limit + polishing; falls back to SCS for ill-conditioned problems.
_OSQP_OPTS = {"max_iter": 50_000, "eps_abs": 1e-6, "eps_rel": 1e-6, "polish": True}


def _make_ef(mu: pd.Series, S: pd.DataFrame) -> EfficientFrontier:
    try:
        return EfficientFrontier(mu, S, weight_bounds=(0, 1), solver_options=_OSQP_OPTS)
    except Exception:
        return EfficientFrontier(mu, S, weight_bounds=(0, 1), solver="SCS")


# ── Data fetching ─────────────────────────────────────────────────────────────

def _to_log_returns(closes: pd.DataFrame) -> pd.DataFrame:
    log_ret = np.log(closes / closes.shift(1)).iloc[1:].dropna()
    log_ret.columns = [c.replace(".SA", "") for c in log_ret.columns]
    return log_ret


def _download_closes(yf_tickers: list[str], **kwargs) -> pd.DataFrame:
    raw    = yf.download(yf_tickers, auto_adjust=True, progress=False, **kwargs)
    closes = (raw["Close"] if isinstance(raw.columns, pd.MultiIndex)
              else raw[["Close"]].rename(columns={"Close": yf_tickers[0]}))
    closes = closes.dropna(axis=1, how="all")
    if closes.empty:
        raise ValueError("Nenhum dado disponível para os tickers fornecidos.")
    return closes


def fetch_prices(tickers: list[str], period: str = "5y") -> pd.DataFrame:
    yf_tickers = [t.upper().replace(".SA", "") + ".SA" for t in tickers]
    return _to_log_returns(_download_closes(yf_tickers, period=period))


def fetch_prices_range(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    yf_tickers = [t.upper().replace(".SA", "") + ".SA" for t in tickers]
    return _to_log_returns(_download_closes(yf_tickers, start=start, end=end))


def _fetch_ibov_log_returns(**kwargs) -> pd.Series:
    raw = yf.download(IBOV_TICKER, auto_adjust=True, progress=False, **kwargs)
    if raw.empty:
        raise ValueError(f"Não foi possível buscar dados do Ibovespa ({IBOV_TICKER}).")
    closes = raw["Close"].squeeze()
    return np.log(closes / closes.shift(1)).iloc[1:].dropna().rename("IBOV")


def fetch_market_returns(period: str = "5y") -> pd.Series:
    return _fetch_ibov_log_returns(period=period)


def fetch_market_range(start: str, end: str) -> pd.Series:
    return _fetch_ibov_log_returns(start=start, end=end)


# ── Portfolio math ────────────────────────────────────────────────────────────

def annualize(returns: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    return returns.mean() * DIAS_UTEIS, returns.cov() * DIAS_UTEIS


def compute_efficient_frontier(mu: pd.Series, S: pd.DataFrame,
                               n_points: int = 80) -> list[tuple[float, float]]:
    ef_mv = _make_ef(mu, S)
    ef_mv.min_volatility()
    vol_min, ret_min, _ = ef_mv.portfolio_performance(verbose=False)

    # Find highest feasible return target from the top down
    ret_max = ret_min
    for candidate in np.linspace(max(float(mu.max()), ret_min * 1.5), ret_min, 20):
        try:
            ef_test = _make_ef(mu, S)
            ef_test.efficient_return(target_return=float(candidate))
            ret_max = float(candidate)
            break
        except Exception:
            continue

    if ret_max <= ret_min:
        return [(float(vol_min), float(ret_min))]

    frontier = []
    for target in np.linspace(ret_min, ret_max, n_points):
        try:
            ef = _make_ef(mu, S)
            ef.efficient_return(target_return=float(target))
            vol, ret, _ = ef.portfolio_performance(verbose=False)
            frontier.append((float(vol), float(ret)))
        except Exception:
            pass
    return frontier


def compute_max_sharpe(mu: pd.Series, S: pd.DataFrame,
                       rf: float) -> tuple[dict, float, float, float]:
    ef = _make_ef(mu, S)
    try:
        ef.max_sharpe(risk_free_rate=rf)
    except Exception:
        # No asset beats the risk-free rate — fall back to min-volatility portfolio
        ef = _make_ef(mu, S)
        ef.min_volatility()
    weights = ef.clean_weights()
    vol, ret, sharpe = ef.portfolio_performance(risk_free_rate=rf, verbose=False)
    return dict(weights), float(vol), float(ret), float(sharpe)


def compute_min_vol(mu: pd.Series, S: pd.DataFrame,
                    rf: float) -> tuple[dict, float, float, float]:
    ef = _make_ef(mu, S)
    ef.min_volatility()
    weights = ef.clean_weights()
    vol, ret, sharpe = ef.portfolio_performance(risk_free_rate=rf, verbose=False)
    return dict(weights), float(vol), float(ret), float(sharpe)


def compute_naive(tickers: list[str], mu: pd.Series, S: pd.DataFrame,
                  rf: float) -> tuple[dict, float, float, float]:
    n       = len(tickers)
    weights = {t: 1.0 / n for t in tickers}
    w       = np.array([weights[t] for t in mu.index])
    ret     = float(w @ mu.values)
    vol     = float(math.sqrt(float(w @ S.values @ w)))
    sharpe  = (ret - rf) / vol if vol > 0 else 0.0
    return weights, vol, ret, sharpe


def compute_capm_betas(asset_returns: pd.DataFrame, market_returns: pd.Series,
                       rf_annual: float = 0.1075) -> dict:
    rf_daily = rf_annual / DIAS_UTEIS
    common   = asset_returns.index.intersection(market_returns.index)
    mkt_exc  = (market_returns.loc[common] - rf_daily).values
    betas    = {}
    for ticker in asset_returns.columns:
        asset_exc = (asset_returns.loc[common, ticker] - rf_daily).values
        slope, intercept, r, _, _ = linregress(mkt_exc, asset_exc)
        betas[ticker] = {
            "beta":  round(float(slope), 3),
            "alpha": round(float(intercept) * DIAS_UTEIS * 100, 2),
            "r2":    round(float(r ** 2), 3),
        }
    return betas


# ── Playground / backtesting ──────────────────────────────────────────────────

def simulate_portfolio(weights: dict, log_returns: pd.DataFrame) -> pd.Series:
    tickers = [t for t in weights if t in log_returns.columns]
    simple  = np.exp(log_returns[tickers]) - 1
    w       = pd.Series({t: weights[t] for t in tickers})
    port    = (simple * w).sum(axis=1)
    return (1 + port).cumprod() * 100


def compute_metricas_oos(series: pd.Series, benchmark: pd.Series,
                         rf_aa: float) -> dict:
    daily  = series.pct_change().dropna()
    n      = len(daily)
    total  = float(series.iloc[-1] / 100 - 1)
    ret_aa = float((1 + total) ** (DIAS_UTEIS / n) - 1) if n > 0 else 0.0
    vol_aa = float(daily.std() * (DIAS_UTEIS ** 0.5))
    sharpe = (ret_aa - rf_aa) / vol_aa if vol_aa > 0 else 0.0

    roll_max = series.cummax()
    max_dd   = float(((series - roll_max) / roll_max).min())

    bm_daily = benchmark.pct_change().dropna()
    if len(bm_daily) > 1:
        common      = daily.index.intersection(bm_daily.index)
        bm_total    = float((1 + bm_daily.loc[common]).prod() - 1)
        bm_ret_aa   = float((1 + bm_total) ** (DIAS_UTEIS / len(common)) - 1) if common.size else 0.0
        alpha_vs_bm = ret_aa - bm_ret_aa
    else:
        alpha_vs_bm = 0.0

    return {
        "retorno_total":   round(total,       4),
        "retorno_aa":      round(ret_aa,      4),
        "volatilidade_aa": round(vol_aa,      4),
        "sharpe":          round(sharpe,      3),
        "max_drawdown":    round(max_dd,      4),
        "alpha_vs_ibov":   round(alpha_vs_bm, 4),
    }


# ── Report generation ─────────────────────────────────────────────────────────

def gerar_relatorio_str(res: dict) -> str:
    lines = [
        "=" * 62,
        "  RELATÓRIO — GESTÃO DE INVESTIMENTOS (CAD 167 — UFMG)",
        "=" * 62,
        f"  Data:                     {datetime.date.today()}",
        f"  Ativos analisados:        {', '.join(res['tickers'])}",
        f"  Período histórico:        {res['periodo']}",
        f"  Taxa livre de risco (Rƒ): {res['rf'] * 100:.2f}% a.a. (SELIC aprox.)",
        "",
    ]

    def _secao(titulo: str, pesos: dict, vol: float, ret: float, sharpe: float) -> None:
        lines.extend(["─" * 62, f"  {titulo}", "─" * 62])
        lines.append(f"  {'Ativo':<8} {'Peso':>8}  {'Beta':>6}  {'Alpha':>9}  {'R²':>6}")
        for t, w in sorted(pesos.items(), key=lambda x: -x[1]):
            if w < 0.0001:
                continue
            b = res["betas"].get(t, {})
            lines.append(
                f"  {t:<8} {w * 100:>7.1f}%"
                f"  {b.get('beta', 0):>6.3f}"
                f"  {b.get('alpha', 0):>8.2f}%"
                f"  {b.get('r2', 0):>6.3f}"
            )
        lines.extend([
            "",
            f"  Retorno esperado : {ret * 100:.2f}% a.a.",
            f"  Volatilidade     : {vol * 100:.2f}% a.a.",
            f"  Índice de Sharpe : {sharpe:.3f}",
            "",
        ])

    _secao("PORTFÓLIO MAX-SHARPE (portfólio tangente)",
           res["sharpe"]["pesos"], res["sharpe"]["vol"],
           res["sharpe"]["ret"],   res["sharpe"]["sharpe"])
    _secao("PORTFÓLIO MÍNIMA VOLATILIDADE",
           res["minvol"]["pesos"], res["minvol"]["vol"],
           res["minvol"]["ret"],   res["minvol"]["sharpe"])
    _secao("PORTFÓLIO 1/N (benchmark ingênuo)",
           res["naive"]["pesos"],  res["naive"]["vol"],
           res["naive"]["ret"],    res["naive"]["sharpe"])

    lines.extend([
        "─" * 62,
        "  NOTAS METODOLÓGICAS",
        "─" * 62,
        "  • Retornos logarítmicos diários, anualizados por ×252 (dias úteis B3).",
        "  • Retornos esperados estimados por média histórica (sujeitos a overfitting).",
        "  • Otimização via programação quadrática (PyPortfolioOpt / cvxpy).",
        "  • Beta estimado por OLS: (Rᵢ−Rƒ) = α + β(Rₘ−Rƒ) + ε",
        "  • Ibovespa (^BVSP) como proxy do portfólio de mercado.",
        "  • CRP não adicionado: beta Ibovespa já embute risco-país.",
        "    Ref.: RAC/ANPAD — correlação Ibovespa × EMBI+ = −0,749",
        "=" * 62,
    ])
    return "\n".join(lines)
