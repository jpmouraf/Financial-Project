# Funcionalidades — CAD 167 · UFMG
**Aplicação Web de Análise de Investimentos**

> Stack: Python · Flask · Plotly.js · yfinance · brapi.dev · PyPortfolioOpt

---

## Visão Geral

Aplicação web com três módulos independentes acessíveis pela barra de navegação:

| Módulo | URL | Descrição |
|---|---|---|
| Análise Fundamentalista | `/t1` | Séries históricas de indicadores via brapi.dev |
| Fronteira Eficiente | `/t2` | Otimização de portfólio por Markowitz + CAPM |
| Playground | `/playground` | Backtesting in-sample / out-of-sample |

---

## 1. Análise Fundamentalista (`/t1`)

### O que faz
Busca e plota séries históricas diárias de indicadores fundamentalistas de qualquer ação do Ibovespa, calculados com dados financeiros trimestrais ou anuais da API brapi.dev.

### Indicadores disponíveis

| Categoria | Indicadores |
|---|---|
| Calculados (preço ÷ fundamento) | Preço da Cota, P/L, P/VP, EV/EBIT, EV/EBITDA |
| Base (fundamento direto) | LPA, Lucro Líquido, EBIT, EBITDA, VPA |

### Controles da sidebar
- **Empresa** — campo de texto com autocomplete dos tickers atuais do Ibovespa (via API B3); suporta digitar `Enter` para carregar
- **Indicadores** — checkboxes com bolinha colorida por indicador; múltipla seleção livre
- **Período histórico** — 1A / 2A / 5A / 10A / 20A (com fallback automático se o plano brapi.dev não suportar o range)
- **Modo** — Trimestral (TTM 4 trimestres) ou Anual
- **Carregar** — busca assíncrona; botão desabilitado durante o carregamento
- **Resetar** — limpa o gráfico

### Comportamento do gráfico
- **1 indicador:** eixo Y em valores absolutos + área preenchida abaixo da curva
- **Múltiplos indicadores:** cada série normalizada a índice 100 (primeiro pregão = 100); hover mostra valor normalizado e valor real simultaneamente
- Hover modo `x unified` — mostra todos os valores na mesma data ao passar o mouse
- Spike lines horizontais e verticais como cursor de referência

### Metodologia dos indicadores

| Indicador | Cálculo |
|---|---|
| P/L | Preço ÷ LPA_TTM (lucro líquido TTM / ações) |
| P/VP | Preço ÷ (Patrimônio líquido / ações) |
| EV/EBIT | (Preço × ações + dívida − caixa) ÷ EBIT_TTM |
| EV/EBITDA | (Preço × ações + dívida − caixa) ÷ EBITDA_TTM |
| LPA | Lucro líquido TTM / ações (R$/ação) |
| Lucro Líquido | Lucro líquido TTM (R$ bilhões) |
| EBIT / EBITDA | TTM (R$ bilhões) |
| VPA | Patrimônio líquido / ações (R$/ação) |

**TTM (Trailing Twelve Months):** soma dos últimos 4 trimestres. Trimestres ausentes são substituídos pela média dos disponíveis.

---

## 2. Fronteira Eficiente (`/t2`)

### O que faz
Implementa a Teoria Moderna do Portfólio de Markowitz: calcula a fronteira eficiente, destaca os portfólios ótimos e estima os betas CAPM para os ativos selecionados.

### Controles da sidebar
- **Filtro por setor** — dropdown com 26 setores do Ibovespa; ao selecionar um setor, a listbox é repopulada com apenas os tickers daquele setor; seleções já feitas são preservadas
- **Listbox de ativos** — seleção múltipla (ctrl+clique); mínimo 2 ativos
- **Adicionar ticker** — campo de texto para incluir qualquer ticker manualmente (não limitado ao Ibovespa)
- **Período histórico** — 1A / 2A / 5A
- **Taxa livre de risco** — campo numérico em % a.a. (padrão: SELIC vigente 10,75%)
- **Calcular** — dispara a otimização; botão desabilitado durante o cálculo
- **Exportar Relatório** — gera e baixa um `.txt` com todos os resultados (habilitado após calcular)
- **Glossário** — painel rolável com definições de todos os conceitos exibidos

### Gráfico da fronteira eficiente

| Elemento | Cor | Símbolo |
|---|---|---|
| Fronteira eficiente | Azul `#2563eb` | Linha contínua |
| Capital Market Line (CML) | Vermelho `#dc2626` | Linha tracejada |
| Max-Sharpe (portfólio tangente) | Âmbar `#d97706` | Estrela |
| Min-Vol (variância mínima) | Verde `#16a34a` | Círculo |
| 1/N (benchmark ingênuo) | Cinza `#64748b` | Triângulo |
| Ativos individuais | Cinza claro | Ponto pequeno com label |
| Rƒ (origem da CML) | Vermelho | Anotação com seta |

