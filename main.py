import tkinter as tk
from tkinter import ttk
import random

# ── Dados falsos (substituir por Yahoo Finance depois) ──────────────────────


def gerar_serie(n=150, base=20.0):
    dados = []
    v = base
    for _ in range(n):
        v *= (1 + random.gauss(0.0003, 0.025))
        dados.append(max(0.01, v))
    return dados


# ── Janela principal ─────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Price History Comparator")
root.geometry("900x580")
root.configure(bg="#0f1117")

INDICADORES = ["Preço da Cota", "P/VP", "P/L", "EV/EBIT", "EV/EBITDA"]
indicador_var = tk.StringVar(value=INDICADORES[0])
serie = []
linha_ref = None  # valor Y da linha de referência arrastável

# ── Função principal: desenha o gráfico no canvas ────────────────────────────


def desenhar():
    c.delete("all")
    if not serie:
        return

    W, H = c.winfo_width(), c.winfo_height()
    if W < 10 or H < 10:
        return

    # Margens do gráfico
    ml, mr, mt, mb = 55, 15, 15, 30
    x0, y0, x1, y1 = ml, mt, W - mr, H - mb

    # Escala dos valores
    vmin, vmax = min(serie) * 0.97, max(serie) * 1.03
    span = vmax - vmin

    def px(i): return x0 + i / (len(serie) - 1) * (x1 - x0)
    def py(v): return y1 - (v - vmin) / span * (y1 - y0)

    # Grade horizontal com labels de valor
    for k in range(5):
        gy = y0 + k * (y1 - y0) / 4
        gv = vmax - k * span / 4
        c.create_line(x0, gy, x1, gy, fill="#1e2535", dash=(3, 5))
        c.create_text(
            x0 - 4, gy, text=f"{gv:.2f}", font=("Courier New", 8), fill="#555e72", anchor="e")

    # Área preenchida abaixo da linha
    pts = [x0, y1]
    for i, v in enumerate(serie):
        pts += [px(i), py(v)]
    pts += [px(len(serie) - 1), y1]
    c.create_polygon(*pts, fill="#0d2535", outline="")

    # Linha principal do indicador
    pts = []
    for i, v in enumerate(serie):
        pts += [px(i), py(v)]
    c.create_line(*pts, fill="#00e5ff", width=2, smooth=True)

    # Ponto no valor atual (último da série)
    lx, ly = px(len(serie) - 1), py(serie[-1])
    c.create_oval(lx - 4, ly - 4, lx + 4, ly + 4,
                  fill="#00e5ff", outline="#0f1117", width=2)

    # Linha de referência arrastável (amarela)
    if linha_ref is not None:
        by = py(max(vmin, min(vmax, linha_ref)))
        c.create_line(x0, by, x1, by, fill="#ffd700", width=1, dash=(8, 4))
        c.create_text(x1 - 2, by - 8, text=f"ref: {linha_ref:.2f}", font=(
            "Courier New", 8), fill="#ffd700", anchor="e")

        # Porcentagem de tempo acima e abaixo da referência
        acima = sum(1 for v in serie if v > linha_ref) / len(serie) * 100
        abaixo = 100 - acima
        c.create_text(x0 + 4, by - 10, text=f"↑ {acima:.0f}%",
                      font=("Courier New", 8), fill="#00ff88", anchor="w")
        c.create_text(x0 + 4, by + 10, text=f"↓ {abaixo:.0f}%",
                      font=("Courier New", 8), fill="#ff4466", anchor="w")

# ── Carrega nova série quando o indicador muda ───────────────────────────────


def carregar():
    global serie, linha_ref
    serie = gerar_serie()
    linha_ref = None
    root.after(50, desenhar)  # pequeno delay para o canvas ter tamanho correto

# ── Eventos de clique e arraste para mover a linha de referência ─────────────


def canvas_y_para_valor(cy):
    H = c.winfo_height()
    ml, mr, mt, mb = 55, 15, 15, 30
    vmin, vmax = min(serie) * 0.97, max(serie) * 1.03
    ratio = 1.0 - (cy - mt) / (H - mb - mt)
    return vmin + ratio * (vmax - vmin)


def on_click(e):
    global linha_ref
    linha_ref = canvas_y_para_valor(e.y)
    desenhar()


def on_drag(e):
    global linha_ref
    linha_ref = canvas_y_para_valor(e.y)
    desenhar()


# ── Layout: sidebar esquerda + canvas direita ────────────────────────────────
sidebar = tk.Frame(root, bg="#111520", width=170)
sidebar.pack(side="left", fill="y", padx=(8, 0), pady=8)
sidebar.pack_propagate(False)

tk.Label(sidebar, text="INDICADOR", font=("Courier New", 8),
         bg="#111520", fg="#4a5568").pack(anchor="w", padx=12, pady=(14, 4))

for ind in INDICADORES:
    tk.Radiobutton(sidebar, text=ind, variable=indicador_var, value=ind,
                   font=("Courier New", 10), bg="#111520", fg="#94a3b8",
                   selectcolor="#141926", activebackground="#111520",
                   indicatoron=False, relief="flat", padx=12, pady=6,
                   anchor="w", cursor="hand2", command=carregar).pack(fill="x")

tk.Button(sidebar, text="↺ Resetar linha", font=("Courier New", 8),
          bg="#1e2535", fg="#94a3b8", relief="flat", padx=10, pady=5,
          cursor="hand2", command=lambda: [globals().update(linha_ref=None), desenhar()]).pack(fill="x", padx=12, pady=(20, 0))

# Canvas do gráfico
c = tk.Canvas(root, bg="#141926", highlightthickness=0, cursor="crosshair")
c.pack(side="left", fill="both", expand=True, padx=8, pady=8)
c.bind("<Configure>", lambda e: desenhar())
c.bind("<Button-1>", on_click)
c.bind("<B1-Motion>", on_drag)

# Carrega ao iniciar
carregar()
root.mainloop()
