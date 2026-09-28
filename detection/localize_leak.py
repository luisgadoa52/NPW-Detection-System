"""
localize_leak.py
Fase 3 - Localizacion (TDOA), dimensionamiento del orificio y estimacion de
perdidas en tiempo real, a partir de lo que detecto la Fase 2 en ambos
sensores.

Este modulo invierte el modelo directo de simulation/simulate_leak.py:
- TDOA (diferencia de tiempos de llegada entre sensores) para ubicar la fuga.
- Relacion de Joukowsky invertida, corrigiendo la atenuacion por distancia,
  para recuperar la amplitud real de la onda en el punto de fuga.
- Ecuacion de orificio invertida para estimar el diametro equivalente del
  agujero a partir de esa amplitud.
- Balance de masa simple para acumular el volumen y el costo estimado de
  lo que se esta perdiendo, en tiempo real.

Regla de disenio (decidida explicitamente, no un accidente): si un sensor
detecta el evento y el otro no, el sistema NO inventa una ubicacion —no hay
TDOA valido con un solo punto—, sino que emite una alerta de baja confianza
para que un operador la confirme. Esto es lo que haria un sistema industrial
real: prefiere avisar "algo raro paso, revisen" antes que reportar una
ubicacion falsa con precision inventada.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulation"))
from simulate_leak import PipelineConfig  # noqa: E402


@dataclass
class EconomiaConfig:
    """Referencia de precio del crudo para traducir litros perdidos a pesos.

    Valores de referencia (actualizables): precio de la Mezcla Mexicana de
    petroleo en dolares por barril, y el tipo de cambio USD/MXN. Ambos
    tomados de fuentes oficiales el 25 de septiembre de 2026:
      - precio_barril_usd: $99.6 USD/barril, reportado por Pemex
        (fuente: Infobae, "Cierre de la mezcla mexicana de petroleo de
        este viernes 25 de septiembre").
      - tipo_cambio_mxn_por_usd: $17.7072 MXN/USD, cierre de mercado
        (fuente: El Financiero, 25 de septiembre de 2026).
    Con estos dos valores, precio_litro_mxn sale en ~$11.09 MXN/L.
    En la Fase 5 (dashboard) esto se puede conectar a una fuente de precios
    en vivo en lugar de un valor fijo; mientras tanto, hay que actualizar
    estos dos numeros a mano de vez en cuando para que sean numeros
    creibles y no un valor fijo desactualizado.
    """

    precio_barril_usd: float = 99.6
    tipo_cambio_mxn_por_usd: float = 17.7072
    litros_por_barril: float = 158.987

    @property
    def precio_litro_mxn(self) -> float:
        return (self.precio_barril_usd * self.tipo_cambio_mxn_por_usd) / self.litros_por_barril


def _atenuacion(distancia_m: float, cfg: PipelineConfig) -> float:
    return max(0.0, 1 - cfg.atenuacion_por_km * distancia_m / 1000)


def _amplitud_medida(det: dict, fs: float, ventana_s: float = 5.0) -> float:
    """Estima la amplitud del transitorio: caida maxima justo despues de la deteccion."""
    senal = det["senal_limpia"]
    idx_deteccion = int(det["t_deteccion"] * fs)
    idx_fin = min(len(senal), idx_deteccion + int(ventana_s * fs))
    baseline_pre = np.mean(senal[:idx_deteccion]) if idx_deteccion > 0 else senal[0]
    trough = np.min(senal[idx_deteccion:idx_fin])
    return float(baseline_pre - trough)


def localizar_fuga(
    det_a: dict,
    det_b: dict,
    fs: float,
    cfg: PipelineConfig | None = None,
    economia: EconomiaConfig | None = None,
) -> dict:
    """
    Combina las detecciones de ambos sensores (Fase 2) para ubicar la fuga,
    estimar su diametro y calcular el caudal perdido.

    Regresa un dict con 'confianza' en {'ninguna', 'baja', 'alta'}. Solo
    cuando la confianza es 'alta' (ambos sensores detectaron) se incluyen
    'ubicacion_m', 'diametro_mm', 'caudal_perdido_lpm' y
    'costo_por_minuto_mxn'.
    """
    if cfg is None:
        cfg = PipelineConfig()
    if economia is None:
        economia = EconomiaConfig()

    a_ok = det_a["detectado"]
    b_ok = det_b["detectado"]

    if not a_ok and not b_ok:
        return {"confianza": "ninguna", "mensaje": "No se detecto ningun evento."}

    if a_ok != b_ok:
        sensor = "A" if a_ok else "B"
        return {
            "confianza": "baja",
            "mensaje": (
                f"Evento detectado solo en el sensor {sensor}. No hay suficiente "
                "informacion para triangular la ubicacion (se requieren ambos "
                "sensores para TDOA). Se recomienda confirmar con inspeccion o "
                "esperar una segunda lectura antes de escalar la alerta."
            ),
        }

    # Confianza alta: ambos sensores detectaron el evento -> TDOA
    c = cfg.velocidad_onda
    dt = det_b["t_deteccion"] - det_a["t_deteccion"]
    x_leak = (cfg.longitud - c * dt) / 2
    x_leak = float(np.clip(x_leak, 0.0, cfg.longitud))

    dist_a = x_leak
    dist_b = cfg.longitud - x_leak

    amp_medida_a = _amplitud_medida(det_a, fs)
    amp_medida_b = _amplitud_medida(det_b, fs)

    atenuacion_a = _atenuacion(dist_a, cfg)
    atenuacion_b = _atenuacion(dist_b, cfg)

    estimaciones_diametro = []
    estimaciones_caudal = []
    for amp_medida, atenuacion in [(amp_medida_a, atenuacion_a), (amp_medida_b, atenuacion_b)]:
        if atenuacion <= 1e-6:
            continue
        amp_en_fuga = amp_medida / atenuacion
        delta_v = amp_en_fuga / (cfg.densidad_fluido * c)  # Joukowsky invertida
        q_leak = delta_v * cfg.area_ducto  # m3/s
        area_fuga = q_leak / (
            cfg.coef_descarga * np.sqrt(2 * cfg.presion_base / cfg.densidad_fluido)
        )  # ecuacion de orificio invertida
        diametro = np.sqrt(4 * area_fuga / np.pi)
        estimaciones_diametro.append(diametro)
        estimaciones_caudal.append(q_leak)

    diametro_estimado_m = float(np.mean(estimaciones_diametro))
    caudal_estimado_m3s = float(np.mean(estimaciones_caudal))
    caudal_estimado_lpm = caudal_estimado_m3s * 1000 * 60

    return {
        "confianza": "alta",
        "ubicacion_m": x_leak,
        "diametro_mm": diametro_estimado_m * 1000,
        "caudal_perdido_lpm": caudal_estimado_lpm,
        "costo_por_minuto_mxn": caudal_estimado_lpm * economia.precio_litro_mxn,
        "dt_s": dt,
    }


def perdida_acumulada(
    caudal_lpm: float,
    minutos_transcurridos: float,
    economia: EconomiaConfig | None = None,
) -> dict:
    """Acumula litros y pesos perdidos desde que se detecto el evento."""
    if economia is None:
        economia = EconomiaConfig()
    litros = caudal_lpm * minutos_transcurridos
    pesos = litros * economia.precio_litro_mxn
    return {"litros_perdidos": litros, "pesos_perdidos": pesos}


if __name__ == "__main__":
    from detect_event import detectar_evento
    from simulate_leak import simular_fuga

    cfg = PipelineConfig()
    UBICACION_REAL = 4000.0
    DIAMETRO_REAL = 0.02

    print("=== Caso 1: fuga grande, ambos sensores detectan ===")
    resultado = simular_fuga(
        ubicacion=UBICACION_REAL, diametro=DIAMETRO_REAL, t_inicio=10.0, cfg=cfg, semilla=42
    )
    det_a = detectar_evento(resultado["t"], resultado["presion_A"], cfg.fs)
    det_b = detectar_evento(resultado["t"], resultado["presion_B"], cfg.fs)
    loc = localizar_fuga(det_a, det_b, cfg.fs, cfg)

    print(f"Confianza: {loc['confianza']}")
    if loc["confianza"] == "alta":
        error_ubicacion = loc["ubicacion_m"] - UBICACION_REAL
        error_diametro = loc["diametro_mm"] - DIAMETRO_REAL * 1000
        print(
            f"Ubicacion estimada: {loc['ubicacion_m']:.1f} m "
            f"(real: {UBICACION_REAL} m, error: {error_ubicacion:+.1f} m)"
        )
        print(
            f"Diametro estimado: {loc['diametro_mm']:.1f} mm "
            f"(real: {DIAMETRO_REAL * 1000:.1f} mm, error: {error_diametro:+.1f} mm)"
        )
        print(f"Caudal perdido: {loc['caudal_perdido_lpm']:.1f} L/min")
        print(f"Costo estimado: ${loc['costo_por_minuto_mxn']:.2f} MXN/min")

        acumulado = perdida_acumulada(loc["caudal_perdido_lpm"], minutos_transcurridos=60)
        print(
            f"\nSi la fuga sigue abierta 1 hora: {acumulado['litros_perdidos']:.0f} L perdidos "
            f"(~${acumulado['pesos_perdidos']:,.0f} MXN)"
        )
    else:
        print(loc["mensaje"])

    print("\n=== Caso 2: fuga chica, solo un sensor detecta ===")
    resultado_chica = simular_fuga(
        ubicacion=UBICACION_REAL, diametro=0.008, t_inicio=10.0, cfg=cfg, semilla=42
    )
    det_a2 = detectar_evento(resultado_chica["t"], resultado_chica["presion_A"], cfg.fs)
    det_b2 = detectar_evento(resultado_chica["t"], resultado_chica["presion_B"], cfg.fs)
    loc2 = localizar_fuga(det_a2, det_b2, cfg.fs, cfg)
    print(f"Confianza: {loc2['confianza']}")
    print(loc2.get("mensaje", ""))
