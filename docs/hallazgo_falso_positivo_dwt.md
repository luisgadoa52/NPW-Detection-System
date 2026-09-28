# Hallazgo: falso positivo por efecto de borde de la DWT en modo streaming

## Resumen

Durante las pruebas del dashboard en vivo (Fase 5) se encontro que, para
ciertas combinaciones de ubicacion/diametro de fuga, la ubicacion estimada
se alejaba varios cientos o miles de metros del valor real -- muy por
encima del error normal del sistema (decenas de metros, ~1-2%).

Ejemplo real que disparo la investigacion: fuga real a 8200 m, diametro
10 mm. El dashboard en vivo reporto 6602 m (error de 1598 m, ~19.5% de la
longitud del ducto). Corriendo el mismo caso con el detector en modo
"batch" (senal completa, como en las Fases 2-3) el error fue de solo 7.8 m.
La diferencia no esta en la fisica ni en la localizacion (localize_leak.py)
sino en como el dashboard alimenta datos al detector en tiempo real.

## Causa raiz

Los dashboards en vivo simulan la llegada de datos en tiempo real
entregandole al detector ventanas de senal cada vez mas grandes (creciendo
frame a frame). Cada vez, `detectar_evento()` vuelve a correr la
transformada wavelet (DWT, `pywt.wavedec`/`waverec`) desde cero sobre esa
ventana truncada.

La reconstruccion de una DWT tiene un efecto de borde conocido: cerca de
los extremos de la senal, la extension implicita que asume el algoritmo
(por default, simetrica) puede generar una discontinuidad artificial. En
este caso, esa discontinuidad aparecio justo en el ultimo tramo de una
ventana de 630 muestras (6.30 s) y el detector la confundio con una
llegada de onda real.

Se verifico que es un artefacto (no una fuga real) evaluando el mismo
sensor con ventanas de largo vecino:

| Muestras en la ventana | Tiempo | ¿Se detecta un evento? |
|---:|---:|:---:|
| 629 | 6.28 s | No |
| **630** | **6.29 s** | **Si (falso, t=6.26s)** |
| 635 | 6.34 s | No |
| ... | ... | No (hasta el evento real) |

Un evento fisico real no aparece y desaparece asi con uno o dos frames de
diferencia -- esa es la firma de un artefacto numerico de borde, no de una
onda de presion real.

## Correccion aplicada

`detection/live_stream.py` agrega `detectar_evento_streaming()`, que
descarta (no confirma) cualquier deteccion que este a menos de
`margen_confirmacion_s` (1.0 s por defecto) del borde final de la ventana
actual. Si el evento es real, seguira presente cuando llegue mas
informacion y se confirmara con un pequeno retraso adicional. Si era un
artefacto de borde, desaparece al crecer la ventana y nunca se confirma.

Los modulos ya validados de las Fases 2 y 3 (`detect_event.py`,
`localize_leak.py`) no se modificaron -- siguen funcionando exactamente
igual en modo batch. El cambio vive unicamente en la capa de "streaming"
que usan los dashboards.

## Resultado despues de la correccion

| Caso (ubicacion real / diametro real) | Error de ubicacion ANTES | Error de ubicacion DESPUES |
|---|---:|---:|
| 4000 m / 20 mm | 68 m (1.7%) | 68 m (1.7%) -- sin cambio, no estaba afectado |
| 7700 m / 7 mm | Alerta de "baja confianza" -- **tambien era un falso positivo** (con la senal completa, ningun sensor detecta esta fuga) | Correctamente reportado como "sin deteccion" |
| 8200 m / 10 mm | 1598 m (19.5%) | 2 m (0.02%) |

## Costo de la correccion

El sistema ahora tarda ~1 segundo mas en confirmar una alerta (tiempo
adicional para descartar artefactos de borde). Es un compromiso razonable:
ningun sistema de deteccion real dispara una alarma sin algun periodo de
confirmacion, y 1 segundo es insignificante frente a los minutos/horas que
tarda una fuga en volverse economicamente relevante.

## Leccion para produccion

En un sistema real, esto se resolveria de forma mas robusta con una
transformada wavelet no decimada (evita el problema de borde por
construccion) o con procesamiento por bloques con traslape (overlap-save),
en vez de re-analizar desde cero una ventana creciente. El margen de
confirmacion usado aqui es una solucion simple y efectiva para esta
demo, pero se documenta la alternativa "de produccion" a proposito, para
poder hablar de ambas en una entrevista.
