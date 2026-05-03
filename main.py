"""
=============================================================================
  ANÁLISE FUNDAMENTALISTA DE AÇÕES — main_brapi.py
=============================================================================

VISÃO GERAL
-----------
Aplicativo desktop (tkinter) para análise histórica de indicadores
fundamentalistas de ações brasileiras, usando a API Brapi (brapi.dev).

O usuário escolhe um ativo do Ibovespa (grande parte dos indicadores não estarão completamente
disponíveis na versão gratuita da API Brapi, porém a VALE3 possui, então recomendamos usa-la de teste),
seleciona um ou mais indicadores e um período histórico. O app busca os dados, 
calcula as séries temporais e plota tudo em um gráfico interativo.

FLUXO DE DADOS
--------------
1. Busca de preço histórico diário via  GET /api/quote/{ticker}
   → parâmetros: range (ex.: "5y"), interval="1d"
   → campo usado: historicalDataPrice[].close  (preço não ajustado por dividendos)

2. Busca de fundamentos via  GET /api/quote/{ticker}?modules=...
   → módulos: incomeStatementHistoryQuarterly, balanceSheetHistoryQuarterly,
              incomeStatementHistory, balanceSheetHistory, defaultKeyStatistics
   → até 60 trimestres (~15 anos) ou 16 anos de dados anuais disponíveis

3. Para cada período fiscal (trimestre ou ano), calcula o denominador do
   indicador (ex.: EPS para P/L, patrimônio/ação para P/VP).

4. Para cada dia de pregão, associa o denominador do período fiscal mais
   recente já encerrado (bisect) e calcula o indicador final.

INDICADORES
-----------
  Calculados (price-based):
    Preço da Cota  → close direto do histórico
    P/L            → preço / LPA_TTM           (LPA = lucro líquido / ações)
    P/VP           → preço / (PL / ações)      (PL = patrimônio líquido)
    EV/EBIT        → (preço × ações + dívida − caixa) / EBIT_TTM
    EV/EBITDA      → (preço × ações + dívida − caixa) / EBITDA_TTM

  Base (mostram o fundamento em si, sem divisão pelo preço):
    LPA            → lucro líquido TTM / ações  (R$/ação)
    Lucro Líquido  → lucro líquido TTM           (R$ bilhões)
    EBIT           → EBIT TTM                    (R$ bilhões)
    EBITDA         → EBITDA TTM                  (R$ bilhões)
    VPA            → patrimônio líquido / ações  (R$/ação)

  TTM (Trailing Twelve Months): soma dos últimos 4 trimestres. Se algum
  trimestre estiver faltando, usa a média dos disponíveis como substituto.

MODO TRIMESTRAL vs ANUAL
------------------------
  Trimestral → usa quarterly_financials; o denominador é recalculado a cada
               trimestre com TTM (4 períodos somados).
  Anual      → usa financials anuais; cada entrada já representa 1 ano completo.

LIMITAÇÕES DO PLANO BRAPI
--------------------------
  Alguns tickers só permitem histórico curto (até 3mo) no plano atual.
  O app faz fallback automático: tenta 5y → 2y → 1y → 6mo → 3mo até obter dados.
  Tickers premium (VALE3, PETR4, ITUB4) funcionam com histórico completo.

INTERFACE
---------
  Sidebar (esquerda):
    • Campo de texto com autocomplete dos tickers do Ibovespa (B3 API)
    • Checkboxes para selecionar múltiplos indicadores
    • Radiobuttons para período histórico (1A–20A) e modo (Trim./Anual)
    • Botão "Carregar" → busca em thread separada para não travar a UI
    • Botão "Resetar linha" → limpa cursor e linha de referência

  Canvas (direita):
    • Clique/arrastar → posiciona cursor vertical (data) + linha horizontal (valor)
    • Cursor mostra o valor exato de cada indicador na data apontada
    • Linha horizontal mostra o valor de referência e % do histórico acima/abaixo
    • Com 1 indicador: área preenchida + eixo Y com valores absolutos
    • Com múltiplos: cada série tem sua própria escala Y independente

ESTADO GLOBAL
-------------
  series     → dict {indicador: (dates, values)} com os dados carregados
  linha_ref  → fração Y 0..1 da linha de referência horizontal (None = oculta)
  cursor_idx → fração X 0..1 do cursor vertical (None = oculto)
=============================================================================
"""

import tkinter as tk
import threading
import bisect
import datetime
import json
import urllib.request
import urllib.parse


# =============================================================================
#  CONFIGURAÇÃO
# =============================================================================

# TOKEN PESSOAL BRAPI (vou deixar o meu de exemplo, já que é uma API gratuita)
BRAPI_TOKEN = "ugC55N8Ha3k1KNR73VtX4q"
BRAPI_BASE  = "https://brapi.dev/api"

