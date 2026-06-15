'use strict';

const DARK_LAYOUT = {
  paper_bgcolor: '#f5f7fa',
  plot_bgcolor:  '#ffffff',
  font:          { family: "Inter, system-ui, sans-serif", color: '#1e293b', size: 10 },
  margin:        { l: 70, r: 30, t: 40, b: 60 },
  hovermode:    'closest',
  hoverlabel:   { bgcolor: '#ffffff', bordercolor: '#dde1ea', font: { family: "'Courier New'", size: 10, color: '#1e293b' } },
  legend: {
    bgcolor: 'rgba(0,0,0,0)', font: { size: 9 },
    orientation: 'h', y: 1.06, x: 0,
  },
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
};

let _resultado = null;

// ── localStorage persistence ───────────────────────────────────────────────

const NS = 't2:';

function saveState() {
  const sel     = document.getElementById('ticker-select');
  const setor   = document.getElementById('setor-filter').value;
  const tickers = [...sel.options].map(o => o.value);
  const selected = [...sel.options].filter(o => o.selected).map(o => o.value);
  const periodo  = document.querySelector('input[name=periodo]:checked')?.value || '5A';
  const rf       = document.getElementById('rf-input').value;
  localStorage.setItem(NS + 'setor',    setor);
  localStorage.setItem(NS + 'tickers',  JSON.stringify(tickers));
  localStorage.setItem(NS + 'selected', JSON.stringify(selected));
  localStorage.setItem(NS + 'periodo',  periodo);
  localStorage.setItem(NS + 'rf',       rf);
}

function restoreState() {
  const setor = localStorage.getItem(NS + 'setor');
  if (setor !== null) {
    const sf = document.getElementById('setor-filter');
    sf.value = setor;
    // Trigger repopulation of listbox
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
    // Add any extra tickers not in current list (manually added ones)
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

  const periodo = localStorage.getItem(NS + 'periodo');
  if (periodo) {
    const el = document.querySelector(`input[name=periodo][value="${periodo}"]`);
    if (el) el.checked = true;
  }

  const rf = localStorage.getItem(NS + 'rf');
  if (rf) document.getElementById('rf-input').value = rf;
}

restoreState();

// ── Sector filter ─────────────────────────────────────────────────────────
document.getElementById('setor-filter').addEventListener('change', function () {
  const setor   = this.value;
  const sel     = document.getElementById('ticker-select');
  const selected = new Set([...sel.options].filter(o => o.selected).map(o => o.value));

  const list = setor
    ? (window.SETORES[setor] || []).slice().sort()
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
document.querySelectorAll('input[name=periodo]').forEach(el => el.addEventListener('change', saveState));
document.getElementById('rf-input').addEventListener('input', saveState);

// Add ticker from text input
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

document.getElementById('btn-calcular').addEventListener('click', calcular);
document.getElementById('btn-relatorio').addEventListener('click', exportarRelatorio);

function setStatus(msg, ok = true) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.style.color = ok ? '#51cf66' : '#ff4466';
}

async function calcular() {
  const tickers = [...document.querySelectorAll('#ticker-select option:checked')]
    .map(o => o.value);
  if (tickers.length < 2) { setStatus('Selecione ao menos 2 ativos.', false); return; }

  const periodo = document.querySelector('input[name=periodo]:checked')?.value || '5A';
  const rf      = parseFloat(document.getElementById('rf-input').value) || 10.75;

  const btn = document.getElementById('btn-calcular');
  btn.disabled = true;
  document.getElementById('btn-relatorio').disabled = true;
  setStatus('Buscando dados e calculando...');

  try {
    const resp = await fetch('/api/t2/calcular', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ tickers, periodo, rf }),
    });
    const data = await resp.json();
    if (data.error) { setStatus(data.error, false); return; }

    _resultado = data;
    renderChart(data);
    renderTable(data);
    setStatus(`OK — ${data.tickers.length} ativos carregados`);
    document.getElementById('btn-relatorio').disabled = false;
  } catch (e) {
    setStatus(`Erro: ${e.message}`, false);
  } finally {
    btn.disabled = false;
  }
}

