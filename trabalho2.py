"""
=============================================================================
  GESTÃO DE INVESTIMENTOS — OTIMIZAÇÃO DE PORTFÓLIO COM FRONTEIRA EFICIENTE
=============================================================================

VISÃO GERAL
-----------
Aplicativo desktop (tkinter) que demonstra a Teoria Moderna do Portfólio (MPT)
de Markowitz (1952) aplicada a ações do Ibovespa.

O usuário seleciona um conjunto de ativos, define o período histórico e a taxa
livre de risco. O app busca dados via yfinance, calcula a fronteira eficiente,
destaca os portfólios de máximo Índice de Sharpe e mínima volatilidade, estima
os betas individuais via regressão OLS (CAPM), e gera um relatório em .txt.

FLUXO DE DADOS
--------------
1. Busca de preços históricos via yfinance (tickers com sufixo .SA)
2. Retornos logarítmicos diários: ln(Pₜ/Pₜ₋₁), anualizados ×252
3. Estimação de retornos esperados (média histórica) e matriz de covariância
4. Otimização via PyPortfolioOpt (cvxpy / programação quadrática):
     - Fronteira eficiente: varredura de retornos alvo → curva (vol, ret)
     - Max-Sharpe: maximiza (E[R] − Rƒ) / σ
     - Min-Vol: minimiza σ do portfólio
     - 1/N: benchmark ingênuo com pesos iguais
5. Estimação de beta por OLS: (Rᵢ − Rƒ) = α + β·(Rₘ − Rƒ) + ε
   onde Rₘ é o retorno do Ibovespa (^BVSP)

NOTA SOBRE RISCO-PAÍS
---------------------
Não é adicionado prêmio de risco-país (CRP) ao CAPM.
Embasamento: estudo RAC/ANPAD (204 empresas BM&FBovespa, 2009–2013) mostrou
correlação de −0,749 entre retornos do Ibovespa e spread EMBI+, indicando que
o beta local já embute o risco-país. Adicionar CRP ao beta local seria dupla
contagem. A abordagem de Damodaran com CRP aplica-se apenas ao usar um índice
global (S&P 500) como base de mercado.

LIMITAÇÕES
----------
  Retornos esperados estimados por média histórica — sujeitos a overfitting.
  O portfólio max-Sharpe in-sample tende a superestimar desempenho fora da
  amostra. Recomenda-se usar 5–15 ativos para uma fronteira bem definida.
=============================================================================
"""

import datetime
import math
import threading
import tkinter as tk

import numpy as np
import pandas as pd
import yfinance as yf
from pypfopt import EfficientFrontier
from scipy.stats import linregress


# =============================================================================
#  CONFIGURAÇÃO
# =============================================================================

# Lista ampla de ações brasileiras — usada como fallback se a API da B3 falhar.
# Inclui constituintes do Ibovespa + ações relevantes do IBRX-100.
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

# 5 tickers pré-selecionados ao abrir o app
TICKERS_SELECAO_INICIAL = ["VALE3", "PETR4", "ITUB4", "BBDC4", "WEGE3"]

# Ticker do índice Ibovespa no yfinance (proxy do portfólio de mercado)
IBOV_TICKER = "^BVSP"

# Mapeamento de label → período aceito pelo yfinance
PERIODOS = {"1A": "1y", "2A": "2y", "5A": "5y"}

# Número de dias úteis por ano — padrão B3
DIAS_UTEIS = 252

# SELIC vigente como padrão da taxa livre de risco (% a.a.)
RF_DEFAULT = 10.75

# ── Paleta de cores (dark theme, consistente com Trabalho 1) ─────────────────
BG       = "#0f1117"   # fundo principal
BG_SIDE  = "#111520"   # fundo da sidebar
BG_INPUT = "#1e2535"   # fundo de inputs e botões secundários
FG       = "#94a3b8"   # texto padrão
FG_DIM   = "#4a5568"   # labels de seção
ACCENT   = "#00e5ff"   # destaque (azul ciano)

# Cores dos portfólios e elementos do gráfico
COR_FRONTIER = "#3b82f6"   # curva da fronteira eficiente
COR_SHARPE   = "#ffd700"   # ponto max-Sharpe
COR_MINVOL   = "#51cf66"   # ponto min-vol
COR_NAIVE    = "#94a3b8"   # ponto 1/N
COR_ASSET    = "#4a5568"   # ativos individuais
COR_CML      = "#ff6b6b"   # Capital Market Line


# =============================================================================
#  CAMADA DE DADOS (Fase 1)
# =============================================================================

def fetch_prices(tickers: list[str], period: str = "5y") -> pd.DataFrame:
    """
    Busca preços de fechamento ajustados para tickers do Ibovespa via yfinance.

    Os tickers são convertidos para o formato yfinance (sufixo .SA).
    Tickers sem dados no período são removidos e um aviso é emitido.

    Retorna DataFrame de retornos logarítmicos diários ln(Pₜ/Pₜ₋₁).
    Retornos log são usados por serem aditivos no tempo e melhor comportados
    estatisticamente do que retornos aritméticos.

    Parâmetros
    ----------
    tickers : lista de códigos sem sufixo (ex.: ["VALE3", "PETR4"])
    period  : string de período do yfinance ("1y", "2y", "5y")
    """
    yf_tickers = [t.upper().replace(".SA", "") + ".SA" for t in tickers]

    # Uma única requisição para todos os tickers é mais eficiente
    raw = yf.download(yf_tickers, period=period, auto_adjust=True, progress=False)

    # yfinance retorna MultiIndex de colunas quando há múltiplos tickers
    closes = (raw["Close"] if isinstance(raw.columns, pd.MultiIndex)
              else raw[["Close"]].rename(columns={"Close": yf_tickers[0]}))

    # Remove colunas inteiramente vazias (ticker sem dados no plano gratuito)
    closes = closes.dropna(axis=1, how="all")
    if closes.empty:
        raise ValueError("Nenhum dado disponível para os tickers fornecidos.")

    tickers_ok  = [c.replace(".SA", "") for c in closes.columns]
    tickers_bad = [t for t in tickers if t not in tickers_ok]
    if tickers_bad:
        print(f"[yfinance] Sem dados: {', '.join(tickers_bad)} — removidos.")

    # Retornos logarítmicos: ln(Pₜ / Pₜ₋₁)
    log_ret = np.log(closes / closes.shift(1)).iloc[1:].dropna()
    log_ret.columns = [c.replace(".SA", "") for c in log_ret.columns]
    return log_ret