# Ordem de exibição na sidebar
INDICADORES = [
    "Preço da Cota",
    "P/VP", "P/L", "EV/EBIT", "EV/EBITDA",   # indicadores calculados
    "LPA", "Lucro Líquido", "EBIT", "EBITDA", "VPA",  # indicadores base
]

# Cor de cada indicador no gráfico
CORES_IND = {
    "Preço da Cota": "#00e5ff",
    "P/VP":          "#ff6b6b",
    "P/L":           "#51cf66",
    "EV/EBIT":       "#ffd700",
    "EV/EBITDA":     "#cc5de8",
    "LPA":           "#f59f00",
    "Lucro Líquido": "#20c997",
    "EBIT":          "#a9e34b",
    "EBITDA":        "#74c0fc",
    "VPA":           "#e599f7",
}

# Indicadores que retornam o fundamento diretamente (sem divisão pelo preço)
IND_BASE = {"LPA", "Lucro Líquido", "EBIT", "EBITDA", "VPA"}

# Mapeamento de label → parâmetro "range" da Brapi
HIST_PERIODS = {"1A": "1y", "2A": "2y", "5A": "5y", "10A": "10y", "20A": "max"}

# Fallback de ranges quando o plano não suporta o range solicitado
_RANGE_FALLBACKS = ["5y", "2y", "1y", "6mo", "3mo"]


# =============================================================================
#  CAMADA DE ACESSO À API BRAPI
# =============================================================================

def _brapi_get(path, params=None):
    """Faz GET na Brapi e retorna o JSON. Lança ValueError em caso de erro da API."""
    p = dict(params or {})
    p["token"] = BRAPI_TOKEN
    url = f"{BRAPI_BASE}/{path}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    if data.get("error"):
        raise ValueError(data.get("message", "brapi error"))
    return data


def _fetch_price_history(ticker, hist_period):
    """
    Busca o histórico de preços diários. Se o plano não suportar o range
    solicitado (HTTP 400), tenta ranges menores em ordem decrescente.
    Retorna a lista bruta de dicts ou [] se nenhum range funcionar.
    """
    # Monta a sequência de ranges a tentar, começando pelo solicitado
    ranges = [hist_period]
    try:
        ranges += _RANGE_FALLBACKS[_RANGE_FALLBACKS.index(hist_period) + 1:]
    except ValueError:
        ranges += _RANGE_FALLBACKS  # hist_period não está na lista padrão

    for rng in ranges:
        try:
            raw  = _brapi_get(f"quote/{ticker}", {"range": rng, "interval": "1d"})
            rows = raw["results"][0].get("historicalDataPrice", [])
            if rows:
                if rng != hist_period:
                    print(f"[brapi] {ticker}: {hist_period} indisponível no plano → usando {rng}")
                return rows
        except Exception:
            continue  # tenta o próximo range
    return []


def _parse_price_rows(rows):
    """
    Converte a lista bruta de preços da Brapi em [(date, close), ...] ordenado
    por data ascendente. O campo "date" pode ser Unix timestamp (int) ou string.
    """
    hist = []
    for p in rows:
        if p.get("close") is None:
            continue
        ts = p["date"]
        d  = (datetime.date.fromtimestamp(ts) if isinstance(ts, (int, float))
              else datetime.date.fromisoformat(str(ts)[:10]))
        hist.append((d, float(p["close"])))
    hist.sort()
    return hist


def _parse_statements(lst):
    """
    Converte uma lista de demonstrativos financeiros (DRE ou balanço) em
    {date: dict_campos}. O campo "endDate" é a data de encerramento do período.
    """
    out = {}
    for s in lst:
        raw_date = s.get("endDate", "")
        if not raw_date:
            continue
        out[datetime.date.fromisoformat(str(raw_date)[:10])] = s
    return out


def _nearest_bal(bal_sorted, bal, fd):
    """
    Retorna o balanço patrimonial mais recente cujo encerramento seja <= fd.
    Necessário porque DRE e balanço podem não ter exatamente as mesmas datas.
    """
    if not bal_sorted:
        return {}
    i = bisect.bisect_right(bal_sorted, fd) - 1
    return bal[bal_sorted[i]] if i >= 0 else {}


def _ttm(inc, fin_dates, field, i):
    """
    Trailing Twelve Months: soma os valores de 'field' nos até 4 trimestres
    que encerram no índice i. Períodos com valor None são preenchidos com a
    média dos disponíveis, evitando distorção por dados faltantes.
    """
    window = fin_dates[max(0, i - 3): i + 1]   # janela de até 4 trimestres
    vals   = [inc[d].get(field) for d in window]
    valids = [v for v in vals if v is not None]
    if not valids:
        return None
    mean = sum(valids) / len(valids)
    return sum(v if v is not None else mean for v in vals)