function renderChart(d) {
  const frontier_vols = d.frontier.map(p => p[0]);
  const frontier_rets = d.frontier.map(p => p[1]);

  // CML line from (0, rf) through max-sharpe extended to right
  const rf      = d.rf;
  const sh_v    = d.sharpe.vol;
  const sh_r    = d.sharpe.ret;
  const slope   = sh_v > 0 ? (sh_r - rf) / sh_v : 0;
  const vol_end = Math.max(...frontier_vols) * 1.2;
  const ret_end = rf + slope * vol_end;

  const traces = [
    // Frontier
    {
      x: frontier_vols, y: frontier_rets, name: 'Fronteira Eficiente',
      type: 'scatter', mode: 'lines',
      line: { color: '#2563eb', width: 2 },
      hovertemplate: 'Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra>Fronteira</extra>',
    },
    // CML
    {
      x: [0, vol_end], y: [rf, ret_end], name: 'CML',
      type: 'scatter', mode: 'lines',
      line: { color: '#dc2626', width: 1, dash: 'dash' },
      hovertemplate: 'CML<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra></extra>',
    },
    // Individual assets
    {
      x: d.tickers.map(t => d.asset_vols[t]),
      y: d.tickers.map(t => d.asset_rets[t]),
      text: d.tickers,
      name: 'Ativos',
      type: 'scatter', mode: 'markers+text',
      textposition: 'top right', textfont: { size: 9, color: '#555e72' },
      marker: { color: '#94a3b8', size: 7, line: { color: '#64748b', width: 1 } },
      hovertemplate: '%{text}<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<extra></extra>',
    },
    // 1/N
    {
      x: [d.naive.vol], y: [d.naive.ret], name: `1/N (SR=${d.naive.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#64748b', size: 12, symbol: 'triangle-up' },
      hovertemplate: `1/N<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${d.naive.sharpe.toFixed(2)}<extra></extra>`,
    },
    // Min-Vol
    {
      x: [d.minvol.vol], y: [d.minvol.ret], name: `Min-Vol (SR=${d.minvol.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#16a34a', size: 14, symbol: 'circle' },
      hovertemplate: `Min-Vol<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${d.minvol.sharpe.toFixed(2)}<extra></extra>`,
    },
    // Max-Sharpe
    {
      x: [d.sharpe.vol], y: [d.sharpe.ret], name: `Max-Sharpe (SR=${d.sharpe.sharpe.toFixed(2)})`,
      type: 'scatter', mode: 'markers',
      marker: { color: '#d97706', size: 14, symbol: 'star' },
      hovertemplate: `Max-Sharpe<br>Vol: %{x:.1%}<br>Ret: %{y:.1%}<br>SR: ${d.sharpe.sharpe.toFixed(2)}<extra></extra>`,
    },
  ];

  // Rƒ annotation on CML
  const annotations = [{
    x: 0, y: rf, xref: 'x', yref: 'y',
    text: `Rƒ=${(rf * 100).toFixed(1)}%`,
    showarrow: true, arrowhead: 2, arrowcolor: '#dc2626',
    font: { size: 9, color: '#dc2626' }, ax: 30, ay: -20,
  }];

  Plotly.react('chart', traces, { ...DARK_LAYOUT, annotations }, { responsive: true, displaylogo: false });
}

function renderTable(d) {
  const cols = ['Ativo', 'Max-Sharpe', 'Min-Vol', '1/N', 'Beta (β)', 'Alpha (α a.a.)', 'R²'];
  let html = `<table class="weights-table"><thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>`;

  d.tickers.forEach(t => {
    const ws  = (d.sharpe.pesos[t] || 0) * 100;
    const wm  = (d.minvol.pesos[t] || 0) * 100;
    const wn  = (d.naive.pesos[t]  || 0) * 100;
    const b   = d.betas[t] || {};
    html += `<tr>
      <td>${t}</td>
      <td>${ws.toFixed(1)}%</td>
      <td>${wm.toFixed(1)}%</td>
      <td>${wn.toFixed(1)}%</td>
      <td>${(b.beta || 0).toFixed(3)}</td>
      <td>${(b.alpha || 0).toFixed(2)}%</td>
      <td>${(b.r2 || 0).toFixed(3)}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('table-wrap').innerHTML = html;
}

async function exportarRelatorio() {
  if (!_resultado) return;
  const resp = await fetch('/api/t2/relatorio', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(_resultado),
  });
  if (!resp.ok) { setStatus('Erro ao gerar relatório.', false); return; }
  const blob     = await resp.blob();
  const filename = resp.headers.get('Content-Disposition')?.match(/filename="?([^"]+)"?/)?.[1]
                   || 'relatorio.txt';
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
