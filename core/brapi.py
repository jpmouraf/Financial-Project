import bisect
import base64
import datetime
import json
import urllib.request
import urllib.parse

BRAPI_TOKEN = "ugC55N8Ha3k1KNR73VtX4q"
BRAPI_BASE  = "https://brapi.dev/api"

INDICADORES = [
    "Preço da Cota",
    "P/VP", "P/L", "EV/EBIT", "EV/EBITDA",
    "LPA", "Lucro Líquido", "EBIT", "EBITDA", "VPA",
]

CORES_IND = {
    "Preço da Cota": "#2563eb",
    "P/VP":          "#dc2626",
    "P/L":           "#16a34a",
    "EV/EBIT":       "#d97706",
    "EV/EBITDA":     "#7c3aed",
    "LPA":           "#b45309",
    "Lucro Líquido": "#0891b2",
    "EBIT":          "#65a30d",
    "EBITDA":        "#0369a1",
    "VPA":           "#be185d",
}

IND_BASE = {"LPA", "Lucro Líquido", "EBIT", "EBITDA", "VPA"}

HIST_PERIODS = {"1A": "1y", "2A": "2y", "5A": "5y", "10A": "10y", "20A": "max"}

_RANGE_FALLBACKS = ["5y", "2y", "1y", "6mo", "3mo"]

_IBOV_FALLBACK = ["VALE3", "PETR4", "ITUB4", "BBDC4", "WEGE3"]


def _brapi_get(path, params=None):
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
    ranges = [hist_period]
    try:
        ranges += _RANGE_FALLBACKS[_RANGE_FALLBACKS.index(hist_period) + 1:]
    except ValueError:
        ranges += _RANGE_FALLBACKS

    for rng in ranges:
        try:
            raw  = _brapi_get(f"quote/{ticker}", {"range": rng, "interval": "1d"})
            rows = raw["results"][0].get("historicalDataPrice", [])
            if rows:
                return rows
        except Exception:
            continue
    return []


def _parse_price_rows(rows):
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
    out = {}
    for s in lst:
        raw_date = s.get("endDate", "")
        if not raw_date:
            continue
        out[datetime.date.fromisoformat(str(raw_date)[:10])] = s
    return out


def _nearest_bal(bal_sorted, bal, fd):
    if not bal_sorted:
        return {}
    i = bisect.bisect_right(bal_sorted, fd) - 1
    return bal[bal_sorted[i]] if i >= 0 else {}


def _ttm(inc, fin_dates, field, i):
    window = fin_dates[max(0, i - 3): i + 1]
    vals   = [inc[d].get(field) for d in window]
    valids = [v for v in vals if v is not None]
    if not valids:
        return None
    mean = sum(valids) / len(valids)
    return sum(v if v is not None else mean for v in vals)


def fetch_indicator_series(ticker_sym, indicator, periodo="Trimestral", hist_period="5y"):
    """Returns (dates_list, values_list) or None on failure."""
    try:
        ticker = ticker_sym.upper().replace(".SA", "")

        rows = _fetch_price_history(ticker, hist_period)
        hist = _parse_price_rows(rows)
        if not hist:
            return None

        if indicator == "Preço da Cota":
            return ([d for d, _ in hist], [v for _, v in hist])

        modules = ("incomeStatementHistoryQuarterly,balanceSheetHistoryQuarterly,"
                   "incomeStatementHistory,balanceSheetHistory,defaultKeyStatistics")
        fund   = _brapi_get(f"quote/{ticker}", {"modules": modules})["results"][0]
        ks     = fund.get("defaultKeyStatistics", {})
        shares = ks.get("sharesOutstanding") or 1

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

        q_denom = {}
        q_ev    = {}

        for i, fd in enumerate(fin_dates):
            if periodo == "Trimestral" and i < 3:
                continue
            try:
                row_i = inc[fd]
                row_b = _nearest_bal(bal_sorted, bal, fd)

                get_ = (lambda field: _ttm(inc, fin_dates, field, i)
                        if periodo == "Trimestral"
                        else lambda field: row_i.get(field))

                if indicator == "P/L":
                    ni = get_("netIncome")
                    if ni and shares:
                        eps = ni / shares
                        if eps > 0:
                            q_denom[fd] = eps

                elif indicator == "P/VP":
                    eq = row_b.get("totalStockholderEquity")
                    if eq and eq > 0 and shares:
                        q_denom[fd] = eq / shares

                elif indicator in ("EV/EBIT", "EV/EBITDA"):
                    debt = (row_b.get("longTermDebt") or 0) + (row_b.get("shortLongTermDebt") or 0)
                    cash = row_b.get("cash") or 0
                    q_ev[fd] = (float(debt), float(cash))
                    field = "ebit" if indicator == "EV/EBIT" else "cleanEbitda"
                    v = get_(field)
                    if v and v > 0:
                        q_denom[fd] = v

                elif indicator == "LPA":
                    ni = get_("netIncome")
                    if ni is not None and shares:
                        q_denom[fd] = ni / shares

                elif indicator == "Lucro Líquido":
                    ni = get_("netIncome")
                    if ni is not None:
                        q_denom[fd] = ni / 1e9

                elif indicator == "EBIT":
                    v = get_("ebit")
                    if v is not None:
                        q_denom[fd] = v / 1e9

                elif indicator == "EBITDA":
                    v = get_("cleanEbitda")
                    if v is not None:
                        q_denom[fd] = v / 1e9

                elif indicator == "VPA":
                    eq = row_b.get("totalStockholderEquity")
                    if eq is not None and shares:
                        q_denom[fd] = eq / shares

            except Exception:
                continue

        if not q_denom:
            return None

        sorted_q      = sorted(q_denom.keys())
        dates, values = [], []

        for hd, price in hist:
            i = bisect.bisect_right(sorted_q, hd) - 1
            if i < 0:
                continue
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
                dates.append(hd)
                values.append(denom)

        return (dates, values) if len(values) >= 2 else None

    except Exception as e:
        print(f"[brapi] ERROR {ticker_sym} {indicator}: {e}")
        return None


def fetch_ibovespa_tickers():
    """Returns sorted list of current Ibovespa tickers from B3 API."""
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
        return tickers if tickers else _IBOV_FALLBACK
    except Exception:
        return _IBOV_FALLBACK