# =============================================================================
#  CÁLCULO DOS INDICADORES
# =============================================================================

def fetch_indicator_series(ticker_sym, indicator, periodo="Trimestral", hist_period="5y"):
    """
    Retorna (dates, values) — duas listas paralelas de datetime.date e float —
    com a série histórica diária do indicador para o ticker, ou None em falha.

    Para indicadores calculados (P/L, P/VP, EV/*):
      - O denominador é calculado por período fiscal e mantido constante
        até o próximo período (step function no tempo).
      - Para cada dia de pregão, usa bisect para encontrar o período fiscal
        mais recente já encerrado (não usa dados futuros).

    Para indicadores base (LPA, Lucro Líquido, EBIT, EBITDA, VPA):
      - O valor do fundamento é propagado da mesma forma, sem divisão pelo preço.
    """
    try:
        # Brapi não usa sufixo .SA
        ticker = ticker_sym.upper().replace(".SA", "")

        # ── 1. Preço histórico ─────────────────────────────────────────────
        rows = _fetch_price_history(ticker, hist_period)
        hist = _parse_price_rows(rows)
        if not hist:
            return None

        # Preço da Cota não precisa de fundamentos
        if indicator == "Preço da Cota":
            return ([d for d, _ in hist], [v for _, v in hist])

        # ── 2. Fundamentos ─────────────────────────────────────────────────
        # Uma única requisição traz DRE + balanço trimestral/anual + key stats
        modules = ("incomeStatementHistoryQuarterly,balanceSheetHistoryQuarterly,"
                   "incomeStatementHistory,balanceSheetHistory,defaultKeyStatistics")
        fund   = _brapi_get(f"quote/{ticker}", {"modules": modules})["results"][0]
        ks     = fund.get("defaultKeyStatistics", {})
        # Número de ações usado como constante (sem histórico disponível na Brapi)
        shares = ks.get("sharesOutstanding") or 1

        # Seleciona fonte trimestral ou anual conforme o modo escolhido
        if periodo == "Trimestral":
            inc = _parse_statements(fund.get("incomeStatementHistoryQuarterly", []))
            bal = _parse_statements(fund.get("balanceSheetHistoryQuarterly", []))
        else:
            inc = _parse_statements(fund.get("incomeStatementHistory", []))
            bal = _parse_statements(fund.get("balanceSheetHistory", []))

        if not inc:
            return None

        fin_dates  = sorted(inc.keys())
        bal_sorted = sorted(bal.keys())

        # ── 3. Denominador por período fiscal ──────────────────────────────
        q_denom = {}  # {data_encerramento: valor_denominador}
        q_ev    = {}  # {data_encerramento: (dívida, caixa)} — só para EV/*

        for i, fd in enumerate(fin_dates):
            # No modo trimestral precisamos de pelo menos 4 períodos para TTM
            if periodo == "Trimestral" and i < 3:
                continue
            try:
                row_i = inc[fd]
                row_b = _nearest_bal(bal_sorted, bal, fd)

                # get_ abstrai TTM (trimestral) vs valor direto (anual)
                get_ = (lambda field: _ttm(inc, fin_dates, field, i)
                        if periodo == "Trimestral"
                        else lambda field: row_i.get(field))

                if indicator == "P/L":
                    # EPS = lucro líquido TTM / número de ações
                    ni = get_("netIncome")
                    if ni and shares:
                        eps = ni / shares
                        if eps > 0:           # ignora períodos com prejuízo
                            q_denom[fd] = eps

                elif indicator == "P/VP":
                    # VPA = patrimônio líquido / número de ações
                    eq = row_b.get("totalStockholderEquity")
                    if eq and eq > 0 and shares:
                        q_denom[fd] = eq / shares

                elif indicator in ("EV/EBIT", "EV/EBITDA"):
                    # EV = market cap + dívida líquida
                    debt = (row_b.get("longTermDebt") or 0) + (row_b.get("shortLongTermDebt") or 0)
                    cash = row_b.get("cash") or 0
                    q_ev[fd] = (float(debt), float(cash))
                    field = "ebit" if indicator == "EV/EBIT" else "cleanEbitda"
                    v = get_(field)
                    if v and v > 0:
                        q_denom[fd] = v

                elif indicator == "LPA":
                    # Lucro Por Ação (TTM) em R$/ação
                    ni = get_("netIncome")
                    if ni is not None and shares:
                        q_denom[fd] = ni / shares

                elif indicator == "Lucro Líquido":
                    # Lucro líquido TTM em bilhões de R$
                    ni = get_("netIncome")
                    if ni is not None:
                        q_denom[fd] = ni / 1e9

                elif indicator == "EBIT":
                    # EBIT TTM em bilhões de R$
                    v = get_("ebit")
                    if v is not None:
                        q_denom[fd] = v / 1e9

                elif indicator == "EBITDA":
                    # EBITDA TTM em bilhões de R$ (campo "cleanEbitda" da Brapi)
                    v = get_("cleanEbitda")
                    if v is not None:
                        q_denom[fd] = v / 1e9

                elif indicator == "VPA":
                    # Valor Patrimonial por Ação em R$/ação
                    eq = row_b.get("totalStockholderEquity")
                    if eq is not None and shares:
                        q_denom[fd] = eq / shares

            except Exception:
                continue   # ignora períodos com dados incompletos

        if not q_denom:
            return None

        # ── 4. Mapeamento diário: cada dia → período fiscal mais recente ───
        sorted_q       = sorted(q_denom.keys())
        dates, values  = [], []

        for hd, price in hist:
            # bisect_right devolve o índice do primeiro período APÓS hd,
            # então i-1 é o último período já encerrado nessa data
            i = bisect.bisect_right(sorted_q, hd) - 1
            if i < 0:
                continue   # nenhum período disponível antes dessa data
            last_q = sorted_q[i]
            denom  = q_denom[last_q]

            if indicator in ("P/L", "P/VP"):
                dates.append(hd)
                values.append(price / denom)

            elif indicator in ("EV/EBIT", "EV/EBITDA"):
                debt, cash = q_ev.get(last_q, (0.0, 0.0))
                ev = price * shares + debt - cash
                dates.append(hd)
                values.append(ev / denom)

            elif indicator in IND_BASE:
                # Indicadores base: o valor do fundamento é exibido diretamente
                dates.append(hd)
                values.append(denom)

        return (dates, values) if len(values) >= 2 else None

    except Exception as e:
        print(f"[brapi] ERROR {ticker_sym} {indicator}: {e}")
        return None


