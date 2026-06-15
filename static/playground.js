'use strict';

// ── Shared layout helpers ──────────────────────────────────────────────────

const BASE_LAYOUT = {
  paper_bgcolor: '#f5f7fa',
  plot_bgcolor:  '#ffffff',
  font:   { family: "Inter, system-ui, sans-serif", color: '#1e293b', size: 10 },
  margin: { l: 70, r: 30, t: 40, b: 50 },
  hovermode: 'closest',
  hoverlabel: { bgcolor: '#ffffff', bordercolor: '#dde1ea',
                font: { family: "'Courier New'", size: 10, color: '#1e293b' } },
};

// ── localStorage persistence ───────────────────────────────────────────────

const NS = 'pg:';

function saveState() {
  const sel      = document.getElementById('ticker-select');
  const setor    = document.getElementById('setor-filter').value;
  const tickers  = [...sel.options].map(o => o.value);
  const selected = [...sel.options].filter(o => o.selected).map(o => o.value);
  const estrategia = document.querySelector('input[name=estrategia]:checked')?.value || 'max_sharpe';
  localStorage.setItem(NS + 'setor',      setor);
  localStorage.setItem(NS + 'tickers',    JSON.stringify(tickers));
  localStorage.setItem(NS + 'selected',   JSON.stringify(selected));
  localStorage.setItem(NS + 'rf',         document.getElementById('rf-input').value);
  localStorage.setItem(NS + 'inicio',     document.getElementById('dt-inicio').value);
  localStorage.setItem(NS + 'corte',      document.getElementById('dt-corte').value);
  localStorage.setItem(NS + 'fim',        document.getElementById('dt-fim').value);
  localStorage.setItem(NS + 'estrategia', estrategia);
}

function restoreState() {
  const setor = localStorage.getItem(NS + 'setor');
  if (setor !== null) {
    const sf = document.getElementById('setor-filter');
    sf.value = setor;
    const list = setor ? (window.SETORES[setor] || []).slice().sort()
                       : [...window.ALL_TICKERS].sort();
    const sel = document.getElementById('ticker-select');
    sel.innerHTML = '';
    list.forEach(t => {
      const opt = document.createElement('option');
      opt.value = opt.textContent = t;
      sel.appendChild(opt);
    });
  }

  const tickers  = JSON.parse(localStorage.getItem(NS + 'tickers')  || 'null');
  const selected = JSON.parse(localStorage.getItem(NS + 'selected') || 'null');
  if (tickers && selected) {
    const sel = document.getElementById('ticker-select');
    const existing = new Set([...sel.options].map(o => o.value));
    tickers.forEach(t => {
      if (!existing.has(t)) {
        const opt = document.createElement('option');
        opt.value = opt.textContent = t;
        sel.appendChild(opt);
      }
    });
    const selSet = new Set(selected);
    [...sel.options].forEach(o => { o.selected = selSet.has(o.value); });
  }

  const rf = localStorage.getItem(NS + 'rf');
  if (rf) document.getElementById('rf-input').value = rf;

  const inicio = localStorage.getItem(NS + 'inicio');
  if (inicio) document.getElementById('dt-inicio').value = inicio;

  const corte = localStorage.getItem(NS + 'corte');
  if (corte) document.getElementById('dt-corte').value = corte;

  const fim = localStorage.getItem(NS + 'fim');
  if (fim) document.getElementById('dt-fim').value = fim;

  const estrategia = localStorage.getItem(NS + 'estrategia');
  if (estrategia) {
    const el = document.querySelector(`input[name=estrategia][value="${estrategia}"]`);
    if (el) el.checked = true;
  }
}

restoreState();

// ── Sector filter ──────────────────────────────────────────────────────────

document.getElementById('setor-filter').addEventListener('change', function () {
  const setor    = this.value;
  const sel      = document.getElementById('ticker-select');
  const selected = new Set([...sel.options].filter(o => o.selected).map(o => o.value));
  const list     = setor ? (window.SETORES[setor] || []).slice().sort()
                         : [...window.ALL_TICKERS].sort();
  sel.innerHTML = '';
  list.forEach(t => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = t;
    opt.selected = selected.has(t);
    sel.appendChild(opt);
  });
  saveState();
});