def fetch_market_returns(period: str = "5y") -> pd.Series:
    """
    Busca retornos logarítmicos diários do Ibovespa (^BVSP).

    O Ibovespa é usado como proxy do portfólio de mercado na estimação de beta
    pelo CAPM. Usar o índice local elimina a necessidade de adicionar prêmio
    de risco-país separado (ver nota no topo do arquivo).
    """
    raw = yf.download(IBOV_TICKER, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"Não foi possível buscar dados do Ibovespa ({IBOV_TICKER}).")

    closes  = raw["Close"].squeeze()
    log_ret = np.log(closes / closes.shift(1)).iloc[1:].dropna()
    return log_ret.rename("IBOV")


def annualize(returns: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """
    Converte retornos logarítmicos diários em métricas anualizadas.

    Retorno esperado anualizado: μ_anual = μ_diário × 252
    Covariância anualizada:      Σ_anual = Σ_diário × 252

    A anualização linear por 252 é o padrão do mercado (dias úteis B3).
    Retorna (mu, S): retornos esperados e matriz de covariância anualizados.
    """
    mu = returns.mean() * DIAS_UTEIS
    S  = returns.cov()  * DIAS_UTEIS
    return mu, S


# =============================================================================
#  CAMADA DE CÁLCULO — MPT (Fase 2)
# =============================================================================

def compute_efficient_frontier(mu: pd.Series, S: pd.DataFrame,
                               n_points: int = 80) -> list[tuple[float, float]]:
    """
    Calcula a fronteira eficiente de Markowitz varrendo retornos alvo.

    Para cada retorno alvo no intervalo [ret_min_vol, ret_max_alcançável], resolve:
        min  wᵀΣw
        s.t. wᵀμ = retorno_alvo
             Σwᵢ = 1
             wᵢ ≥ 0  (sem venda a descoberto)

    O limite inferior é o retorno do portfólio de mínima volatilidade.
    O limite superior é descoberto empiricamente via bissecção — evita o bug
    em que mu.max() < ret_min_vol quando ativos têm retornos históricos baixos
    (comum em períodos de mercado lateralizado ou com alta Selic).

    Retorna lista de (volatilidade, retorno) para cada ponto da fronteira.
    Pontos onde o QP é infeasível são silenciosamente descartados.
    """
    # Limite inferior: retorno do portfólio de mínima volatilidade
    ef_mv = EfficientFrontier(mu, S, weight_bounds=(0, 1))
    ef_mv.min_volatility()
    vol_mv, ret_min, _ = ef_mv.portfolio_performance(verbose=False)

    # Limite superior: busca o maior retorno alvo que ainda é feasível.
    # Começa pelo maior retorno individual; se for menor que ret_min (pode
    # ocorrer por instabilidade numérica quando retornos são baixos),
    # usa ret_min * 1.5 como ponto de partida e recua até encontrar.
    ret_max_candidate = max(float(mu.max()), ret_min * 1.5)
    ret_max = ret_min  # fallback: pelo menos inclui o ponto min-vol
    for candidate in np.linspace(ret_max_candidate, ret_min, 20):
        try:
            ef_test = EfficientFrontier(mu, S, weight_bounds=(0, 1))
            ef_test.efficient_return(target_return=float(candidate))
            ret_max = float(candidate)
            break
        except Exception:
            continue

    if ret_max <= ret_min:
        # Sem espaço para varrer: retorna apenas o ponto de mínima volatilidade
        return [(float(vol_mv), float(ret_min))]

    frontier = []
    for target in np.linspace(ret_min, ret_max, n_points):
        try:
            ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
            ef.efficient_return(target_return=float(target))
            vol, ret, _ = ef.portfolio_performance(verbose=False)
            frontier.append((float(vol), float(ret)))
        except Exception:
            pass   # ignora pontos infeasíveis nas bordas

    return frontier


def compute_max_sharpe(mu: pd.Series, S: pd.DataFrame,
                       rf: float) -> tuple[dict, float, float, float]:
    """
    Portfólio de máximo Índice de Sharpe (portfólio tangente).

    Resolve: max  (wᵀμ − Rƒ) / √(wᵀΣw)
    via transformação de variáveis (Markowitz-Tobin): equivalente a QP.

    O portfólio tangente é o ponto de tangência entre a Capital Market Line
    e a fronteira eficiente — a melhor combinação risco/retorno disponível.

    Retorna (pesos, volatilidade, retorno, sharpe).
    """
    ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
    ef.max_sharpe(risk_free_rate=rf)
    weights = ef.clean_weights()
    vol, ret, sharpe = ef.portfolio_performance(risk_free_rate=rf, verbose=False)
    return dict(weights), float(vol), float(ret), float(sharpe)


def compute_min_vol(mu: pd.Series, S: pd.DataFrame,
                    rf: float) -> tuple[dict, float, float, float]:
    """
    Portfólio de mínima volatilidade global (MVP).

    Resolve: min  wᵀΣw   s.t. Σwᵢ = 1, wᵢ ≥ 0
    Este portfólio não depende dos retornos esperados — apenas da covariância.
    É o ponto mais à esquerda da fronteira eficiente.

    Retorna (pesos, volatilidade, retorno, sharpe).
    """
    ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
    ef.min_volatility()
    weights = ef.clean_weights()
    vol, ret, sharpe = ef.portfolio_performance(risk_free_rate=rf, verbose=False)
    return dict(weights), float(vol), float(ret), float(sharpe)


def compute_naive(tickers: list[str], mu: pd.Series, S: pd.DataFrame,
                  rf: float) -> tuple[dict, float, float, float]:
    """
    Portfólio ingênuo 1/N — benchmark de alocação uniforme.

    Cada ativo recebe peso wᵢ = 1/N, sem nenhuma otimização.
    Serve como linha de base para avaliar o ganho dos portfólios otimizados.
    Estudos empíricos mostram que 1/N é difícil de superar fora da amostra
    (DeMiguel et al., 2009).

    Retorna (pesos, volatilidade, retorno, sharpe).
    """
    n       = len(tickers)
    weights = {t: 1.0 / n for t in tickers}
    w       = np.array([weights[t] for t in mu.index])
    ret     = float(w @ mu.values)
    vol     = float(math.sqrt(float(w @ S.values @ w)))
    sharpe  = (ret - rf) / vol if vol > 0 else 0.0
    return weights, vol, ret, sharpe


# =============================================================================
#  CAMADA DE CÁLCULO — CAPM (Fase 3)
# =============================================================================

def compute_capm_betas(asset_returns: pd.DataFrame,
                       market_returns: pd.Series,
                       rf_annual: float = 0.1075) -> dict:
    """
    Estima beta, alpha anualizado e R² para cada ativo via regressão OLS.

    Modelo CAPM em excesso de retorno:
        (Rᵢ − Rƒ) = α + β·(Rₘ − Rƒ) + ε

    onde Rᵢ = retorno diário do ativo,
          Rₘ = retorno diário do Ibovespa,
          Rƒ = SELIC_anual / 252  (taxa livre de risco diária).

    Interpretação:
      β > 1 → ativo mais volátil que o mercado (amplifica movimentos)
      β < 1 → ativo mais defensivo (amorte movimentos)
      α > 0 → retorno acima do esperado pelo CAPM (Jensen's alpha)
      R²    → fração da variância do ativo explicada pelo mercado

    Parâmetros
    ----------
    rf_annual : taxa livre de risco anualizada (ex.: 0.1075 = 10.75% a.a.)

    Retorna
    -------
    dict {ticker: {'beta': float, 'alpha': float (% a.a.), 'r2': float}}
    """
    rf_daily = rf_annual / DIAS_UTEIS

    # Alinha os retornos pelo índice de datas (nem sempre coincidem)
    common   = asset_returns.index.intersection(market_returns.index)
    mkt_exc  = (market_returns.loc[common] - rf_daily).values

    betas = {}
    for ticker in asset_returns.columns:
        asset_exc = (asset_returns.loc[common, ticker] - rf_daily).values
        slope, intercept, r, _, _ = linregress(mkt_exc, asset_exc)
        betas[ticker] = {
            "beta":  round(float(slope), 3),
            "alpha": round(float(intercept) * DIAS_UTEIS * 100, 2),  # % a.a.
            "r2":    round(float(r ** 2), 3),
        }
    return betas


# =============================================================================
#  GERAÇÃO DE RELATÓRIO (Fase 5)
# =============================================================================

def gerar_relatorio(res: dict) -> str:
    """
    Gera relatório em .txt com os resultados da otimização e estimação de beta.

    O arquivo é salvo no diretório atual com nome relatorio_<ativos>_<data>.txt.
    Retorna o caminho do arquivo gerado.
    """
    hoje    = datetime.date.today().strftime("%Y%m%d")
    prefixo = "_".join(res["tickers"][:3])
    path    = f"relatorio_{prefixo}_{hoje}.txt"

    L = []  # linhas do relatório

    L += [
        "=" * 62,
        "  RELATÓRIO — GESTÃO DE INVESTIMENTOS (CAD 167 — UFMG)",
        "=" * 62,
        f"  Data:                    {datetime.date.today()}",
        f"  Ativos analisados:       {', '.join(res['tickers'])}",
        f"  Período histórico:       {res['periodo']}",
        f"  Taxa livre de risco (Rƒ): {res['rf'] * 100:.2f}% a.a. (SELIC aprox.)",
        "",
    ]

    def _secao(lines, titulo, pesos, vol, ret, sharpe):
        """Formata uma seção de portfólio para o relatório."""
        lines.append("─" * 62)
        lines.append(f"  {titulo}")
        lines.append("─" * 62)
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
        lines += [
            "",
            f"  Retorno esperado : {ret * 100:.2f}% a.a.",
            f"  Volatilidade     : {vol * 100:.2f}% a.a.",
            f"  Índice de Sharpe : {sharpe:.3f}",
            "",
        ]

    _secao(L, "PORTFÓLIO MAX-SHARPE (portfólio tangente)",
           res["sharpe"]["pesos"], res["sharpe"]["vol"],
           res["sharpe"]["ret"],   res["sharpe"]["sharpe"])

    _secao(L, "PORTFÓLIO MÍNIMA VOLATILIDADE",
           res["minvol"]["pesos"], res["minvol"]["vol"],
           res["minvol"]["ret"],   res["minvol"]["sharpe"])

    _secao(L, "PORTFÓLIO 1/N (benchmark ingênuo)",
           res["naive"]["pesos"],  res["naive"]["vol"],
           res["naive"]["ret"],    res["naive"]["sharpe"])

    L += [
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
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    return path


# =============================================================================
#  ESTADO GLOBAL DA UI
# =============================================================================

root = tk.Tk()
root.title("Gestão de Investimentos — Fronteira Eficiente de Markowitz")
root.geometry("1200x740")
root.configure(bg=BG)

# Variáveis tkinter da sidebar
periodo_var = tk.StringVar(value="5A")
rf_var      = tk.StringVar(value=str(RF_DEFAULT))
status_var  = tk.StringVar(value="")

# Resultado atual (preenchido pela thread de cálculo)
resultado: dict | None = None


# =============================================================================
#  HELPERS DE DESENHO DO CANVAS (Fase 4)
# =============================================================================

def _margins(W: int, H: int) -> tuple[int, int, int, int]:
    """Retorna as margens do canvas (x0, y0, x1, y1) em pixels."""
    return 70, 30, W - 20, H - 50


def _make_transforms(frontier: list, res: dict, W: int, H: int):
    """
    Cria funções de transformação (vol, ret) → (pixel_x, pixel_y).

    Determina os limites dos eixos a partir de todos os pontos no canvas
    (fronteira + portfólios + ativos individuais) e adiciona 10% de padding.
    """
    x0, y0, x1, y1 = _margins(W, H)

    all_vols = [v for v, _ in frontier]
    all_rets = [r for _, r in frontier]

    for key in ("sharpe", "minvol", "naive"):
        all_vols.append(res[key]["vol"])
        all_rets.append(res[key]["ret"])
    for t in res["tickers"]:
        all_vols.append(res["asset_vols"][t])
        all_rets.append(res["asset_rets"][t])

    if not all_vols:
        return None, None, None, None

    vmin = min(all_vols) * 0.90
    vmax = max(all_vols) * 1.10
    rmin = min(all_rets) * (1.10 if min(all_rets) < 0 else 0.85)
    rmax = max(all_rets) * 1.12

    # Garante que a taxa livre de risco (ponto de origem da CML) aparece no eixo Y
    try:
        rf = res["rf"]
        rmin = min(rmin, rf * 0.90)
    except Exception:
        pass

    def px(vol):
        return x0 + (vol - vmin) / (vmax - vmin) * (x1 - x0)

    def py(ret):
        return y1 - (ret - rmin) / (rmax - rmin) * (y1 - y0)

    return px, py, vmin, vmax, rmin, rmax


def _draw_grid(cv, vmin, vmax, rmin, rmax, px, py, x0, y0, x1, y1):
    """
    Desenha grade de fundo, marcações e rótulos nos eixos X (vol) e Y (ret).
    Usa 5 divisões uniformes em cada eixo.
    """
    for k in range(5):
        # Linhas horizontais (retorno no eixo Y)
        gy = y0 + k * (y1 - y0) / 4
        gv = rmax - k * (rmax - rmin) / 4
        cv.create_line(x0, gy, x1, gy, fill="#1e2535", dash=(3, 5))
        cv.create_text(x0 - 6, gy, text=f"{gv * 100:.1f}%",
                       font=("Courier New", 8), fill=FG_DIM, anchor="e")

        # Linhas verticais (volatilidade no eixo X)
        gx  = x0 + k * (x1 - x0) / 4
        gvx = vmin + k * (vmax - vmin) / 4
        cv.create_line(gx, y0, gx, y1, fill="#1e2535", dash=(3, 5))
        cv.create_text(gx, y1 + 6, text=f"{gvx * 100:.1f}%",
                       font=("Courier New", 8), fill=FG_DIM, anchor="n")

    # Rótulos dos eixos
    cv.create_text((x0 + x1) // 2, y1 + 38,
                   text="Volatilidade Anualizada (risco)",
                   font=("Courier New", 9), fill=FG_DIM, anchor="n")
    cv.create_text(14, (y0 + y1) // 2,
                   text="Retorno Esperado Anualizado",
                   font=("Courier New", 9), fill=FG_DIM, anchor="center", angle=90)


def _draw_cml(cv, px, py, rf: float, sharpe_vol: float, sharpe_ret: float, x1: int):
    """
    Desenha a Capital Market Line (CML).

    A CML parte do ponto (vol=0, ret=Rƒ) e passa pelo portfólio tangente
    (max-Sharpe). Representa as combinações eficientes de ativo sem risco
    e portfólio arriscado. Inclinação = Índice de Sharpe do portfólio tangente.
    """
    if sharpe_vol <= 0:
        return

    slope   = (sharpe_ret - rf) / sharpe_vol
    x_start = px(0)
    y_start = py(rf)

    # Estende a CML até a borda direita do canvas
    vol_end = (x1 - px(0)) / (px(sharpe_vol) - px(0)) * sharpe_vol
    ret_end = rf + slope * vol_end

    cv.create_line(x_start, y_start, x1, py(ret_end),
                   fill=COR_CML, width=1, dash=(6, 4))
    cv.create_text(x1 - 4, py(ret_end) - 10, text="CML",
                   font=("Courier New", 8), fill=COR_CML, anchor="e")

    # Marca o ponto de origem (Rƒ, 0) na CML
    cv.create_oval(x_start - 4, y_start - 4, x_start + 4, y_start + 4,
                   fill=COR_CML, outline=BG, width=1)
    cv.create_text(x_start + 8, y_start,
                   text=f"Rƒ={rf * 100:.1f}%",
                   font=("Courier New", 7), fill=COR_CML, anchor="w")


def _draw_frontier_curve(cv, px, py, frontier: list):
    """Plota a curva da fronteira eficiente como linha contínua suavizada."""
    if len(frontier) < 2:
        return
    pts = []
    for vol, ret in frontier:
        pts += [px(vol), py(ret)]
    cv.create_line(*pts, fill=COR_FRONTIER, width=2, smooth=True)


def _draw_portfolio_point(cv, px, py, vol: float, ret: float,
                          color: str, label: str, sharpe: float | None = None):
    """
    Plota um portfólio como círculo colorido com label e Índice de Sharpe.
    Usado para max-Sharpe, min-vol e 1/N.
    """
    cx_, cy_ = px(vol), py(ret)
    cv.create_oval(cx_ - 7, cy_ - 7, cx_ + 7, cy_ + 7,
                   fill=color, outline=BG, width=2)
    txt = label if sharpe is None else f"{label}  (SR={sharpe:.2f})"
    cv.create_text(cx_ + 11, cy_, text=txt,
                   font=("Courier New", 8, "bold"), fill=color, anchor="w")


def _draw_asset_points(cv, px, py, res: dict):
    """
    Plota os ativos individuais como pontos menores no espaço risco-retorno.
    Permite visualizar onde cada ativo fica antes da diversificação.
    """
    for t in res["tickers"]:
        v   = res["asset_vols"][t]
        r   = res["asset_rets"][t]
        cx_ = px(v)
        cy_ = py(r)
        cv.create_oval(cx_ - 3, cy_ - 3, cx_ + 3, cy_ + 3,
                       fill=COR_ASSET, outline="#94a3b8", width=1)
        cv.create_text(cx_ + 6, cy_ - 7, text=t,
                       font=("Courier New", 7), fill="#555e72", anchor="w")


def _draw_legend(cv, x0: int, y0: int):
    """Desenha a legenda dos elementos do gráfico no canto superior esquerdo."""
    items = [
        ("Fronteira Eficiente", COR_FRONTIER),
        ("Max-Sharpe",          COR_SHARPE),
        ("Min-Vol",             COR_MINVOL),
        ("1/N",                 COR_NAIVE),
        ("CML",                 COR_CML),
    ]
    for i, (lbl, cor) in enumerate(items):
        lx = x0 + 10 + i * 162
        ly = y0 + 8
        cv.create_rectangle(lx, ly, lx + 10, ly + 8, fill=cor, outline="")
        cv.create_text(lx + 14, ly + 4, text=lbl,
                       font=("Courier New", 8), fill=FG, anchor="w")


# =============================================================================
#  GRÁFICO PRINCIPAL
# =============================================================================

def desenhar():
    """
    Redesenha completamente o canvas a partir do estado global (resultado).
    Chamado ao concluir o cálculo e ao redimensionar a janela.
    """
    c.delete("all")
    W, H = c.winfo_width(), c.winfo_height()
    if W < 50 or H < 50:
        return

    if not resultado:
        c.create_text(W // 2, H // 2,
                      text="Selecione ativos e clique em Calcular",
                      font=("Courier New", 11), fill=FG_DIM)
        return

    frontier = resultado["frontier"]
    x0, y0, x1, y1 = _margins(W, H)
    transforms = _make_transforms(frontier, resultado, W, H)
    if transforms[0] is None:
        return
    px, py, vmin, vmax, rmin, rmax = transforms

    _draw_grid(c, vmin, vmax, rmin, rmax, px, py, x0, y0, x1, y1)

    # CML: parte de (0, Rƒ) e passa pelo portfólio tangente (max-Sharpe)
    _draw_cml(c, px, py,
              resultado["rf"],
              resultado["sharpe"]["vol"],
              resultado["sharpe"]["ret"],
              x1)

    _draw_frontier_curve(c, px, py, frontier)
    _draw_asset_points(c, px, py, resultado)

    # Portfólios em ordem crescente de destaque (último = mais visível)
    _draw_portfolio_point(c, px, py,
                          resultado["naive"]["vol"], resultado["naive"]["ret"],
                          COR_NAIVE, "1/N", resultado["naive"]["sharpe"])
    _draw_portfolio_point(c, px, py,
                          resultado["minvol"]["vol"], resultado["minvol"]["ret"],
                          COR_MINVOL, "Min-Vol", resultado["minvol"]["sharpe"])
    _draw_portfolio_point(c, px, py,
                          resultado["sharpe"]["vol"], resultado["sharpe"]["ret"],
                          COR_SHARPE, "Max-Sharpe", resultado["sharpe"]["sharpe"])

    _draw_legend(c, x0, y0)


# =============================================================================
#  TABELA DE PESOS (Fase 4 — painel inferior)
# =============================================================================

# Linhas de labels da tabela — criadas uma vez e atualizadas dinamicamente
_table_rows: list[list[tk.Label]] = []

# Cabeçalhos da tabela — cada coluna corresponde a um indicador calculado
# Max-Sharpe e Min-Vol são portfólios otimizados; 1/N é o benchmark sem otimização
# Beta, Alpha e R² vêm da regressão OLS do modelo CAPM
COLS_TABLE = ["Ativo", "Max-Sharpe", "Min-Vol", "1/N", "Beta (β)", "Alpha (α a.a.)", "R²"]

# Descrições exibidas no glossário da sidebar (painel inferior)
# Permitem que o professor e os alunos entendam cada indicador sem sair do app
GLOSSARIO = [
    ("Fronteira Eficiente",
     "Conjunto de portfólios que oferecem o maior retorno possível para cada nível de risco "
     "(volatilidade). Portfólios abaixo da curva são ineficientes — existe outro com mais "
     "retorno para o mesmo risco."),
    ("Max-Sharpe (portfólio tangente)",
     "Portfólio que maximiza o Índice de Sharpe: SR = (Ret − Rƒ) / Vol. "
     "É o ponto de tangência entre a Capital Market Line (CML) e a fronteira eficiente. "
     "Representa a melhor relação retorno/risco disponível dado Rƒ."),
    ("Min-Vol (variância mínima)",
     "Portfólio com a menor volatilidade possível, independentemente do retorno. "
     "É o vértice esquerdo da fronteira. Útil para investidores muito avessos a risco."),
    ("1/N (benchmark ingênuo)",
     "Alocação uniforme: peso igual para todos os ativos (1 dividido por N). "
     "Não usa nenhuma otimização. Serve de baseline — um bom modelo deve superá-lo "
     "consistentemente fora da amostra (o que nem sempre ocorre)."),
    ("CML — Capital Market Line",
     "Reta que parte de (vol=0, ret=Rƒ) e passa pelo portfólio tangente. "
     "Representa combinações ótimas entre o ativo sem risco e o portfólio arriscado. "
     "Inclinação = Índice de Sharpe do portfólio tangente."),
    ("Beta (β)",
     "Sensibilidade do ativo ao mercado. Estimado por OLS: (Rᵢ−Rƒ) = α + β(Rₘ−Rƒ) + ε. "
     "β > 1 → amplifica movimentos do Ibovespa (ativo agressivo). "
     "β < 1 → amorte movimentos (ativo defensivo). "
     "β = 1 → move-se igual ao mercado."),
    ("Alpha (α)",
     "Retorno anualizado acima (ou abaixo) do esperado pelo CAPM. "
     "α > 0 → ativo gerou mais retorno do que o risco sistemático justificaria. "
     "α < 0 → ativo destruiu valor ajustado ao risco. Também chamado Jensen's Alpha."),
    ("R² (coeficiente de determinação)",
     "Fração da variância do ativo explicada pelo movimento do mercado (Ibovespa). "
     "R² = 0,80 → 80% da variação do preço é explicada pelo mercado; o restante é "
     "risco específico da empresa (diversificável)."),
    ("Índice de Sharpe (SR)",
     "SR = (Retorno esperado − Taxa livre de risco) / Volatilidade. "
     "Mede o prêmio de retorno por unidade de risco total. "
     "Quanto maior, melhor a relação risco/retorno do portfólio."),
    ("Volatilidade (σ)",
     "Desvio-padrão anualizado dos retornos — medida de risco total do portfólio. "
     "Calculada como √(wᵀ Σ w), onde Σ é a matriz de covariância dos ativos e w são os pesos. "
     "Inclui risco de mercado (β) e risco específico da empresa."),
    ("Taxa livre de risco (Rƒ)",
     "Retorno de um ativo sem risco de crédito. No Brasil, usa-se a SELIC como proxy. "
     "No CAPM, Rƒ é a origem da CML e o denominador do excesso de retorno. "
     "Altere o campo na sidebar para testar diferentes cenários de juros."),
]


def _build_table(parent: tk.Frame):
    """
    Cria os widgets da tabela de pesos: cabeçalho + até 20 linhas de ativos.
    Chamado uma única vez na montagem da UI.

    Colunas:
      Ativo       — código do ticker (ex.: VALE3)
      Max-Sharpe  — peso (%) neste portfólio; 0% = não incluído
      Min-Vol     — peso (%) no portfólio de mínima volatilidade
      1/N         — peso (%) no benchmark uniforme (sempre = 100%/N)
      Beta (β)    — sensibilidade ao Ibovespa (OLS)
      Alpha (α)   — retorno anual acima do CAPM (Jensen's Alpha)
      R²          — % da variância explicada pelo mercado
    """
    # Textos de ajuda exibidos ao passar o mouse sobre cada cabeçalho (tooltip simples)
    tooltips = {
        "Ativo":             "Código do ativo na B3 (ex.: VALE3, PETR4)",
        "Max-Sharpe":        "Peso no portfólio de máximo Índice de Sharpe (melhor ret/risco)",
        "Min-Vol":           "Peso no portfólio de mínima volatilidade (menor risco possível)",
        "1/N":               "Peso no portfólio ingênuo (igual para todos — sem otimização)",
        "Beta (β)":          "β > 1: mais volátil que o mercado | β < 1: mais defensivo",
        "Alpha (α a.a.)":    "Retorno anualizado acima do esperado pelo CAPM (Jensen's Alpha)",
        "R²":                "Fração da variância do ativo explicada pelo Ibovespa (0 a 1)",
    }

    for j, h in enumerate(COLS_TABLE):
        lbl = tk.Label(parent, text=h, font=("Courier New", 8, "bold"),
                       bg=BG_INPUT, fg=ACCENT, padx=8, pady=4, anchor="center")
        lbl.grid(row=0, column=j, sticky="ew", padx=1, pady=1)
        # Tooltip: mostra descrição no label de status ao passar o mouse
        tip = tooltips.get(h, "")
        # Tooltip: mostra dica no status ao passar o mouse, restaura ao sair
        lbl.bind("<Enter>", lambda e, t=tip: status_var.set(t))
        lbl.bind("<Leave>", lambda e: status_var.set(
            f"OK — {len(resultado['tickers'])} ativos" if resultado else ""))

    for i in range(1, 21):
        row = []
        for j in range(len(COLS_TABLE)):
            lbl = tk.Label(parent, text="", font=("Courier New", 8),
                           bg=BG_SIDE, fg=FG, padx=8, pady=3, anchor="center")
            lbl.grid(row=i, column=j, sticky="ew", padx=1, pady=1)
            row.append(lbl)
        _table_rows.append(row)

    for j in range(len(COLS_TABLE)):
        parent.columnconfigure(j, weight=1)


def _update_table():
    """Preenche a tabela de pesos com os dados do resultado atual."""
    if not resultado:
        return

    tickers = resultado["tickers"]
    betas   = resultado["betas"]

    for i, t in enumerate(tickers):
        if i >= len(_table_rows):
            break
        w_s = resultado["sharpe"]["pesos"].get(t, 0)
        w_m = resultado["minvol"]["pesos"].get(t, 0)
        w_n = resultado["naive"]["pesos"].get(t, 0)
        b   = betas.get(t, {})
        vals = [
            t,
            f"{w_s * 100:.1f}%",
            f"{w_m * 100:.1f}%",
            f"{w_n * 100:.1f}%",
            f"{b.get('beta', 0):.3f}",
            f"{b.get('alpha', 0):.2f}%",
            f"{b.get('r2', 0):.3f}",
        ]
        for j, v in enumerate(vals):
            _table_rows[i][j].config(text=v)

    # Limpa linhas de ativos anteriores que já não estão na seleção atual
    for i in range(len(tickers), len(_table_rows)):
        for lbl in _table_rows[i]:
            lbl.config(text="")


# =============================================================================
#  CARREGAMENTO E CÁLCULO (Fase 4 — thread)
# =============================================================================

def calcular():
    """
    Lê a seleção da sidebar e executa todos os cálculos em thread separada
    para não travar a interface durante as requisições de rede e a otimização.

    Ao concluir, atualiza o estado global, redesenha o canvas e a tabela.
    """
    global resultado

    selected = [ticker_listbox.get(i) for i in ticker_listbox.curselection()]
    if len(selected) < 2:
        status_var.set("Selecione ao menos 2 ativos.")
        return

    try:
        rf = float(rf_var.get().replace(",", ".")) / 100
    except ValueError:
        status_var.set("Taxa livre de risco inválida.")
        return

    periodo_yf = PERIODOS.get(periodo_var.get(), "5y")
    status_var.set("Buscando dados e calculando...")
    btn_calcular.config(state="disabled")
    btn_relatorio.config(state="disabled")

    def _worker():
        global resultado
        try:
            print(f"[calc] Buscando {selected} | período={periodo_yf} | Rƒ={rf:.4f}")

            # Fase 1: dados
            returns = fetch_prices(selected, period=periodo_yf)
            market  = fetch_market_returns(period=periodo_yf)
            tickers_ok = list(returns.columns)
            print(f"[calc] Dados OK: {tickers_ok} ({len(returns)} pregões)")

            # Fase 2: MPT
            mu, S        = annualize(returns)

            # Avisa quando muitos ativos têm retorno abaixo de Rƒ — o max-Sharpe
            # pode ser instável e a fronteira ficará curta nesses casos
            abaixo_rf = [t for t in tickers_ok if mu[t] < rf]
            if len(abaixo_rf) == len(tickers_ok):
                root.after(0, lambda: status_var.set(
                    f"Aviso: todos os ativos têm retorno histórico < Rƒ ({rf:.1%}). "
                    "Tente um período maior ou adicione ativos com melhor desempenho."))

            frontier     = compute_efficient_frontier(mu, S, n_points=80)
            sh_w, sh_v, sh_r, sh_s = compute_max_sharpe(mu, S, rf)
            mv_w, mv_v, mv_r, mv_s = compute_min_vol(mu, S, rf)
            nv_w, nv_v, nv_r, nv_s = compute_naive(tickers_ok, mu, S, rf)
            print(f"[calc] Fronteira: {len(frontier)} pts | "
                  f"Max-SR={sh_s:.2f} vol={sh_v:.1%} ret={sh_r:.1%}")

            # Fase 3: CAPM
            betas = compute_capm_betas(returns, market, rf_annual=rf)
            print(f"[calc] Betas: { {t: b['beta'] for t, b in betas.items()} }")

            # Volatilidade e retorno individuais para plotar no gráfico
            asset_vols = {t: math.sqrt(float(S.loc[t, t])) for t in tickers_ok}
            asset_rets = {t: float(mu[t]) for t in tickers_ok}

            resultado = {
                "tickers":    tickers_ok,
                "periodo":    periodo_var.get(),
                "rf":         rf,
                "frontier":   frontier,
                "sharpe":     {"pesos": sh_w, "vol": sh_v, "ret": sh_r, "sharpe": sh_s},
                "minvol":     {"pesos": mv_w, "vol": mv_v, "ret": mv_r, "sharpe": mv_s},
                "naive":      {"pesos": nv_w, "vol": nv_v, "ret": nv_r, "sharpe": nv_s},
                "betas":      betas,
                "asset_vols": asset_vols,
                "asset_rets": asset_rets,
            }
            root.after(0, _concluido, "")

        except Exception as e:
            import traceback
            traceback.print_exc()   # mostra erro completo no terminal
            root.after(0, _concluido, f"ERRO: {e}")

    def _concluido(msg: str):
        btn_calcular.config(state="normal")
        if msg:
            # Erro: mostra em vermelho e também no terminal via messagebox
            status_var.set(msg)
            status_lbl.config(fg="#ff4466")
            print(f"[calc] {msg}")
        else:
            # Sucesso: confirma na barra de status
            tks = resultado["tickers"] if resultado else []
            status_var.set(f"OK — {len(tks)} ativos carregados")
            status_lbl.config(fg="#51cf66")
        if resultado:
            btn_relatorio.config(state="normal")
        desenhar()
        _update_table()

    threading.Thread(target=_worker, daemon=True).start()


def exportar_relatorio():
    """Gera o relatório .txt e exibe o caminho salvo na barra de status."""
    if not resultado:
        return
    try:
        path = gerar_relatorio(resultado)
        status_var.set(f"Salvo: {path}")
    except Exception as e:
        status_var.set(f"Erro ao salvar: {e}")


# =============================================================================
#  LAYOUT DA INTERFACE (Fase 4)
# =============================================================================

# ── Helpers de layout ────────────────────────────────────────────────────────

def _section_label(parent, text, pady=(10, 4)):
    """Label de seção com estilo padronizado (texto em caixa alta dimmed)."""
    tk.Label(parent, text=text, font=("Courier New", 8),
             bg=BG_SIDE, fg=FG_DIM).pack(anchor="w", padx=12, pady=pady)


def _radio_row(parent, var, options):
    """Linha de radiobuttons horizontais com estilo de toggle."""
    frame = tk.Frame(parent, bg=BG_SIDE)
    frame.pack(fill="x", padx=12, pady=(0, 4))
    for text, value in options:
        tk.Radiobutton(frame, text=text, variable=var, value=value,
                       font=("Courier New", 8), bg=BG_SIDE, fg=FG,
                       selectcolor=BG_INPUT, activebackground=BG_SIDE,
                       activeforeground="#e2e8f0", indicatoron=False,
                       relief="flat", padx=4, pady=3, cursor="hand2",
                       ).pack(side="left", fill="x", expand=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────
sidebar = tk.Frame(root, bg=BG_SIDE, width=230)
sidebar.pack(side="left", fill="y", padx=(8, 0), pady=8)
sidebar.pack_propagate(False)

_section_label(sidebar, "ATIVOS  (ctrl+clique)", pady=(14, 4))

# Campo para adicionar qualquer ticker manualmente (não limitado ao Ibovespa)
add_frame = tk.Frame(sidebar, bg=BG_SIDE)
add_frame.pack(fill="x", padx=12, pady=(0, 4))
add_var = tk.StringVar()
add_entry = tk.Entry(add_frame, textvariable=add_var,
                     font=("Courier New", 9), bg=BG_INPUT, fg="#e2e8f0",
                     insertbackground="#e2e8f0", relief="flat",
                     highlightthickness=1, highlightbackground="#2a3550",
                     width=10)
add_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

def _add_ticker():
    """Insere o ticker digitado na listbox e o seleciona, se ainda não existir."""
    t = add_var.get().strip().upper().replace(".SA", "")
    if not t:
        return
    existing = [ticker_listbox.get(i) for i in range(ticker_listbox.size())]
    if t not in existing:
        ticker_listbox.insert("end", t)
    # Seleciona o ticker recém-adicionado
    idx = ticker_listbox.get(0, "end").index(t)
    ticker_listbox.selection_set(idx)
    ticker_listbox.see(idx)
    add_var.set("")

add_entry.bind("<Return>", lambda e: _add_ticker())
tk.Button(add_frame, text="+ Add", font=("Courier New", 7), bg=BG_INPUT,
          fg=ACCENT, relief="flat", padx=4, cursor="hand2",
          command=_add_ticker).pack(side="left")

list_frame = tk.Frame(sidebar, bg=BG_INPUT)
list_frame.pack(fill="x", padx=12, pady=(0, 4))

# Scrollbar para a listbox de ativos (o Ibovespa tem ~90 tickers)
list_scroll = tk.Scrollbar(list_frame, orient="vertical", bg=BG_INPUT,
                            troughcolor=BG_SIDE, width=10)
ticker_listbox = tk.Listbox(list_frame, selectmode="multiple",
                             font=("Courier New", 9), bg=BG_INPUT, fg=FG,
                             selectbackground="#2a3550", selectforeground="#e2e8f0",
                             relief="flat", bd=0, height=12, activestyle="none",
                             exportselection=False,
                             yscrollcommand=list_scroll.set)
list_scroll.config(command=ticker_listbox.yview)
list_scroll.pack(side="right", fill="y")
ticker_listbox.pack(side="left", fill="both", expand=True)

# Popula com a lista completa de tickers; pré-seleciona os 5 iniciais
for t in sorted(TICKERS_DEFAULT):
    ticker_listbox.insert("end", t)
for i, t in enumerate(sorted(TICKERS_DEFAULT)):
    if t in TICKERS_SELECAO_INICIAL:
        ticker_listbox.selection_set(i)

_section_label(sidebar, "PERÍODO HISTÓRICO")
_radio_row(sidebar, periodo_var, [(k, k) for k in PERIODOS])

_section_label(sidebar, "TAXA LIVRE DE RISCO (% a.a.)")
rf_entry = tk.Entry(sidebar, textvariable=rf_var,
                    font=("Courier New", 10), bg=BG_INPUT, fg="#e2e8f0",
                    insertbackground="#e2e8f0", relief="flat",
                    highlightthickness=1, highlightbackground="#2a3550")
rf_entry.pack(fill="x", padx=12, pady=(0, 6))
rf_entry.bind("<Return>", lambda e: calcular())

btn_calcular = tk.Button(sidebar, text="▶  Calcular",
                          font=("Courier New", 9, "bold"),
                          bg="#0d4f6e", fg=ACCENT, relief="flat",
                          padx=10, pady=6, cursor="hand2", command=calcular)
btn_calcular.pack(fill="x", padx=12, pady=(14, 4))

btn_relatorio = tk.Button(sidebar, text="⬇  Exportar Relatório",
                           font=("Courier New", 8),
                           bg=BG_INPUT, fg=FG, relief="flat",
                           padx=10, pady=5, cursor="hand2",
                           command=exportar_relatorio, state="disabled")
btn_relatorio.pack(fill="x", padx=12)

# Label de status — guardamos referência para mudar a cor (verde=OK, vermelho=erro)
status_lbl = tk.Label(sidebar, textvariable=status_var, font=("Courier New", 7),
                      bg=BG_SIDE, fg="#ffd700", wraplength=210)
status_lbl.pack(anchor="w", padx=12, pady=(8, 0))

# ── Glossário de indicadores ──────────────────────────────────────────────────
# Painel rolável com definições de cada conceito exibido no app.
# Permite que professor e alunos consultem o significado dos indicadores
# sem precisar de material externo durante a apresentação.

tk.Frame(sidebar, bg="#2a3550", height=1).pack(fill="x", padx=12, pady=(10, 0))
_section_label(sidebar, "GLOSSÁRIO", pady=(6, 2))

# Frame que contém o Text + scrollbar
glos_outer = tk.Frame(sidebar, bg=BG_INPUT)
glos_outer.pack(fill="both", expand=True, padx=12, pady=(0, 8))

glos_scroll = tk.Scrollbar(glos_outer, orient="vertical", bg=BG_INPUT,
                            troughcolor=BG_SIDE, width=8)
glos_text = tk.Text(glos_outer, font=("Courier New", 7), bg=BG_INPUT, fg=FG,
                    relief="flat", bd=0, wrap="word", cursor="arrow",
                    state="normal", yscrollcommand=glos_scroll.set,
                    padx=6, pady=4, spacing1=2, spacing3=4)
glos_scroll.config(command=glos_text.yview)
glos_scroll.pack(side="right", fill="y")
glos_text.pack(side="left", fill="both", expand=True)

# Tag de título de cada conceito (destaque em ciano)
glos_text.tag_config("titulo", foreground=ACCENT, font=("Courier New", 7, "bold"))
# Tag do corpo da definição (texto normal)
glos_text.tag_config("corpo",  foreground=FG,     font=("Courier New", 7))

# Insere cada entrada do glossário no widget Text
for nome, descricao in GLOSSARIO:
    glos_text.insert("end", f"{nome}\n", "titulo")
    glos_text.insert("end", f"{descricao}\n\n", "corpo")

# Torna o widget somente-leitura após inserção (evita edição acidental)
glos_text.config(state="disabled")

# ── Área principal ────────────────────────────────────────────────────────────
main_frame = tk.Frame(root, bg=BG)
main_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

# Canvas do gráfico da fronteira eficiente
c = tk.Canvas(main_frame, bg="#141926", highlightthickness=0, cursor="crosshair")
c.pack(fill="both", expand=True)
c.bind("<Configure>", lambda e: desenhar())

# Separador visual entre gráfico e tabela
tk.Frame(main_frame, bg="#1e2535", height=1).pack(fill="x", pady=(4, 0))

# Painel da tabela de pesos (altura fixa)
table_outer = tk.Frame(main_frame, bg=BG, height=145)
table_outer.pack(fill="x", pady=(4, 0))
table_outer.pack_propagate(False)

table_inner = tk.Frame(table_outer, bg=BG)
table_inner.pack(anchor="w", padx=4, pady=2)
_build_table(table_inner)


# =============================================================================
#  BUSCA DOS TICKERS DO IBOVESPA EM BACKGROUND
# =============================================================================

def _fetch_ibovespa_tickers():
    """
    Busca a composição atual do Ibovespa via API pública da B3 e atualiza
    a listbox em background. Mantém os tickers default como fallback.
    """
    import base64
    import json
    import urllib.request

    try:
        payload = base64.b64encode(
            json.dumps({"language": "pt-br", "pageNumber": 1,
                        "pageSize": 120, "index": "IBOV", "segment": "1"}).encode()
        ).decode()
        url = ("https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall"
               f"/GetPortfolioDay/{payload}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        tickers = sorted(item["cod"].strip() for item in data.get("results", []))
        if tickers:
            def _update():
                # Preserva a seleção atual ao recarregar a lista
                selected = {ticker_listbox.get(i)
                            for i in ticker_listbox.curselection()}
                ticker_listbox.delete(0, "end")
                for t in tickers:
                    ticker_listbox.insert("end", t)
                for i, t in enumerate(tickers):
                    if t in selected or t in TICKERS_SELECAO_INICIAL:
                        ticker_listbox.selection_set(i)
            root.after(0, _update)
    except Exception:
        pass   # mantém os tickers default silenciosamente


threading.Thread(target=_fetch_ibovespa_tickers, daemon=True).start()

root.mainloop()