# =============================================================================
#  ESTADO GLOBAL DA UI
# =============================================================================

root = tk.Tk()
root.title("Análise Fundamentalista")
root.geometry("980x600")
root.configure(bg="#0f1117")

# Variáveis de controle dos widgets da sidebar
ticker_var       = tk.StringVar(value="VALE3")
indicadores_vars = {ind: tk.BooleanVar(value=(ind == "Preço da Cota")) for ind in INDICADORES}
periodo_var      = tk.StringVar(value="Trimestral")
periodo_hist_var = tk.StringVar(value="5A")
status_var       = tk.StringVar(value="")

# Dados carregados: {indicador: (dates_list, values_list)}
series = {}

# Posição do cursor e da linha de referência como frações 0..1 do canvas
# (None = não exibido). Fração 0 = esquerda/topo, 1 = direita/base.
linha_ref  = None
cursor_idx = None


# =============================================================================
#  HELPERS DE DESENHO (canvas tkinter)
# =============================================================================

def _fmt_date(d, span_days):
    """Formata uma data para o eixo X: apenas ano se > 3 anos, mês/ano se > 6 meses."""
    if span_days > 365 * 3:
        return d.strftime("%Y")
    elif span_days > 180:
        return d.strftime("%m/%Y")
    return d.strftime("%d/%m")


