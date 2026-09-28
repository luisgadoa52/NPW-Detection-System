"""
app.py
Fase 5 - Dashboard en tiempo real (Streamlit) que conecta las Fases 1-3:
simula una fuga, la reproduce como si llegara en vivo de los sensores,
la detecta, la localiza/dimensiona, y acumula la perdida en litros y pesos
mientras la fuga sigue "abierta".

Correr con: streamlit run app.py (desde la carpeta dashboard/)
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detection"))

from live_stream import detectar_evento_streaming  # noqa: E402
from localize_leak import EconomiaConfig, localizar_fuga, perdida_acumulada  # noqa: E402
from simulate_leak import PipelineConfig, simular_fuga  # noqa: E402

st.set_page_config(page_title="Deteccion de fugas NPW", layout="wide")

st.title("Sistema de deteccion de fugas por onda de presion negativa (NPW)")
st.caption(
    "Simulacion fisica, deteccion (wavelet + umbral adaptativo), localizacion "
    "TDOA y estimacion de perdidas en tiempo real, para una fuga o toma "
    "clandestina en un ducto de crudo."
)

cfg = PipelineConfig()
economia = EconomiaConfig()

with st.sidebar:
    st.header("Parametros de la fuga a simular")
    ubicacion = st.slider(
        "Ubicacion de la fuga (m desde el sensor A)", 0, int(cfg.longitud), 4000, step=100
    )
    diametro_mm = st.slider("Diametro del agujero (mm)", 2, 30, 20, step=1)
    t_inicio = st.slider("Instante en que ocurre la fuga (s)", 2.0, 10.0, 5.0, step=0.5)
    semilla = st.number_input("Semilla aleatoria (reproducibilidad)", value=42, step=1)
    duracion_video_s = st.slider("Duracion deseada de la animacion (s)", 5, 45, 15)
    iniciar = st.button("Iniciar simulacion", type="primary", width="stretch")

    st.divider()
    st.caption(f"Velocidad de la onda (Korteweg): {cfg.velocidad_onda:.0f} m/s")
    st.caption(
        f"Presion de operacion: {cfg.presion_base / 1e5:.0f} bar | "
        f"Longitud entre sensores: {cfg.longitud / 1000:.0f} km"
    )
    st.caption(
        "Nota: los estimados de perdida asumen descarga libre sin contrapresion "
        "externa (peor caso), no la perdida exacta garantizada."
    )

chart_placeholder = st.empty()
status_placeholder = st.empty()
metrics_placeholder = st.empty()


def render_status(mensaje: str, tipo: str = "info") -> None:
    with status_placeholder.container():
        if tipo == "warning":
            st.warning(mensaje)
        elif tipo == "success":
            st.success(mensaje)
        elif tipo == "error":
            st.error(mensaje)
        else:
            st.info(mensaje)


if not iniciar:
    render_status("Ajusta los parametros en la barra lateral y da clic en 'Iniciar simulacion'.")
    presion_bar_inicial = cfg.presion_base / 1e5
    chart_placeholder.line_chart(
        pd.DataFrame(
            {"Sensor A (bar)": [presion_bar_inicial], "Sensor B (bar)": [presion_bar_inicial]}
        )
    )
else:
    duracion_sim = 30.0
    resultado = simular_fuga(
        ubicacion=float(ubicacion),
        diametro=diametro_mm / 1000.0,
        t_inicio=float(t_inicio),
        duracion=duracion_sim,
        cfg=cfg,
        semilla=int(semilla),
    )

    t = resultado["t"]
    presion_a_full = resultado["presion_A"]
    presion_b_full = resultado["presion_B"]
    n = len(t)

    num_frames_objetivo = 300
    paso = max(1, n // num_frames_objetivo)
    num_frames_reales = max(1, n // paso)
    intervalo_frame = duracion_video_s / num_frames_reales

    det_a = det_b = None
    loc = None
    confianza_alta = False

    render_status("Transmitiendo datos de los sensores...", "info")

    for i in range(paso, n + paso, paso):
        i = min(i, n)
        df_parcial = pd.DataFrame(
            {
                "Sensor A (bar)": presion_a_full[:i] / 1e5,
                "Sensor B (bar)": presion_b_full[:i] / 1e5,
            },
            index=t[:i],
        )
        chart_placeholder.line_chart(df_parcial)

        if t[i - 1] > t_inicio + 0.5 and not confianza_alta:
            det_a = detectar_evento_streaming(t[:i], presion_a_full[:i], cfg.fs)
            det_b = detectar_evento_streaming(t[:i], presion_b_full[:i], cfg.fs)
            loc = localizar_fuga(det_a, det_b, cfg.fs, cfg, economia)

            if loc["confianza"] == "alta":
                render_status(
                    f"🚨 Fuga detectada y localizada a {loc['ubicacion_m']:.0f} m del "
                    f"sensor A (diametro estimado: {loc['diametro_mm']:.1f} mm)",
                    "error",
                )
                confianza_alta = True
            elif loc["confianza"] == "baja":
                render_status(f"⚠️ {loc['mensaje']}", "warning")

        if loc and loc["confianza"] == "alta":
            minutos_transcurridos = max(0.0, (t[i - 1] - det_a["t_deteccion"]) / 60.0)
            acumulado = perdida_acumulada(loc["caudal_perdido_lpm"], minutos_transcurridos, economia)
            with metrics_placeholder.container():
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Ubicacion estimada", f"{loc['ubicacion_m']:.0f} m")
                c2.metric("Diametro estimado", f"{loc['diametro_mm']:.1f} mm")
                c3.metric("Litros perdidos (acumulado)", f"{acumulado['litros_perdidos']:.0f} L")
                c4.metric("Costo acumulado", f"${acumulado['pesos_perdidos']:,.0f} MXN")

        time.sleep(intervalo_frame)

    if not confianza_alta:
        if loc and loc["confianza"] == "baja":
            render_status(f"⚠️ {loc['mensaje']}", "warning")
        else:
            render_status(
                "Simulacion terminada. No se disparo ninguna alerta en el tiempo simulado.", "info"
            )

    if loc and loc["confianza"] == "alta":
        st.divider()
        st.subheader("Proyeccion si la fuga sigue abierta (estimado de peor caso)")
        filas = []
        for etiqueta, minutos in [("1 hora", 60), ("1 dia", 60 * 24), ("1 semana", 60 * 24 * 7)]:
            acum = perdida_acumulada(loc["caudal_perdido_lpm"], minutos, economia)
            filas.append(
                {
                    "Periodo": etiqueta,
                    "Litros perdidos": f"{acum['litros_perdidos']:,.0f} L",
                    "Costo estimado": f"${acum['pesos_perdidos']:,.0f} MXN",
                }
            )
        st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
