#!/usr/bin/env python3
"""Genera un PDF breve (B/N, estilo LaTeX) explicando las metricas del Modulo 1."""
from fpdf import FPDF

SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
SERIF_B = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
SERIF_I = "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

BLACK = (0, 0, 0)
GRAY = (90, 90, 90)
BOXBG = (244, 244, 244)
RULE = (170, 170, 170)

pdf = FPDF(format="A4")
pdf.set_auto_page_break(auto=True, margin=18)
pdf.add_page()
pdf.set_margins(20, 18, 20)

pdf.add_font("serif", "", SERIF)
pdf.add_font("serif", "B", SERIF_B)
pdf.add_font("serif", "I", SERIF_I)
pdf.add_font("mono", "", MONO)

W = pdf.w - pdf.l_margin - pdf.r_margin


def h1(txt):
    pdf.set_font("serif", "B", 17)
    pdf.set_text_color(*BLACK)
    pdf.multi_cell(W, 8, txt)
    pdf.ln(1)


def h2(txt):
    pdf.ln(2)
    pdf.set_font("serif", "B", 12.5)
    pdf.set_text_color(*BLACK)
    pdf.multi_cell(W, 6.2, txt)
    y = pdf.get_y() + 0.5
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, y, pdf.l_margin + W, y)
    pdf.ln(2.5)


def body(txt):
    pdf.set_font("serif", "", 11)
    pdf.set_text_color(*BLACK)
    pdf.multi_cell(W, 5.4, txt)


def small(txt):
    pdf.set_font("serif", "I", 9.5)
    pdf.set_text_color(*GRAY)
    pdf.multi_cell(W, 4.6, txt)
    pdf.set_text_color(*BLACK)


def formula(txt):
    """Caja gris con la formula en monoespaciada (look ecuacion)."""
    pdf.ln(1.2)
    pdf.set_font("mono", "", 10)
    lines = txt.split("\n")
    h = 5.6 * len(lines) + 4
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*BOXBG)
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, W, h, style="DF")
    pdf.set_xy(x + 4, y + 2)
    pdf.set_text_color(*BLACK)
    for ln in lines:
        pdf.set_x(x + 4)
        pdf.cell(W - 8, 5.6, ln)
        pdf.ln(5.6)
    pdf.set_y(y + h)
    pdf.ln(2)


# ============================ CONTENIDO ============================
h1("Modulo 1 - Simulador de Aumentos")
pdf.set_font("serif", "I", 11)
pdf.set_text_color(*GRAY)
pdf.multi_cell(W, 5.2, "Como se calcula cada metrica que se muestra en pantalla. "
                      "Todas las formulas son las que usa la aplicacion internamente.")
pdf.set_text_color(*BLACK)
pdf.ln(2)

# --- 1. Datos base ---
h2("1.  Los dos datos de partida")
body("Cada fila combina informacion de dos archivos, unidos por Prestador + Convenio + Prestacion:")
pdf.ln(1)
body("•  Cantidad CM  -  cuantas veces se realizo esa prestacion (archivo de Consumo).")
body("•  Valor Convenido a HOY  -  el precio actual pactado de esa prestacion (Tarifario / Valores).")
small("Si una prestacion tiene varias vigencias en el tarifario, se toma la mas reciente (el valor vigente).")

# --- 2. Metricas principales ---
h2("2.  Metricas principales (las cuatro tarjetas)")
body("Se calculan fila por fila y las tarjetas muestran la SUMA de todas las filas.")
formula(
    "Consumo Ideal     = Cantidad CM  x  Valor Convenido a HOY\n"
    "Valor Ofrecido    = Valor Convenido a HOY  x  (1 + aumento% / 100)\n"
    "Consumo Simulado  = Cantidad CM  x  Valor Ofrecido\n"
    "Diferencia        = Consumo Simulado  -  Consumo Ideal\n"
    "Impacto Total (%) = (Consumo Simulado / Consumo Ideal - 1) x 100"
)
body("En palabras:")
body("•  Consumo Ideal = lo que cuesta hoy, sin aumento.")
body("•  Valor Ofrecido = el precio nuevo despues de aplicar el aumento.")
body("•  Consumo Simulado = lo que costaria con el aumento aplicado.")
body("•  Diferencia = la plata extra que genera el aumento.")
body("•  Impacto Total = esa diferencia expresada en porcentaje.")

# --- 3. Aumentos ---
h2("3.  Como funcionan los aumentos")
body("Aumentar un % significa multiplicar el precio actual por (1 + % / 100). Esa es la unica formula:")
formula("Valor Ofrecido = Valor actual  x  (1 + % / 100)")
body("Ejemplo: un valor de $1.000 con 15% de aumento  ->  1.000 x 1,15 = $1.150.")
pdf.ln(1)
body("Hay tres formas de elegir ese % (boton \"Tipo de Aumento\"):")
body("•  Plano: el mismo % para todas las prestaciones.")
body("•  Por Nomenclador: un % por grupo (nomenclador); el resto usa el % base.")
body("•  Por Prestacion: un % especifico para las prestaciones elegidas; el resto usa el % base.")
small("Cambia solo de donde sale el % de cada fila; el calculo del precio nuevo es siempre el mismo.")

# --- 4. Ejemplo ---
h2("4.  Ejemplo completo de una prestacion")
formula(
    "Cantidad CM = 200      Valor Convenido a HOY = $1.000      Aumento = 15%\n"
    "\n"
    "Consumo Ideal    = 200 x 1.000          = $200.000\n"
    "Valor Ofrecido   = 1.000 x (1 + 0,15)   = $1.150\n"
    "Consumo Simulado = 200 x 1.150          = $230.000\n"
    "Diferencia       = 230.000 - 200.000    = $30.000\n"
    "Impacto Total    = 230.000 / 200.000 - 1 = 15%"
)

# --- 5. Metricas de negociacion ---
h2("5.  Metricas de negociacion")
body("Mismas sumas (Σ = suma sobre todas las filas), vistas desde la negociacion:")
formula(
    "Impacto total    = Σ Simulado - Σ Ideal\n"
    "Impacto %        = Σ Simulado / Σ Ideal - 1\n"
    "Impacto mensual  = Impacto total / N (cantidad de meses)\n"
    "Extrapauta       = Σ Simulado - Σ Ideal x (1 + pauta% / 100)"
)
body("El Extrapauta mide cuanto se pasa el aumento por encima de la pauta autorizada de referencia "
     "(por ejemplo, la inflacion). Si da 0 o menos, el aumento esta dentro de la pauta.")
body("Y en la tabla de negociacion, el % de aumento efectivo por prestacion es:")
formula("% Aumento = (Valor Ofrecido / Valor Convenido a HOY - 1) x 100")

# --- 6. Pronostico ---
h2("6.  Pronostico (pestana Evolucion)")
body("Las lineas punteadas proyectan 6 meses hacia adelante con una recta de tendencia "
     "(regresion lineal simple) ajustada a los meses historicos de cada serie "
     "(Cantidad CM e Importe CM, sumadas por mes):")
formula("valor estimado = a x (numero de mes) + b")
small("a y b se calculan para que la recta pase lo mas cerca posible de los puntos historicos. "
      "Es una tendencia orientativa, no una prediccion con factores externos.")

pdf.output("/home/user/simulador_app/metricas_modulo1.pdf")
print("PDF generado OK")
