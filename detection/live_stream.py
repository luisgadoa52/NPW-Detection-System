"""
live_stream.py
Envoltorio de deteccion para uso en vivo/streaming (los dashboards de la
Fase 5 y 5b), separado de detect_event.py a proposito: detect_event.py es el
modulo validado de la Fase 2 y se deja intacto (funciona perfecto cuando se
le da la senal ya completa, en modo "batch").

Por que existe este archivo (bug real encontrado y documentado):
------------------------------------------------------------------
Los dashboards en vivo no le dan al detector la senal completa de una vez:
se la van dando en pedazos cada vez mas grandes, como llegaria de verdad de
un sensor. Volver a correr la transformada wavelet (DWT) desde cero sobre
cada pedazo truncado tiene un efecto de borde conocido: justo en el corte
final de la ventana, la reconstruccion (waverec) puede generar un pico
artificial que no corresponde a ningun evento fisico real. Se comprobo
numericamente (ver docs/hallazgo_falso_positivo_dwt.md) que ese pico
aparece y desaparece de forma no monotonica segun el largo exacto de la
ventana -- la firma clasica de un artefacto de borde, no de una fuga real.

La correccion: no se confia en una deteccion hasta que sigue siendo visible
despues de que llegue al menos 'margen_confirmacion_s' segundos mas de
datos. Un artefacto de borde desaparece en cuanto deja de estar justo en el
borde; un evento real sigue ahi. El costo es una latencia adicional de
~margen_confirmacion_s segundos antes de reportar una alerta -- un
compromiso razonable y, de hecho, realista: ningun sistema de deteccion de
verdad reporta una alarma instantaneamente sin ningun periodo de
confirmacion.
"""

from __future__ import annotations

from detect_event import DetectorConfig, detectar_evento


def detectar_evento_streaming(
    t,
    presion,
    fs: float,
    cfg: DetectorConfig | None = None,
    margen_confirmacion_s: float = 1.0,
) -> dict:
    """
    Igual que detectar_evento(), pero pensado para llamarse repetidamente
    con una ventana de datos que va creciendo (streaming). Descarta
    (reporta como no detectado) cualquier evento que este demasiado cerca
    del borde final de la ventana actual, porque ahi es donde la DWT puede
    generar falsos positivos por efecto de borde.

    Regresa el mismo dict que detectar_evento(), con dos posibles cambios:
    - Si la deteccion esta demasiado cerca del borde: 'detectado' se fuerza
      a False y 't_deteccion' a None (se reevaluara en la siguiente
      llamada, con mas datos, cuando ya no este en el borde).
    - Se agrega la llave 'pendiente_confirmacion' (bool) para que quien
      llama pueda distinguir "no hay evento" de "hay un evento que
      todavia se esta confirmando".
    """
    det = detectar_evento(t, presion, fs, cfg)
    det["pendiente_confirmacion"] = False

    if not det["detectado"]:
        return det

    margen_muestras = int(margen_confirmacion_s * fs)
    idx_deteccion = int(det["t_deteccion"] * fs)
    idx_ahora = len(presion) - 1

    if (idx_ahora - idx_deteccion) < margen_muestras:
        det["detectado"] = False
        det["t_deteccion"] = None
        det["pendiente_confirmacion"] = True

    return det
