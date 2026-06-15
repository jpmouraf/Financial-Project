import io
import math
import datetime
import sys
import os

import numpy as np
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file

sys.path.insert(0, os.path.dirname(__file__))

from core.brapi import (fetch_indicator_series, fetch_ibovespa_tickers,
                        INDICADORES, CORES_IND, HIST_PERIODS)
from core.portfolio import (fetch_prices, fetch_prices_range,
                             fetch_market_returns, fetch_market_range,
                             annualize, compute_efficient_frontier,
                             compute_max_sharpe, compute_min_vol, compute_naive,
                             compute_capm_betas, simulate_portfolio,
                             compute_metricas_oos, gerar_relatorio_str,
                             TICKERS_DEFAULT, TICKERS_SELECAO_INICIAL,
                             PERIODOS, RF_DEFAULT, GLOSSARIO, SETORES)

app = Flask(__name__)


# ── JSON serialization ────────────────────────────────────────────────────────

class _JSONEncoder(app.json_provider_class):
    def default(self, obj):
        if isinstance(obj, datetime.date):
            return obj.isoformat()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return super().default(obj)


app.json_provider_class = _JSONEncoder
app.json = _JSONEncoder(app)


# ── Page routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('t1'))


@app.route('/t1')
def t1():
    return render_template('t1.html',
                           indicadores=INDICADORES,
                           cores=CORES_IND,
                           hist_periods=list(HIST_PERIODS.keys()))


@app.route('/t2')
def t2():
    return render_template('t2.html',
                           tickers_default=TICKERS_DEFAULT,
                           tickers_inicial=TICKERS_SELECAO_INICIAL,
                           periodos=list(PERIODOS.keys()),
                           rf_default=RF_DEFAULT,
                           glossario=GLOSSARIO,
                           setores=SETORES)


@app.route('/playground')
def playground():
    return render_template('playground.html',
                           tickers_default=TICKERS_DEFAULT,
                           tickers_inicial=TICKERS_SELECAO_INICIAL,
                           rf_default=RF_DEFAULT,
                           setores=SETORES)


# ── API: shared ───────────────────────────────────────────────────────────────

@app.route('/api/tickers')
def api_tickers():
    return jsonify(fetch_ibovespa_tickers())


# ── API: T1 ───────────────────────────────────────────────────────────────────

@app.route('/api/t1/series', methods=['POST'])
def api_t1_series():
    data        = request.json or {}
    ticker      = data.get('ticker', 'VALE3').strip().upper()
    indicators  = data.get('indicators', [])
    periodo     = data.get('periodo', 'Trimestral')
    hist_period = HIST_PERIODS.get(data.get('hist_period', '5A'), '5y')

    result, errors = {}, []
    for ind in indicators:
        series = fetch_indicator_series(ticker, ind, periodo, hist_period)
        if series:
            dates, values = series
            result[ind] = {
                'dates':  [d.isoformat() for d in dates],
                'values': values,
                'color':  CORES_IND.get(ind, '#2563eb'),
            }
        else:
            errors.append(ind)

    return jsonify({'series': result, 'errors': errors})


# ── API: T2 ───────────────────────────────────────────────────────────────────