def _draw_x_axis(cv, date_min, span_days, x0, x1, y1):
    """Desenha marcações de data no eixo X, espaçadas uniformemente."""
    n = max(2, min(8, (x1 - x0) // 90))   # entre 2 e 8 labels conforme largura
    for k in range(n + 1):
        d  = date_min + datetime.timedelta(days=round(k / n * span_days))
        lx = x0 + (d - date_min).days / span_days * (x1 - x0)
        cv.create_line(lx, y1, lx, y1 + 4, fill="#555e72")
        cv.create_text(lx, y1 + 6, text=_fmt_date(d, span_days),
                       font=("Courier New", 7), fill="#555e72", anchor="n")


def _draw_h_grid(cv, x0, x1, y0, y1, vmin, vmax):
    """Desenha 5 linhas horizontais de grade com os valores do eixo Y à esquerda."""
    span = vmax - vmin if vmax != vmin else 1
    for k in range(5):
        gy = y0 + k * (y1 - y0) / 4
        gv = vmax - k * span / 4
        cv.create_line(x0, gy, x1, gy, fill="#1e2535", dash=(3, 5))
        cv.create_text(x0 - 4, gy, text=f"{gv:.2f}",
                       font=("Courier New", 8), fill="#555e72", anchor="e")


def _draw_legend(cv, items, cores, x0, y0, legend_rows):
    """Desenha a legenda acima do gráfico com quadradinho colorido + nome."""
    for i, key in enumerate(items):
        lx = x0 + 6
        ly = y0 - 12 - (legend_rows - 1 - i) * 14
        cv.create_rectangle(lx, ly + 1, lx + 10, ly + 9, fill=cores[key], outline="")
        cv.create_text(lx + 14, ly + 5, text=key,
                       font=("Courier New", 8), fill="#94a3b8", anchor="w")


def _draw_ref_line(cv, linha_ref, x0, x1, y0, y1, series_items, cores):
    """
    Desenha a linha horizontal de referência (amarela).
    linha_ref é uma fração Y 0..1; converte para pixel e depois para o valor
    real de cada indicador usando sua própria escala.
    Com 1 indicador: mostra valor + % acima/abaixo.
    Com múltiplos: mostra uma linha e o valor de cada indicador à direita.
    """
    if linha_ref is None:
        return
    by = y0 + linha_ref * (y1 - y0)   # pixel Y da linha
    cv.create_line(x0, by, x1, by, fill="#ffd700", width=1, dash=(8, 4))
    lbl_y = by - 8
    for ind, dates, s in series_items:
        # Reconstrói a escala deste indicador para converter fração → valor
        vmin_i  = min(s) * 0.97
        vmax_i  = max(s) * 1.03
        span_i  = vmax_i - vmin_i if vmax_i != vmin_i else 1
        ref_val = vmax_i - linha_ref * span_i   # valor na altura da linha
        acima   = sum(1 for v in s if v > ref_val) / len(s) * 100
        if len(series_items) == 1:
            cv.create_text(x1 - 2, lbl_y, text=f"ref: {ref_val:.2f}",
                           font=("Courier New", 8), fill="#ffd700", anchor="e")
            cv.create_text(x0 + 4, by - 10, text=f"↑ {acima:.0f}%",
                           font=("Courier New", 8), fill="#00ff88", anchor="w")
            cv.create_text(x0 + 4, by + 10, text=f"↓ {100 - acima:.0f}%",
                           font=("Courier New", 8), fill="#ff4466", anchor="w")
        else:
            cv.create_text(x1 - 2, lbl_y,
                           text=f"{ind}: {ref_val:.2f}  ↑{acima:.0f}%",
                           font=("Courier New", 7), fill=cores[ind], anchor="e")
            lbl_y -= 11   # empilha os labels de cada indicador


def _draw_cursor(cv, cursor_idx, date_min, span_days, x0, x1, y0, y1,
                 series_items, py_fns, cores):
    """
    Desenha o cursor vertical (linha branca tracejada) e os labels de valor.
    cursor_idx é uma fração X 0..1; converte para data e depois para pixel.
    Usa bisect para encontrar o ponto mais próximo em cada série.
    O label troca de lado quando o cursor está na metade direita do gráfico.
    """
    if cursor_idx is None:
        return
    target  = date_min + datetime.timedelta(days=round(cursor_idx * span_days))
    cx_     = x0 + (target - date_min).days / span_days * (x1 - x0)
    right   = cx_ > (x0 + x1) / 2   # cursor na metade direita?
    lbl_x   = cx_ - 6 if right else cx_ + 6
    lbl_anc = "e" if right else "w"

    cv.create_line(cx_, y0, cx_, y1, fill="#ffffff", width=1, dash=(4, 4))

    if len(series_items) == 1:
        ind, dates, s = series_items[0]
        ci  = max(0, min(len(s) - 1, bisect.bisect_left(dates, target)))
        cy_ = py_fns[ind](s[ci])
        cv.create_oval(cx_ - 4, cy_ - 4, cx_ + 4, cy_ + 4,
                       fill="#ffffff", outline="#0f1117", width=2)
        cv.create_text(lbl_x, y0 - 4, text=f"{dates[ci]}  {s[ci]:.2f}",
                       font=("Courier New", 8), fill="#ffffff",
                       anchor="se" if right else "sw")
    else:
        label_y = y0 + 4
        for ind, dates, s in series_items:
            color = cores[ind]
            if target < dates[0]:
                # Cursor antes do início desta série
                cv.create_text(lbl_x, label_y,
                               text=f"{ind}: sem dados  ({target})",
                               font=("Courier New", 8), fill="#555e72", anchor=lbl_anc)
            else:
                ci    = min(bisect.bisect_right(dates, target), len(s) - 1)
                dot_y = py_fns[ind](s[ci])
                cv.create_oval(cx_ - 3, dot_y - 3, cx_ + 3, dot_y + 3,
                               fill=color, outline="#0f1117", width=1)
                cv.create_text(lbl_x, label_y,
                               text=f"{ind}: {s[ci]:.2f}  ({dates[ci]})",
                               font=("Courier New", 8), fill=color, anchor=lbl_anc)
            label_y += 14


# =============================================================================
#  GRÁFICO PRINCIPAL
# =============================================================================

def desenhar():
    """
    Redesenha o canvas completamente a partir do estado global (series,
    linha_ref, cursor_idx). Chamado após cada interação do usuário e ao
    redimensionar a janela.

    Layout do canvas:
      - Margens: esquerda 60px (eixo Y), direita 15px, topo variável
        (14px × nº de indicadores para a legenda), baixo 44px (eixo X).
      - Escala X: temporal, proporcional ao span total em dias.
      - Escala Y: independente por indicador (cada série ocupa todo o eixo).
    """
    c.delete("all")
    active = {ind: dv for ind, dv in series.items() if dv and len(dv[1]) > 0}
    W, H   = c.winfo_width(), c.winfo_height()
    if W < 10 or H < 10:
        return
    if not active:
        c.create_text(W // 2, H // 2,
                      text="Selecione indicadores e clique em Carregar",
                      font=("Courier New", 11), fill="#4a5568")
        return

    items       = [(ind, dv[0], dv[1]) for ind, dv in active.items()]
    legend_rows = len(items)

    # Margens do canvas
    ml, mr, mt, mb = 60, 15, 15 + legend_rows * 14, 44
    x0, y0, x1, y1 = ml, mt, W - mr, H - mb

    # Intervalo temporal global (união de todas as séries)
    all_dates = [d for _, dates, _ in items for d in dates]
    date_min  = min(all_dates)
    date_max  = max(all_dates)
    span_days = max((date_max - date_min).days, 1)

    # px: converte date → pixel X
    def px(d):
        return x0 + (d - date_min).days / span_days * (x1 - x0)

    # py_fns: para cada indicador, função que converte valor → pixel Y
    # Cada série ocupa o range completo do eixo Y (escala independente)
    py_fns = {}
    for ind, dates, s in items:
        vmin = min(s) * 0.97
        vmax = max(s) * 1.03
        span = vmax - vmin if vmax != vmin else 1
        py_fns[ind] = lambda v, vm=vmin, sp=span: y1 - (v - vm) / sp * (y1 - y0)

    # Com 1 indicador: grade com valores no eixo Y; com múltiplos: só linhas
    if len(items) == 1:
        ind, dates, s = items[0]
        _draw_h_grid(c, x0, x1, y0, y1, min(s) * 0.97, max(s) * 1.03)
    else:
        for k in range(5):
            gy = y0 + k * (y1 - y0) / 4
            c.create_line(x0, gy, x1, gy, fill="#1e2535", dash=(3, 5))

    # Desenha cada série
    for ind, dates, s in items:
        color = CORES_IND[ind]
        py    = py_fns[ind]

        if len(items) == 1:
            # Área preenchida sob a curva (só no modo single)
            pts = [px(dates[0]), y1]
            for i, v in enumerate(s):
                pts += [px(dates[i]), py(v)]
            pts += [px(dates[-1]), y1]
            c.create_polygon(*pts, fill="#0d2535", outline="")

        # Linha da série
        pts = []
        for i, v in enumerate(s):
            pts += [px(dates[i]), py(v)]
        c.create_line(*pts, fill=color, width=2, smooth=True)

        # Ponto no valor mais recente
        lx, ly = px(dates[-1]), py(s[-1])
        c.create_oval(lx - 4, ly - 4, lx + 4, ly + 4,
                      fill=color, outline="#0f1117", width=2)

        # No modo multi, mostra o valor atual à esquerda do eixo Y
        if len(items) > 1:
            c.create_text(x0 - 4, ly, text=f"{s[-1]:.2f}",
                          font=("Courier New", 7), fill=color, anchor="e")

    _draw_ref_line(c, linha_ref, x0, x1, y0, y1, items, CORES_IND)
    _draw_cursor(c, cursor_idx, date_min, span_days, x0, x1, y0, y1,
                 items, py_fns, CORES_IND)
    _draw_x_axis(c, date_min, span_days, x0, x1, y1)
    _draw_legend(c, [ind for ind, _, _ in items], CORES_IND, x0, y0, legend_rows)


# =============================================================================
#  CARREGAMENTO DE DADOS
# =============================================================================

def carregar():
    """
    Lê as configurações da sidebar e busca os dados em uma thread separada
    para não travar a interface. Ao terminar, atualiza 'series' e redesenha.
    """
    global series, linha_ref, cursor_idx
    selected = [ind for ind, var in indicadores_vars.items() if var.get()]
    if not selected:
        series = {}
        desenhar()
        return

    ticker_sym = ticker_var.get().strip().upper()
    ticker_var.set(ticker_sym)
    status_var.set("Carregando...")
    btn_carregar.config(state="disabled")
    linha_ref  = None   # reseta interações anteriores
    cursor_idx = None

    def _fetch():
        global series
        periodo     = periodo_var.get()
        hist_period = HIST_PERIODS.get(periodo_hist_var.get(), "5y")
        new_series, errors = {}, []
        for ind in selected:
            data = fetch_indicator_series(ticker_sym, ind, periodo, hist_period)
            if data:
                new_series[ind] = data
            else:
                errors.append(ind)
        series = new_series
        msg = f"Sem dados: {', '.join(errors)}" if errors else ""
        root.after(0, lambda: status_var.set(msg))
        root.after(0, lambda: btn_carregar.config(state="normal"))
        root.after(0, desenhar)

    threading.Thread(target=_fetch, daemon=True).start()


# =============================================================================
#  INTERAÇÃO COM O CANVAS (clique e arraste)
# =============================================================================

def _x_frac(cx):
    """Converte pixel X do canvas para fração 0..1 dentro da área do gráfico."""
    x0, x1 = 60, c.winfo_width() - 15
    return max(0.0, min(1.0, (cx - x0) / max(x1 - x0, 1)))


def _y_frac(cy):
    """Converte pixel Y do canvas para fração 0..1 dentro da área do gráfico."""
    active = {ind: dv for ind, dv in series.items() if dv}
    mt = 15 + len(active) * 14 if active else 29
    mb = 44
    y0, y1 = mt, c.winfo_height() - mb
    return max(0.0, min(1.0, (cy - y0) / max(y1 - y0, 1)))


def _on_click(e):
    """Clique no canvas: posiciona cursor vertical + linha horizontal de referência."""
    global linha_ref, cursor_idx
    if not any(dv for dv in series.values() if dv):
        return
    cursor_idx = _x_frac(e.x)
    linha_ref  = _y_frac(e.y)
    desenhar()


def _on_drag(e):
    """Arrastar no canvas: mesmo comportamento do clique, atualiza em tempo real."""
    global linha_ref, cursor_idx
    if not any(dv for dv in series.values() if dv):
        return
    cursor_idx = _x_frac(e.x)
    linha_ref  = _y_frac(e.y)
    desenhar()


# =============================================================================
#  AUTOCOMPLETE DE TICKERS DO IBOVESPA
# =============================================================================

# Lista inicial com fallback; substituída pela composição real do Ibovespa via B3
IBOVESPA = ["VALE3", "PETR4", "ITUB4", "BBDC4", "WEGE3"]


def _fetch_ibovespa():
    """
    Busca a composição atual do Ibovespa na API pública da B3.
    O payload é um JSON codificado em base64 na URL (formato exigido pela B3).
    Atualiza IBOVESPA em background sem bloquear a UI.
    """
    import base64 as _b64
    try:
        payload = _b64.b64encode(
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
            IBOVESPA[:] = tickers
            root.after(0, _update_suggestions)  # atualiza dropdown se aberto
    except Exception:
        pass   # mantém a lista de fallback


threading.Thread(target=_fetch_ibovespa, daemon=True).start()


def _update_suggestions(*_):
    """Filtra IBOVESPA pelo texto digitado e mostra/oculta o dropdown."""
    if root.focus_get() is not ticker_entry:
        return
    texto   = ticker_var.get().upper()
    matches = [t for t in IBOVESPA if texto in t] if texto else []
    sug_menu.delete(0, "end")
    for t in matches:
        sug_menu.insert("end", t)
    if matches:
        sug_frame.place(in_=ticker_entry, x=0, rely=1.0, relwidth=1.0)
        sug_frame.lift()
    else:
        sug_frame.place_forget()


def _on_sug_select(e):
    """Seleciona um ticker do dropdown e fecha o menu."""
    sel = sug_menu.curselection()
    if sel:
        ticker_var.set(sug_menu.get(sel[0]))
    sug_frame.place_forget()


# Dispara _update_suggestions a cada tecla digitada no campo de ticker
ticker_var.trace_add("write", _update_suggestions)


# =============================================================================
#  LAYOUT DA INTERFACE (sidebar + canvas)
# =============================================================================

# Paleta de cores
BG       = "#0f1117"   # fundo principal
BG_SIDE  = "#111520"   # fundo da sidebar
BG_INPUT = "#1e2535"   # fundo de inputs e botões secundários
FG       = "#94a3b8"   # texto padrão
FG_DIM   = "#4a5568"   # labels de seção (dimmed)
ACCENT   = "#00e5ff"   # destaque (botão carregar)

sidebar = tk.Frame(root, bg=BG_SIDE, width=185)
sidebar.pack(side="left", fill="y", padx=(8, 0), pady=8)
sidebar.pack_propagate(False)   # impede que os filhos redimensionem o frame


def _label(parent, text, pady=(10, 4)):
    """Label de seção com estilo padronizado."""
    tk.Label(parent, text=text, font=("Courier New", 8),
             bg=BG_SIDE, fg=FG_DIM).pack(anchor="w", padx=12, pady=pady)


def _radio_row(parent, var, options, font_size=8):
    """Linha de radiobuttons horizontais com estilo de toggle."""
    frame = tk.Frame(parent, bg=BG_SIDE)
    frame.pack(fill="x", padx=12, pady=(0, 4))
    for text, value in options:
        tk.Radiobutton(frame, text=text, variable=var, value=value,
                       font=("Courier New", font_size), bg=BG_SIDE, fg=FG,
                       selectcolor=BG_INPUT, activebackground=BG_SIDE,
                       activeforeground="#e2e8f0", indicatoron=False,
                       relief="flat", padx=4, pady=3, cursor="hand2",
                       ).pack(side="left", fill="x", expand=True)
    return frame


# ── Seção: Empresa ────────────────────────────────────────────────────────────
_label(sidebar, "EMPRESA", pady=(14, 4))

ticker_entry = tk.Entry(sidebar, textvariable=ticker_var,
                        font=("Courier New", 11), bg=BG_INPUT, fg="#e2e8f0",
                        insertbackground="#e2e8f0", relief="flat",
                        highlightthickness=1, highlightbackground="#2a3550")
ticker_entry.pack(fill="x", padx=12, pady=(0, 6))
ticker_entry.bind("<Return>", lambda e: carregar())

# Dropdown de autocomplete (posicionado via .place() abaixo do entry)
sug_frame = tk.Frame(root, bg=BG_INPUT, relief="flat", bd=1)
sug_menu  = tk.Listbox(sug_frame, font=("Courier New", 9), bg=BG_INPUT, fg=FG,
                       selectbackground="#2a3550", selectforeground="#e2e8f0",
                       relief="flat", bd=0, height=6, activestyle="none")
sug_menu.pack(fill="both", expand=True)
sug_menu.bind("<<ListboxSelect>>", _on_sug_select)

# Fecha o dropdown ao clicar fora dele
root.bind_all("<Button-1>",
              lambda e: sug_frame.place_forget()
              if e.widget not in (ticker_entry, sug_menu, sug_frame) else None,
              add="+")

# ── Seção: Indicadores ────────────────────────────────────────────────────────
_label(sidebar, "INDICADORES", pady=(10, 2))
for ind in INDICADORES:
    if ind == "LPA":
        # Separador visual entre indicadores calculados e indicadores base
        tk.Frame(sidebar, bg="#2a3550", height=1).pack(fill="x", padx=12, pady=(6, 2))
    tk.Checkbutton(sidebar, text=ind, variable=indicadores_vars[ind],
                   font=("Courier New", 10), bg=BG_SIDE, fg=FG,
                   selectcolor=BG_INPUT, activebackground=BG_SIDE,
                   activeforeground="#e2e8f0", relief="flat",
                   padx=12, pady=2, anchor="w", cursor="hand2").pack(fill="x")

# ── Seção: Período ────────────────────────────────────────────────────────────
_label(sidebar, "PERÍODO HISTÓRICO", pady=(12, 4))
_radio_row(sidebar, periodo_hist_var, [(k, k) for k in HIST_PERIODS])
_radio_row(sidebar, periodo_var,
           [("Trimestral", "Trimestral"), ("Anual", "Anual")], font_size=9)

# ── Botões de ação ────────────────────────────────────────────────────────────
tk.Button(sidebar, text="▶ Carregar", font=("Courier New", 9, "bold"),
          bg="#0d4f6e", fg=ACCENT, relief="flat", padx=10, pady=6,
          cursor="hand2", command=carregar
          ).pack(fill="x", padx=12, pady=(14, 4))

# Referência ao botão para poder desabilitá-lo durante o carregamento
btn_carregar = sidebar.winfo_children()[-1]

tk.Button(sidebar, text="↺ Resetar linha", font=("Courier New", 8),
          bg=BG_INPUT, fg=FG, relief="flat", padx=10, pady=5, cursor="hand2",
          command=lambda: [globals().update(linha_ref=None, cursor_idx=None), desenhar()]
          ).pack(fill="x", padx=12)

# Label de status (erros de carregamento ou "Carregando...")
tk.Label(sidebar, textvariable=status_var, font=("Courier New", 7),
         bg=BG_SIDE, fg="#ffd700", wraplength=160
         ).pack(anchor="w", padx=12, pady=(8, 0))

# ── Canvas principal ──────────────────────────────────────────────────────────
c = tk.Canvas(root, bg="#141926", highlightthickness=0, cursor="crosshair")
c.pack(side="left", fill="both", expand=True, padx=8, pady=8)
c.bind("<Configure>", lambda e: desenhar())   # redesenha ao redimensionar
c.bind("<Button-1>", _on_click)
c.bind("<B1-Motion>", _on_drag)

# Carrega o indicador padrão ao iniciar
carregar()
root.mainloop()
