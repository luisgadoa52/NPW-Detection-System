"""
detect_event.py
Fase 2 - Deteccion del instante de llegada de la onda de presion negativa
(NPW) en una senal de presion ruidosa.

este modulo NUNCA ve el diccionario 'meta' del simulador
(ubicacion real, t_inicio real, etc.). Solo recibe la senal cruda, como lo
haria un sensor de verdad. El 'meta' se usa unicamente despues, para medir
que tan bien le atino el detector (validacion), nunca dentro del algoritmo.

Metodo:
1. Denoising con transformada wavelet discreta (DWT): descompone la senal
   en coeficientes de detalle/aproximacion, aplica un umbral suave
   (soft-thresholding, Donoho-Johnstone) para quitar el ruido de
   instrumento y la vibracion de bombeo, y reconstruye la senal limpia.
2. Deteccion sobre la derivada de la senal limpia: se calcula la
   desviacion estandar de la derivada en una ventana de referencia
   ("baseline", antes de que ocurra cualquier evento) y se dispara la
   alarma en el primer instante donde la derivada cae de forma sostenida
   por debajo de -k * sigma.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pywt


@dataclass
class DetectorConfig:
    wavelet: str = "db4"  # familia wavelet Daubechies-4, buena para capturar transitorios
    nivel_descomposicion: int = 4  # niveles de la DWT
    ventana_baseline_s: float = 5.0  # segundos usados para calibrar el umbral (antes del evento)
    k_umbral: float = 5.0  # multiplo de sigma para disparar la alarma
    muestras_confirmacion: int = 3  # muestras consecutivas requeridas para confirmar el evento


def _denoise_wavelet(senal: np.ndarray, cfg: DetectorConfig) -> np.ndarray:
    """Quita ruido de alta frecuencia con umbralizado suave sobre los coeficientes wavelet."""
    coeffs = pywt.wavedec(senal, cfg.wavelet, level=cfg.nivel_descomposicion)
    # Estimador robusto de la desviacion estandar del ruido a partir del nivel
    # de detalle mas fino (formula estandar de Donoho-Johnstone)
    sigma_ruido = np.median(np.abs(coeffs[-1])) / 0.6745
    umbral = sigma_ruido * np.sqrt(2 * np.log(len(senal)))
    coeffs_limpios = [coeffs[0]] + [pywt.threshold(c, umbral, mode="soft") for c in coeffs[1:]]
    senal_limpia = pywt.waverec(coeffs_limpios, cfg.wavelet)
    return senal_limpia[: len(senal)]  # waverec puede regresar 1 muestra de mas


def detectar_evento(
    t: np.ndarray,
    presion: np.ndarray,
    fs: float,
    cfg: DetectorConfig | None = None,
) -> dict:
    """
    Detecta el instante en que llega una onda de presion negativa a este
    sensor, mirando unicamente la senal (nunca el ground truth).

    Regresa un dict con:
        'detectado'    -> bool
        't_deteccion'  -> tiempo estimado de llegada [s] (None si no se detecto)
        'senal_limpia' -> la senal ya sin ruido (para graficar)
        'derivada'     -> la derivada usada para la deteccion (para graficar)
        'umbral'       -> el umbral que se calculo
    """
    if cfg is None:
        cfg = DetectorConfig()

    senal_limpia = _denoise_wavelet(presion, cfg)
    derivada = np.gradient(senal_limpia, 1 / fs)

    n_baseline = int(cfg.ventana_baseline_s * fs)
    sigma_derivada = np.std(derivada[:n_baseline])
    umbral = -cfg.k_umbral * sigma_derivada

    bajo_umbral = derivada < umbral
    t_deteccion = None
    for i in range(len(bajo_umbral) - cfg.muestras_confirmacion):
        if np.all(bajo_umbral[i : i + cfg.muestras_confirmacion]):
            t_deteccion = float(t[i])
            break

    return {
        "detectado": t_deteccion is not None,
        "t_deteccion": t_deteccion,
        "senal_limpia": senal_limpia,
        "derivada": derivada,
        "umbral": umbral,
    }


if __name__ == "__main__":
    import os
    import sys

    import matplotlib.pyplot as plt

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulation"))
    from simulate_leak import PipelineConfig, simular_fuga

    cfg_ducto = PipelineConfig()
    resultado = simular_fuga(
        ubicacion=4000.0,
        diametro=0.02,
        t_inicio=10.0,
        cfg=cfg_ducto,
        semilla=42,
    )

    fs = cfg_ducto.fs
    t = resultado["t"]
    meta = resultado["meta"]

    det_a = detectar_evento(t, resultado["presion_A"], fs)
    det_b = detectar_evento(t, resultado["presion_B"], fs)

    print("=== Deteccion de evento (el algoritmo no vio el ground truth) ===")
    for nombre, det, t_real in [
        ("Sensor A", det_a, meta["t_llegada_A_s"]),
        ("Sensor B", det_b, meta["t_llegada_B_s"]),
    ]:
        if det["detectado"]:
            error_ms = (det["t_deteccion"] - t_real) * 1000
            print(
                f"{nombre}: detectado en t={det['t_deteccion']:.3f} s "
                f"(real: {t_real:.3f} s, error: {error_ms:+.1f} ms)"
            )
        else:
            print(f"{nombre}: NO se detecto ningun evento")

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    axes[0].plot(t, resultado["presion_A"] / 1e5, linewidth=0.6, color="tab:gray", label="Cruda")
    axes[0].plot(
        t, det_a["senal_limpia"] / 1e5, linewidth=1.2, color="tab:blue", label="Denoised (wavelet)"
    )
    axes[0].set_ylabel("Presion [bar]")
    axes[0].set_title("Sensor A: senal cruda vs. denoised")
    axes[0].legend(loc="lower right")

    axes[1].plot(t, det_a["derivada"] / 1e5, linewidth=0.8, color="tab:blue")
    axes[1].axhline(det_a["umbral"] / 1e5, color="tab:red", linestyle="--", label="Umbral adaptativo")
    axes[1].set_ylabel("dP/dt [bar/s]")
    axes[1].set_title("Derivada de la senal denoised")
    axes[1].legend(loc="lower right")

    axes[2].plot(t, resultado["presion_A"] / 1e5, linewidth=0.6, label="Sensor A")
    axes[2].plot(t, resultado["presion_B"] / 1e5, linewidth=0.6, label="Sensor B")
    if det_a["detectado"]:
        axes[2].axvline(det_a["t_deteccion"], color="tab:blue", linestyle=":", label="Deteccion A")
    if det_b["detectado"]:
        axes[2].axvline(det_b["t_deteccion"], color="tab:orange", linestyle=":", label="Deteccion B")
    axes[2].set_xlabel("Tiempo [s]")
    axes[2].set_ylabel("Presion [bar]")
    axes[2].set_title("Instantes de deteccion en ambos sensores")
    axes[2].legend(loc="lower right")

    fig.tight_layout()
    fig.savefig("deteccion_evento_ejemplo.png", dpi=150)
    print("\nGrafica guardada en deteccion_evento_ejemplo.png")