document.getElementById('ticker-select').addEventListener('change', saveState);
document.getElementById('rf-input').addEventListener('input', saveState);
document.getElementById('dt-inicio').addEventListener('change', saveState);
document.getElementById('dt-corte').addEventListener('change', saveState);
document.getElementById('dt-fim').addEventListener('change', saveState);
document.querySelectorAll('input[name=estrategia]').forEach(el => el.addEventListener('change', saveState));

document.getElementById('btn-add').addEventListener('click', addTicker);
document.getElementById('add-ticker').addEventListener('keydown', e => {
  if (e.key === 'Enter') addTicker();
});

function addTicker() {
  const input = document.getElementById('add-ticker');
  const t = input.value.trim().toUpperCase().replace('.SA', '');
  if (!t) return;
  const sel = document.getElementById('ticker-select');
  let found = [...sel.options].find(o => o.value === t);
  if (!found) {
    const opt = document.createElement('option');
    opt.value = opt.textContent = t;
    sel.appendChild(opt);
    found = opt;
  }
  found.selected = true;
  input.value = '';
  saveState();
}

// ── Main simulate ──────────────────────────────────────────────────────────

document.getElementById('btn-simular').addEventListener('click', simular);

function setStatus(msg, ok = true) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = ok ? '#51cf66' : '#ff4466';
}

async function simular() {
  const tickers = [...document.querySelectorAll('#ticker-select option:checked')]
    .map(o => o.value);
  if (tickers.length < 2) { setStatus('Selecione ao menos 2 ativos.', false); return; }

  const inicio    = document.getElementById('dt-inicio').value;
  const corte     = document.getElementById('dt-corte').value;
  const fim       = document.getElementById('dt-fim').value;
  const estrategia = document.querySelector('input[name=estrategia]:checked')?.value || 'max_sharpe';
  const rf        = parseFloat(document.getElementById('rf-input').value) || 10.75;

  if (!inicio || !corte || !fim) { setStatus('Preencha todas as datas.', false); return; }
  if (!(inicio < corte && corte < fim)) {
    setStatus('Datas devem seguir: início < corte < fim.', false); return;
  }

  const btn = document.getElementById('btn-simular');
  btn.disabled = true;
  setStatus('Baixando dados e calculando...');

  try {
    const resp = await fetch('/api/playground/simular', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ tickers, inicio, corte, fim, estrategia, rf }),
    });
    const data = await resp.json();
    if (data.error) { setStatus(data.error, false); return; }

    renderIS(data);
    renderOOS(data);
    renderMetrics(data.out_of_sample.metricas, data.out_of_sample.estrategia);
    renderTable(data);
    setStatus(`OK — ${data.tickers.length} ativos · corte ${data.corte}`);
  } catch (e) {
    setStatus(`Erro: ${e.message}`, false);
  } finally {
    btn.disabled = false;
  }
}

// ── In-sample: efficient frontier ─────────────────────────────────────────