- Eixo X: volatilidade anualizada (%)
- Eixo Y: retorno esperado anualizado (%)
- Hover mostra vol, retorno e Índice de Sharpe de cada portfólio

### Tabela de pesos
Abaixo do gráfico, exibe para cada ativo selecionado:

| Coluna | Descrição |
|---|---|
| Max-Sharpe | Peso no portfólio tangente |
| Min-Vol | Peso no portfólio de mínima volatilidade |
| 1/N | Peso no benchmark uniforme (sempre 100%/N) |
| Beta (β) | Sensibilidade ao Ibovespa (OLS) |
| Alpha (α a.a.) | Retorno anual acima do esperado pelo CAPM |
| R² | Fração da variância explicada pelo mercado |

### Setores disponíveis (26)
Bancos · Seguros · Serviços Financeiros · Petróleo e Gás · Combustíveis · Mineração · Siderurgia · Energia Elétrica · Saneamento · Telecomunicações · Varejo · Supermercados · Alimentação e Bebidas · Saúde · Farmácias · Construção Civil · Logística e Transporte · Aeroespacial · Educação · Papel e Celulose · Petroquímica · Tecnologia · Shopping e Imóveis · Máquinas e Equipamentos · Agronegócio · Outros

### Relatório exportado (`.txt`)
Inclui para cada portfólio (Max-Sharpe, Min-Vol, 1/N):
- Tabela de pesos com β, α e R² por ativo
- Retorno esperado a.a., Volatilidade a.a., Índice de Sharpe
- Notas metodológicas

### Metodologia

| Item | Detalhe |
|---|---|
| Fonte de dados | yfinance (preços ajustados, sufixo `.SA`) |
| Retornos | Logarítmicos diários: ln(Pₜ/Pₜ₋₁), anualizados ×252 |
| Fronteira eficiente | `EfficientFrontier.efficient_return()` varrendo retornos alvo (PyPortfolioOpt) |
| Max-Sharpe | `EfficientFrontier.max_sharpe()` — portfólio tangente |
| Min-Vol | `EfficientFrontier.min_volatility()` — variância mínima global |
| Solver | OSQP (max 50.000 iter, polishing=True); fallback SCS |
| Beta CAPM | OLS: (Rᵢ − Rƒ) = α + β·(Rₘ − Rƒ) + ε |
| Proxy de mercado | Ibovespa `^BVSP` |
| CRP | Não adicionado (beta local já embute risco-país — RAC/ANPAD) |

---

## 3. Playground — Backtesting (`/playground`)

### O que faz
Divide o histórico em **in-sample** (treinamento) e **out-of-sample** (teste). O portfólio é otimizado no período de treinamento e simulado no período de teste, comparado com o Ibovespa e com o benchmark 1/N.

### Controles da sidebar
- **Filtro por setor + listbox + adicionar ticker** — mesmo componente do T2
- **Início do histórico** — data de início do período de treinamento
- **Data de corte** — separa treinamento (≤ corte) de teste (> corte); mínimo 30 dias úteis in-sample e 5 dias úteis out-of-sample
- **Fim da simulação** — data final do período de teste
- **Estratégia** — Max-Sharpe / Min-Vol / 1/N (define qual portfólio é simulado OOS)
- **Taxa livre de risco** — % a.a.
- **Simular** — executa o backtest completo

### Gráfico superior — In-Sample (fronteira)
- Fronteira eficiente calculada no período de treinamento
- CML, Max-Sharpe, Min-Vol, 1/N, ativos individuais
- Estratégia selecionada destacada com marcador maior

### Gráfico inferior — Out-of-Sample (performance)
- Eixo X: datas do período de teste
- Eixo Y: valor acumulado com base 100
- 3 séries: **Portfólio otimizado** (azul), **Ibovespa** (laranja), **1/N** (cinza)
- Área sombreada de máximo drawdown do portfólio

### Painel de métricas (6 cards)

| Métrica | Descrição |
|---|---|
| Retorno Total | Variação percentual total do portfólio no período OOS |
| Retorno a.a. | Retorno anualizado: (1 + total)^(252/n) − 1 |
| Volatilidade a.a. | Desvio-padrão dos retornos diários × √252 |
| Índice de Sharpe | (Retorno a.a. − Rƒ) / Volatilidade a.a. |
| Max Drawdown | Maior queda do pico ao vale durante o período |
| Alpha vs Ibov | Retorno a.a. do portfólio − Retorno a.a. do Ibovespa |

Métricas positivas são exibidas em verde; negativas em vermelho.

### Tabela de pesos in-sample
Mesma estrutura do T2: pesos dos três portfólios + β, α, R² por ativo.

---
