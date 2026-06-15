'use strict';

const DARK_LAYOUT = {
  paper_bgcolor: '#f5f7fa',
  plot_bgcolor:  '#ffffff',
  font:          { family: "Inter, system-ui, sans-serif", color: '#1e293b', size: 10 },
  margin:        { l: 60, r: 20, t: 30, b: 50 },
  xaxis: {
    gridcolor: '#e2e8f0', linecolor: '#dde1ea', zerolinecolor: '#dde1ea',
    tickfont: { size: 9, color: '#64748b' }, showspikes: true, spikecolor: '#2563eb',
    spikethickness: 1, spikedash: 'dot',
  },
  yaxis: {
    gridcolor: '#e2e8f0', linecolor: '#dde1ea', zerolinecolor: '#dde1ea',
    tickfont: { size: 9, color: '#64748b' }, showspikes: true, spikecolor: '#2563eb',
    spikethickness: 1, spikedash: 'dot',
  },
  hovermode:    'x unified',
  hoverlabel:   { bgcolor: '#ffffff', bordercolor: '#dde1ea', font: { family: "'Courier New'", size: 10, color: '#1e293b' } },
  legend:       { bgcolor: 'rgba(0,0,0,0)', font: { size: 9 }, orientation: 'h', y: 1.08 },
  showlegend:   true,
};

// ── localStorage persistence ───────────────────────────────────────────────

const NS = 't1:';

function saveState() {
  localStorage.setItem(NS + 'ticker',     document.getElementById('ticker-input').value);
  const checked = [...document.querySelectorAll('input[name=indicator]:checked')].map(e => e.value);
  localStorage.setItem(NS + 'indicators', JSON.stringify(checked));
  const hp = document.querySelector('input[name=hist_period]:checked');
  if (hp) localStorage.setItem(NS + 'hist_period', hp.value);
  const per = document.querySelector('input[name=periodo]:checked');
  if (per) localStorage.setItem(NS + 'periodo', per.value);
}

function restoreState() {
  const ticker = localStorage.getItem(NS + 'ticker');
  if (ticker) document.getElementById('ticker-input').value = ticker;

  const checked = JSON.parse(localStorage.getItem(NS + 'indicators') || '[]');
  checked.forEach(v => {
    const el = document.querySelector(`input[name=indicator][value="${v}"]`);
    if (el) el.checked = true;
  });

  const hp = localStorage.getItem(NS + 'hist_period');
  if (hp) {
    const el = document.querySelector(`input[name=hist_period][value="${hp}"]`);
    if (el) el.checked = true;
  }

  const per = localStorage.getItem(NS + 'periodo');
  if (per) {
    const el = document.querySelector(`input[name=periodo][value="${per}"]`);
    if (el) el.checked = true;
  }
}

restoreState();

document.getElementById('ticker-input').addEventListener('input', saveState);
document.querySelectorAll('input[name=indicator], input[name=hist_period], input[name=periodo]')
  .forEach(el => el.addEventListener('change', saveState));

// ── Load ibovespa tickers into datalist ───────────────────────────────────

fetch('/api/tickers')
  .then(r => r.json())
  .then(tickers => {
    const dl = document.getElementById('ticker-list');
    tickers.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      dl.appendChild(opt);
    });
  });

document.getElementById('btn-carregar').addEventListener('click', carregar);
document.getElementById('ticker-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') carregar();
});

document.getElementById('btn-resetar').addEventListener('click', () => {
  Plotly.purge('chart');
});

function setStatus(msg, ok = true) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = ok ? '#ffd700' : '#ff4466';
}

async function carregar() {
  const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (!ticker) return;

  const indicators = [...document.querySelectorAll('input[name=indicator]:checked')]
    .map(el => el.value);
  if (!indicators.length) { setStatus('Selecione ao menos um indicador.', false); return; }

  const hist_period = document.querySelector('input[name=hist_period]:checked')?.value || '5A';
  const periodo     = document.querySelector('input[name=periodo]:checked')?.value || 'Trimestral';

  const btn = document.getElementById('btn-carregar');
  btn.disabled = true;
  setStatus('Carregando...');

  try {
    const resp = await fetch('/api/t1/series', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ ticker, indicators, periodo, hist_period }),
    });
    const data = await resp.json();

    if (data.errors?.length) setStatus(`Sem dados: ${data.errors.join(', ')}`, false);
    else setStatus('');

    renderChart(data.series, indicators, ticker);
  } catch (e) {
    setStatus(`Erro: ${e.message}`, false);
  } finally {
    btn.disabled = false;
  }
}

function renderChart(series, indicators, ticker) {
  const active = indicators.filter(ind => series[ind]);
  if (!active.length) {
    Plotly.purge('chart');
    return;
  }

  const multi  = active.length > 1;
  const traces = [];

  active.forEach(ind => {
    const s = series[ind];
    let yvals = s.values;

    if (multi) {
      // Normalize to index 100 from first point
      const base = s.values[0];
      yvals = s.values.map(v => (v / base) * 100);
    }

    const trace = {
      x:    s.dates,
      y:    yvals,
      name: ind,
      type: 'scatter',
      mode: 'lines',
      line: { color: s.color, width: 2 },
    };

    if (!multi) {
      trace.fill      = 'tozeroy';
      trace.fillcolor = 'rgba(13,37,53,0.7)';
    }

    if (multi) {
      // Store actual values in customdata for hover
      trace.customdata    = s.values;
      trace.hovertemplate = `${ind}<br>%{x}<br>Índice: %{y:.1f}<br>Valor: %{customdata:.3f}<extra></extra>`;
    } else {
      trace.hovertemplate = `${ind}: %{y:.3f}<br>%{x}<extra></extra>`;
    }

    traces.push(trace);
  });

  const layout = {
    ...DARK_LAYOUT,
    title: { text: `${ticker} — ${indicators.join(', ')}`, font: { size: 12, color: '#94a3b8' }, x: 0.01 },
    yaxis: {
      ...DARK_LAYOUT.yaxis,
      title: multi ? 'Índice (base 100)' : active[0],
    },
  };

  Plotly.react('chart', traces, layout, { responsive: true, displaylogo: false });
}
