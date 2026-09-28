"""
simulate_leak.py
Fase 1 - Simulacion fisica de fugas en ductos mediante el metodo de onda de
presion negativa (NPW - Negative Pressure Wave).

Genera series de tiempo sinteticas de presion en dos sensores (A y B)
separados una distancia L a lo largo de un ducto, dado un evento de fuga
(ubicacion, diametro equivalente e instante de inicio). Estas series son
el "ground truth" con ruido realista que usaremos en la Fase 2 para
probar el algoritmo de deteccion (denoising + localizacion TDOA).

Fisica utilizada:
- Velocidad de la onda de presion negativa: ecuacion de Korteweg (corrige
  la velocidad del sonido en el fluido por la elasticidad de la tuberia).
- Amplitud de la onda generada por la fuga: relacion de Joukowsky
  (la misma matematica del golpe de ariete), ligada al caudal que escapa
  por el orificio.
- Caudal de fuga: ecuacion de orificio (Torricelli generalizado).

Nota honesta: este es un modelo de onda viajera simplificado, no resuelve
las ecuaciones completas de flujo transitorio 1D por Metodo de las
Caracteristicas (MOC). Es suficiente para generar datos realistas con los
que probar el pipeline de deteccion de principio a fin; se puede sofisticar
mas adelante (Fase 1B) si se quiere mayor rigor academico.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PipelineConfig:
    """Parametros fisicos del ducto y del fluido (crudo)."""

    longitud: float = 10_000.0  # distancia entre sensores A y B [m]
    diametro_ducto: float = 0.3  # diametro interno del ducto [m] (~12 in)
    espesor_pared: float = 0.008  # espesor de pared de acero [m]
    modulo_young_acero: float = 200e9  # modulo de Young del acero [Pa]
    modulo_compresibilidad_fluido: float = 1.5e9  # modulo K del crudo [Pa]
    densidad_fluido: float = 850.0  # densidad del crudo [kg/m3]
    presion_base: float = 6.0e6  # presion de operacion, manometrica [Pa] (~60 bar)
    coef_descarga: float = 0.62  # Cd tipico de un orificio de borde afilado
    atenuacion_por_km: float = 0.03  # perdida fraccional de amplitud por km recorrido
    fs: float = 100.0  # frecuencia de muestreo de los sensores [Hz]

    @property
    def area_ducto(self) -> float:
        return np.pi / 4 * self.diametro_ducto**2

    @property
    def velocidad_onda(self) -> float:
        """Velocidad de propagacion de la NPW (ecuacion de Korteweg)."""
        c_fluido = np.sqrt(self.modulo_compresibilidad_fluido / self.densidad_fluido)
        correccion = 1 + (self.modulo_compresibilidad_fluido * self.diametro_ducto) / (
            self.modulo_young_acero * self.espesor_pared
        )
        return c_fluido / np.sqrt(correccion)


def caudal_fuga(diametro_fuga: float, cfg: PipelineConfig) -> float:
    """Ecuacion de orificio: caudal que escapa por un agujero de diametro dado."""
    area_fuga = np.pi / 4 * diametro_fuga**2
    return cfg.coef_descarga * area_fuga * np.sqrt(2 * cfg.presion_base / cfg.densidad_fluido)


def amplitud_onda(diametro_fuga: float, cfg: PipelineConfig) -> float:
    """Relacion de Joukowsky: amplitud de la onda de presion generada por la fuga."""
    q_fuga = caudal_fuga(diametro_fuga, cfg)
    delta_v = q_fuga / cfg.area_ducto  # cambio de velocidad equivalente en el ducto
    return cfg.densidad_fluido * cfg.velocidad_onda * delta_v


def _forma_pulso(t: np.ndarray, t_llegada: float, amplitud: float, tau: float = 3.0) -> np.ndarray:
    """
    Forma de la caida de presion al paso de la onda: caida rapida y
    recuperacion exponencial (efecto de 'line pack' acomodandose).
    """
    dt = t - t_llegada
    return np.where(dt >= 0, -amplitud * np.exp(-dt / tau), 0.0)


def simular_fuga(
    ubicacion: float,
    diametro: float,
    t_inicio: float,
    duracion: float = 60.0,
    cfg: PipelineConfig | None = None,
    semilla: int | None = None,
) -> dict:
    """
    Simula las series de presion en los sensores A (x=0) y B (x=L) ante
    una fuga puntual.

    Parametros
    ----------
    ubicacion : distancia del sensor A al punto de fuga [m], entre 0 y cfg.longitud
    diametro  : diametro equivalente del orificio de fuga [m]
    t_inicio  : instante en que ocurre la fuga [s]
    duracion  : duracion total de la simulacion [s]
    cfg       : configuracion fisica del ducto (usa valores por defecto si None)
    semilla   : semilla para el generador de ruido (reproducibilidad)

    Regresa
    -------
    dict con:
        't'         -> vector de tiempo [s]
        'presion_A' -> serie de presion en sensor A [Pa]
        'presion_B' -> serie de presion en sensor B [Pa]
        'meta'      -> dict con el ground truth (ubicacion, diametro, t_inicio,
                        velocidad de onda, amplitud generada, tiempos de llegada)
    """
    if cfg is None:
        cfg = PipelineConfig()
    if not 0 <= ubicacion <= cfg.longitud:
        raise ValueError("La ubicacion de la fuga debe estar entre 0 y cfg.longitud")

    rng = np.random.default_rng(semilla)
    n_muestras = int(duracion * cfg.fs)
    t = np.arange(n_muestras) / cfg.fs

    c = cfg.velocidad_onda
    amplitud_generada = amplitud_onda(diametro, cfg)

    dist_a = ubicacion
    dist_b = cfg.longitud - ubicacion

    atenuacion_a = max(0.0, 1 - cfg.atenuacion_por_km * dist_a / 1000)
    atenuacion_b = max(0.0, 1 - cfg.atenuacion_por_km * dist_b / 1000)

    t_llegada_a = t_inicio + dist_a / c
    t_llegada_b = t_inicio + dist_b / c

    presion_a = np.full(n_muestras, cfg.presion_base)
    presion_b = np.full(n_muestras, cfg.presion_base)

    presion_a = presion_a + _forma_pulso(t, t_llegada_a, amplitud_generada * atenuacion_a)
    presion_b = presion_b + _forma_pulso(t, t_llegada_b, amplitud_generada * atenuacion_b)

    # Ruido de sensor: ruido gaussiano de instrumento + vibracion de bombeo (senoidal)
    ruido_instrumento_a = rng.normal(0, cfg.presion_base * 0.0015, n_muestras)
    ruido_instrumento_b = rng.normal(0, cfg.presion_base * 0.0015, n_muestras)
    vibracion_bombeo = cfg.presion_base * 0.0008 * np.sin(2 * np.pi * 2.0 * t)

    presion_a = presion_a + ruido_instrumento_a + vibracion_bombeo
    presion_b = presion_b + ruido_instrumento_b + vibracion_bombeo

    return {
        "t": t,
        "presion_A": presion_a,
        "presion_B": presion_b,
        "meta": {
            "ubicacion_real_m": ubicacion,
            "diametro_m": diametro,
            "t_inicio_s": t_inicio,
            "velocidad_onda_mps": c,
            "amplitud_generada_pa": amplitud_generada,
            "t_llegada_A_s": t_llegada_a,
            "t_llegada_B_s": t_llegada_b,
            "longitud_ducto_m": cfg.longitud,
        },
    }


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    cfg = PipelineConfig()
    print(f"Velocidad de la onda (Korteweg): {cfg.velocidad_onda:.1f} m/s")

    resultado = simular_fuga(
        ubicacion=4000.0,  # fuga a 4 km del sensor A
        diametro=0.02,  # agujero equivalente de 2 cm (toma clandestina tipica)
        t_inicio=10.0,
        semilla=42,
    )

    meta = resultado["meta"]
    print(
        f"Fuga simulada en x={meta['ubicacion_real_m']} m, "
        f"diametro={meta['diametro_m'] * 1000:.1f} mm"
    )
    print(f"Amplitud de onda generada: {meta['amplitud_generada_pa'] / 1e5:.3f} bar")
    print(
        f"Llegada esperada a A: {meta['t_llegada_A_s']:.2f} s, "
        f"a B: {meta['t_llegada_B_s']:.2f} s"
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(resultado["t"], resultado["presion_A"] / 1e5, label="Sensor A", linewidth=0.8)
    ax.plot(resultado["t"], resultado["presion_B"] / 1e5, label="Sensor B", linewidth=0.8)
    ax.axvline(
        meta["t_inicio_s"], color="gray", linestyle="--", linewidth=0.8, label="Inicio de fuga"
    )
    ax.set_xlabel("Tiempo [s]")
    ax.set_ylabel("Presion [bar]")
    ax.set_title("Simulacion de fuga - Onda de presion negativa")
    ax.legend()
    fig.tight_layout()
    fig.savefig("simulacion_fuga_ejemplo.png", dpi=150)
    print("Grafica guardada en simulacion_fuga_ejemplo.png")
