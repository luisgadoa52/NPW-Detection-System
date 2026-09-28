"""
server.py
Backend del HMI (estilo panel industrial / SCADA clasico) para el sistema de
deteccion de fugas NPW.

A diferencia del dashboard de Streamlit (carpeta ../dashboard), aqui el
frontend es HTML/CSS/JS puro (sin frameworks), pensado para verse como el
software de control que se usa en plantas de verdad: paneles grises con
relieve, banner de alarmas, tendencia tipo registrador de papel, lecturas
tipo LED.

Este servidor solo hace una cosa: correr la simulacion completa + la misma
logica incremental de deteccion/localizacion que usa el dashboard de
Streamlit, y regresarle al navegador un timeline listo para animar. Toda la
animacion (el "tiempo real" simulado) corre en el navegador con JavaScript;
aqui no hay websockets ni nada async, es un solo POST que regresa un JSON.

Correr con: python server.py (desde esta carpeta) y abrir
http://localhost:5000 en el navegador.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detection"))

from live_stream import detectar_evento_streaming  # noqa: E402
from localize_leak import EconomiaConfig, localizar_fuga  # noqa: E402
from simulate_leak import PipelineConfig, simular_fuga  # noqa: E402

app = Flask(__name__)

cfg = PipelineConfig()
economia = EconomiaConfig()

DURACION_SIM_S = 30.0  # segundos de fuga simulados en cada corrida
NUM_FRAMES_OBJETIVO = 300  # cuantos "cortes" de senal se evaluan (mismo criterio que Streamlit)


@app.route("/")
def index():
    return render_template(
        "index.html",
        longitud=cfg.longitud,
        velocidad_onda=cfg.velocidad_onda,
        presion_base_bar=cfg.presion_base / 1e5,
    )


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    datos = request.get_json(force=True)

    ubicacion = float(datos.get("ubicacion", 4000))
    diametro_mm = float(datos.get("diametro_mm", 20))
    t_inicio = float(datos.get("t_inicio", 5.0))
    semilla = int(datos.get("semilla", 42))

    ubicacion = float(np.clip(ubicacion, 0.0, cfg.longitud))
    diametro_mm = float(np.clip(diametro_mm, 2.0, 30.0))
    t_inicio = float(np.clip(t_inicio, 1.0, 10.0))

    resultado = simular_fuga(
        ubicacion=ubicacion,
        diametro=diametro_mm / 1000.0,
        t_inicio=t_inicio,
        duracion=DURACION_SIM_S,
        cfg=cfg,
        semilla=semilla,
    )

    t = resultado["t"]
    presion_a = resultado["presion_A"]
    presion_b = resultado["presion_B"]
    n = len(t)

    paso = max(1, n // NUM_FRAMES_OBJETIVO)

    eventos = []
    confianza_previa = "ninguna"
    confianza_alta_alcanzada = False

    for i in range(paso, n + paso, paso):
        i = min(i, n)
        t_actual = float(t[i - 1])

        if t_actual > t_inicio + 0.5 and not confianza_alta_alcanzada:
            det_a = detectar_evento_streaming(t[:i], presion_a[:i], cfg.fs)
            det_b = detectar_evento_streaming(t[:i], presion_b[:i], cfg.fs)
            loc = localizar_fuga(det_a, det_b, cfg.fs, cfg, economia)

            if loc["confianza"] != confianza_previa:
                confianza_previa = loc["confianza"]
                evento = {"t": t_actual, "confianza": loc["confianza"]}
                if loc["confianza"] == "alta":
                    evento.update(
                        {
                            "ubicacion_m": loc["ubicacion_m"],
                            "diametro_mm": loc["diametro_mm"],
                            "caudal_perdido_lpm": loc["caudal_perdido_lpm"],
                            "costo_por_minuto_mxn": loc["costo_por_minuto_mxn"],
                            "t_deteccion": det_a["t_deteccion"],
                        }
                    )
                    confianza_alta_alcanzada = True
                elif loc["confianza"] == "baja":
                    evento["mensaje"] = loc["mensaje"]
                eventos.append(evento)

    # Downsample de las series de presion para no mandar 3000+ puntos por
    # sensor si no hace falta tanta resolucion visual en la pantalla.
    paso_grafica = max(1, n // 600)
    idx_grafica = np.arange(0, n, paso_grafica)

    return jsonify(
        {
            "t": t[idx_grafica].tolist(),
            "presion_a_bar": (presion_a[idx_grafica] / 1e5).tolist(),
            "presion_b_bar": (presion_b[idx_grafica] / 1e5).tolist(),
            "eventos": eventos,
            "meta": {
                "duracion_sim_s": DURACION_SIM_S,
                "longitud_m": cfg.longitud,
                "precio_litro_mxn": economia.precio_litro_mxn,
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