function renderIS(d) {
  const is     = d.in_sample;
  const rf     = d.rf;
  const sh_v   = is.sharpe.vol;
  const sh_r   = is.sharpe.ret;
  const slope  = sh_v > 0 ? (sh_r - rf) / sh_v : 0;
  const vol_end = Math.max(...is.frontier.map(p => p[0]), ...Object.values(is.asset_vols)) * 1.2;

  const stratLabel = { max_sharpe: 'Max-Sharpe', min_vol: 'Min-Vol', naive: '1/N' };
  const selKey = document.querySelector('input[name=estrategia]:checked')?.value || 'max_sharpe';
  const selData = { max_sharpe: is.sharpe, min_vol: is.minvol, naive: is.naive }[selKey];

  const traces = [
    {
      x: is.frontier.map(p => p[0]), y: is.frontier.map(p => p[1]),
      name: 'Fronteira Eficiente', type: 'scatter', mode: 'lines',
      line: { color: '#2563eb', width: 2 },
      hovertemplate: 'Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra>Fronteira</extra>',
    },
    {
      x: [0, vol_end], y: [rf, rf + slope * vol_end],
      name: 'CML', type: 'scatter', mode: 'lines',
      line: { color: '#dc2626', width: 1, dash: 'dash' },
      hovertemplate: 'CML<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra></extra>',
    },
    {
      x: d.tickers.map(t => is.asset_vols[t]),
      y: d.tickers.map(t => is.asset_rets[t]),
      text: d.tickers, name: 'Ativos', type: 'scatter', mode: 'markers+text',
      textposition: 'top right', textfont: { size: 9, color: '#555e72' },
      marker: { color: '#94a3b8', size: 7, line: { color: '#64748b', width: 1 } },
      hovertemplate: '%{text}<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra></extra>',
    },
    {
      x: [is.naive.vol],   y: [is.naive.ret],
      name: `1/N (SR=${is.naive.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#94a3b8', size: 11, symbol: 'triangle-up' },
      hovertemplate: `1/N<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${is.naive.sharpe.toFixed(2)}<extra></extra>`,
    },
    {
      x: [is.minvol.vol],  y: [is.minvol.ret],
      name: `Min-Vol (SR=${is.minvol.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#16a34a', size: 13, symbol: 'circle' },
      hovertemplate: `Min-Vol<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${is.minvol.sharpe.toFixed(2)}<extra></extra>`,
    },
    {
      x: [is.sharpe.vol],  y: [is.sharpe.ret],
      name: `Max-Sharpe (SR=${is.sharpe.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#d97706', size: 13, symbol: 'star' },
      hovertemplate: `Max-Sharpe<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${is.sharpe.sharpe.toFixed(2)}<extra></extra>`,
    },
  ];

  // Highlight selected strategy with a ring
  if (selKey !== 'max_sharpe' || true) {
    traces.push({
      x: [selData.vol], y: [selData.ret],
      name: `▶ ${stratLabel[selKey]} (selecionado)`,
      type: 'scatter', mode: 'markers',
      marker: { color: 'rgba(0,0,0,0)', size: 20, symbol: 'circle',
                line: { color: '#7c3aed', width: 2.5 } },
      hoverinfo: 'skip', showlegend: false,
    });
  }

  const layout = {
    ...BASE_LAYOUT,
    title: { text: `Período de Treinamento: ${is.periodo}`, font: { size: 11 }, x: 0.05 },
    legend: { bgcolor: 'rgba(0,0,0,0)', font: { size: 9 }, orientation: 'h', y: 1.08, x: 0 },
    xaxis: {
      gridcolor: '#e2e8f0', linecolor: '#dde1ea', zerolinecolor: '#dde1ea',
      tickformat: '.1%', title: { text: 'Volatilidade Anualizada', font: { size: 10, color: '#64748b' } },
      tickfont: { size: 9, color: '#64748b' },
    },
    yaxis: {
      gridcolor: '#e2e8f0', linecolor: '#dde1ea', zerolinecolor: '#dde1ea',
      tickformat: '.1%', title: { text: 'Retorno Esperado Anualizado', font: { size: 10, color: '#64748b' } },
      tickfont: { size: 9, color: '#64748b' },
    },
    annotations: [{
      x: 0, y: rf, xref: 'x', yref: 'y',
      text: `Rƒ=${(rf * 100).toFixed(1)}%`,
      showarrow: true, arrowhead: 2, arrowcolor: '#dc2626',
      font: { size: 9, color: '#dc2626' }, ax: 30, ay: -20,
    }],
  };

  Plotly.react('chart-is', traces, layout, { responsive: true, displaylogo: false });
}

// ── Out-of-sample: performance ─────────────────────────────────────────────

function renderOOS(d) {
  const oos   = d.out_of_sample;
  const datas = oos.datas;
  const stratLabel = { max_sharpe: 'Portfólio Max-Sharpe', min_vol: 'Portfólio Min-Vol', naive: 'Portfólio 1/N' };
  const portName = stratLabel[oos.estrategia] || 'Portfólio';

  // Compute drawdown series for shading
  const port   = oos.portfolio;
  const rollMax = [];
  const ddAbove = [], ddBelow = [];
  let maxSoFar = port[0];
  port.forEach((v, i) => {
    if (v > maxSoFar) maxSoFar = v;
    rollMax.push(maxSoFar);
    ddAbove.push(maxSoFar);
    ddBelow.push(v);
  });

  const traces = [
    // Drawdown fill
    {
      x: [...datas, ...datas.slice().reverse()],
      y: [...ddAbove, ...ddBelow.slice().reverse()],
      fill: 'toself', fillcolor: 'rgba(220,38,38,0.07)',
      line: { color: 'transparent' },
      name: 'Drawdown', type: 'scatter', mode: 'none',
      hoverinfo: 'skip', showlegend: false,
    },
    // Ibovespa
    {
      x: datas, y: oos.ibovespa,
      name: 'Ibovespa', type: 'scatter', mode: 'lines',
      line: { color: '#f59e0b', width: 1.5 },
      hovertemplate: 'Ibovespa<br>%{x}<br>%{y:.1f}<extra></extra>',
    },
    // 1/N benchmark
    {
      x: datas, y: oos.naive,
      name: '1/N', type: 'scatter', mode: 'lines',
      line: { color: '#94a3b8', width: 1.5, dash: 'dot' },
      hovertemplate: '1/N<br>%{x}<br>%{y:.1f}<extra></extra>',
    },
    // Optimised portfolio
    {
      x: datas, y: oos.portfolio,
      name: portName, type: 'scatter', mode: 'lines',
      line: { color: '#2563eb', width: 2.5 },
      hovertemplate: `${portName}<br>%{x}<br>%{y:.1f}<extra></extra>`,
    },
  ];

  const layout = {
    ...BASE_LAYOUT,
    title: { text: `Simulação Forward: ${oos.periodo}`, font: { size: 11 }, x: 0.05 },
    legend: { bgcolor: 'rgba(0,0,0,0)', font: { size: 9 }, orientation: 'h', y: 1.08, x: 0 },
    xaxis: {
      gridcolor: '#e2e8f0', linecolor: '#dde1ea', type: 'date',
      title: { text: 'Data', font: { size: 10, color: '#64748b' } },
      tickfont: { size: 9, color: '#64748b' },
    },
    yaxis: {
      gridcolor: '#e2e8f0', linecolor: '#dde1ea',
      title: { text: 'Valor acumulado (base 100)', font: { size: 10, color: '#64748b' } },
      tickfont: { size: 9, color: '#64748b' },
    },
    shapes: [{
      type: 'line', x0: datas[0], x1: datas[0], y0: 0, y1: 1,
      xref: 'x', yref: 'paper',
      line: { color: '#64748b', width: 1, dash: 'dot' },
    }],
  };

  Plotly.react('chart-oos', traces, layout, { responsive: true, displaylogo: false });
}

// ── Metrics bar ────────────────────────────────────────────────────────────

function renderMetrics(m, estrategia) {
  const bar = document.getElementById('metrics-bar');
  bar.style.display = 'flex';

  const fmt = (v, pct = true) =>
    pct ? `${(v * 100).toFixed(1)}%` : v.toFixed(3);

  const cells = [
    { label: 'Retorno Total',    value: fmt(m.retorno_total),   pos: m.retorno_total   >= 0 },
    { label: 'Retorno a.a.',     value: fmt(m.retorno_aa),      pos: m.retorno_aa      >= 0 },
    { label: 'Volatilidade a.a.',value: fmt(m.volatilidade_aa), pos: true              },
    { label: 'Sharpe',           value: fmt(m.sharpe, false),   pos: m.sharpe          >= 0 },
    { label: 'Max Drawdown',     value: fmt(m.max_drawdown),    pos: false             },
    { label: 'Alpha vs Ibovespa',value: fmt(m.alpha_vs_ibov),   pos: m.alpha_vs_ibov   >= 0 },
  ];

  bar.innerHTML = cells.map(c => `
    <div class="metric-cell">
      <span class="metric-label">${c.label}</span>
      <span class="metric-value ${c.pos ? 'pos' : 'neg'}">${c.value}</span>
    </div>
  `).join('');
}

// ── Weights table ──────────────────────────────────────────────────────────

function renderTable(d) {
  const is   = d.in_sample;
  const cols = ['Ativo', 'Max-Sharpe', 'Min-Vol', '1/N', 'Beta (β)', 'Alpha (α a.a.)', 'R²'];
  let html = `<table class="weights-table"><thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>`;

  d.tickers.forEach(t => {
    const ws = (is.sharpe.pesos[t] || 0) * 100;
    const wm = (is.minvol.pesos[t] || 0) * 100;
    const wn = (is.naive.pesos[t]  || 0) * 100;
    const b  = is.betas[t] || {};
    html += `<tr>
      <td>${t}</td>
      <td>${ws.toFixed(1)}%</td>
      <td>${wm.toFixed(1)}%</td>
      <td>${wn.toFixed(1)}%</td>
      <td>${(b.beta  || 0).toFixed(3)}</td>
      <td>${(b.alpha || 0).toFixed(2)}%</td>
      <td>${(b.r2    || 0).toFixed(3)}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('table-wrap').innerHTML = html;
}