@app.route('/api/t2/calcular', methods=['POST'])
def api_t2_calcular():
    data    = request.json or {}
    tickers = data.get('tickers', [])
    periodo = data.get('periodo', '5A')
    rf      = float(data.get('rf', RF_DEFAULT)) / 100

    if len(tickers) < 2:
        return jsonify({'error': 'Selecione ao menos 2 ativos.'}), 400

    try:
        returns    = fetch_prices(tickers, period=PERIODOS.get(periodo, '5y'))
        market     = fetch_market_returns(period=PERIODOS.get(periodo, '5y'))
        tickers_ok = list(returns.columns)
        mu, S      = annualize(returns)

        sh_w, sh_v, sh_r, sh_s = compute_max_sharpe(mu, S, rf)
        mv_w, mv_v, mv_r, mv_s = compute_min_vol(mu, S, rf)
        nv_w, nv_v, nv_r, nv_s = compute_naive(tickers_ok, mu, S, rf)

        return jsonify({
            'tickers':    tickers_ok,
            'periodo':    periodo,
            'rf':         rf,
            'frontier':   compute_efficient_frontier(mu, S),
            'sharpe':     {'pesos': sh_w, 'vol': sh_v, 'ret': sh_r, 'sharpe': sh_s},
            'minvol':     {'pesos': mv_w, 'vol': mv_v, 'ret': mv_r, 'sharpe': mv_s},
            'naive':      {'pesos': nv_w, 'vol': nv_v, 'ret': nv_r, 'sharpe': nv_s},
            'betas':      compute_capm_betas(returns, market, rf_annual=rf),
            'asset_vols': {t: math.sqrt(float(S.loc[t, t])) for t in tickers_ok},
            'asset_rets': {t: float(mu[t]) for t in tickers_ok},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/t2/relatorio', methods=['POST'])
def api_t2_relatorio():
    data     = request.json or {}
    txt      = gerar_relatorio_str(data)
    tickers  = data.get('tickers', ['relatorio'])
    filename = f"relatorio_{'_'.join(tickers[:3])}_{datetime.date.today():%Y%m%d}.txt"
    buf      = io.BytesIO(txt.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=filename, mimetype='text/plain')


# ── API: Playground ───────────────────────────────────────────────────────────

@app.route('/api/playground/simular', methods=['POST'])
def api_playground_simular():
    data      = request.json or {}
    tickers   = data.get('tickers', [])
    inicio    = data.get('inicio', '')
    corte     = data.get('corte', '')
    fim       = data.get('fim', '')
    rf        = float(data.get('rf', RF_DEFAULT)) / 100
    estrategia = data.get('estrategia', 'max_sharpe')

    if len(tickers) < 2:
        return jsonify({'error': 'Selecione ao menos 2 ativos.'}), 400
    if not (inicio and corte and fim):
        return jsonify({'error': 'Preencha todas as datas.'}), 400
    if not (inicio < corte < fim):
        return jsonify({'error': 'Datas devem seguir a ordem: início < corte < fim.'}), 400

    try:
        all_returns = fetch_prices_range(tickers, start=inicio, end=fim)
        market_all  = fetch_market_range(start=inicio, end=fim)
        tickers_ok  = list(all_returns.columns)

        returns_is  = all_returns[all_returns.index <= corte]
        returns_oos = all_returns[all_returns.index >  corte]
        market_is   = market_all[market_all.index   <= corte]
        market_oos  = market_all[market_all.index   >  corte]

        if len(returns_is) < 30:
            return jsonify({'error': 'Período in-sample muito curto (< 30 dias úteis).'}), 400
        if len(returns_oos) < 5:
            return jsonify({'error': 'Período out-of-sample muito curto (< 5 dias úteis).'}), 400

        mu, S = annualize(returns_is)
        sh_w, sh_v, sh_r, sh_s = compute_max_sharpe(mu, S, rf)
        mv_w, mv_v, mv_r, mv_s = compute_min_vol(mu, S, rf)
        nv_w, nv_v, nv_r, nv_s = compute_naive(tickers_ok, mu, S, rf)

        weights = {'max_sharpe': sh_w, 'min_vol': mv_w, 'naive': nv_w}.get(estrategia, sh_w)

        port_series  = simulate_portfolio(weights, returns_oos)
        naive_series = simulate_portfolio(nv_w,    returns_oos)
        ibov_series  = simulate_portfolio({'IBOV': 1.0}, market_oos.to_frame())

        return jsonify({
            'tickers': tickers_ok,
            'rf':      rf,
            'corte':   corte,
            'in_sample': {
                'periodo':    f'{inicio} → {corte}',
                'frontier':   compute_efficient_frontier(mu, S),
                'sharpe':     {'pesos': sh_w, 'vol': sh_v, 'ret': sh_r, 'sharpe': sh_s},
                'minvol':     {'pesos': mv_w, 'vol': mv_v, 'ret': mv_r, 'sharpe': mv_s},
                'naive':      {'pesos': nv_w, 'vol': nv_v, 'ret': nv_r, 'sharpe': nv_s},
                'betas':      compute_capm_betas(returns_is, market_is, rf_annual=rf),
                'asset_vols': {t: math.sqrt(float(S.loc[t, t])) for t in tickers_ok},
                'asset_rets': {t: float(mu[t]) for t in tickers_ok},
            },
            'out_of_sample': {
                'periodo':    f'{corte} → {fim}',
                'datas':      [d.date().isoformat() for d in returns_oos.index],
                'portfolio':  port_series.tolist(),
                'naive':      naive_series.tolist(),
                'ibovespa':   ibov_series.tolist(),
                'estrategia': estrategia,
                'metricas':   compute_metricas_oos(port_series, ibov_series, rf),
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
