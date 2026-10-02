# Método de la herramienta — versión 0 (acordado con Rodrigo el 2026-10-02)

Documento de decisiones. Lo marcado **[propuesta]** espera confirmación; lo demás está acordado.

## 1. Tiempo puerta a puerta, desagregado

El resultado se reporta por componente, nunca sólo el total:

| Componente | Teleférico | Bus (matriz del motor TP) |
|---|---|---|
| Acceso | caminata origen → estación (red peatonal + pendiente) | caminata origen → paradero |
| Espera | ½ intervalo entre cabinas (13,8 s → ≈ 7 s) | ½ intervalo observado (GPS/GTFS) |
| Viaje | longitud / 6 m/s + 50 s por estación intermedia + 24 s por quiebre | tiempo en vehículo medido por GPS |
| Transbordo | si cambia de tramo (p. ej. en Las Antenas) | si la ruta lo exige |
| Egreso | caminata estación → destino | caminata paradero → destino |

Parámetros del teleférico tomados del P178/P246 (ver `ANTECEDENTES_DRIVE.md`).

## 2. Zonificación hexagonal para la matriz de buses

H3 v4 sobre el área de estudio candidata (EOD cerros + centro), medido el 2026-10-02:

| Resolución | Lado | Área | Hexágonos en el área | Población mediana por hexágono | Error medio de acceso por usar el centroide |
|---|---|---|---|---|---|
| 8 | 531 m | 73,7 ha | 13 | 2.513 | ≈ 6,3 min |
| **9 [propuesta]** | 201 m | 10,5 ha | 88 | 454 | ≈ 2,4 min |
| 10 | 76 m | 1,5 ha | 592 | 97 | ≈ 0,9 min |

**Propuesta: resolución 9 para la matriz de buses.** Es el grano que el GPS sostiene: los bloques de velocidad del motor TP son de 200 m. Dentro de la herramienta, la población y la caminata al teleférico se calculan a nivel de manzana, no de hexágono, así que el grano grueso sólo afecta al lado del bus. El error de acceso se estimó como 0,6 × lado × 1,3 (rodeo) ÷ 1,1 m/s; es un orden de magnitud, no una medición.

## 3. Topografía

Copernicus GLO-30 DSM, tile `S37_W074`, en `datos/crudo/dem/`. **Validado contra las 31 torres del
anteproyecto P178**: sesgo −2,8 m (mediana −3,2), MAE 3,1 m, rango −5,6 a +2,9 m. El sesgo
casi constante sugiere una diferencia de datum vertical (EGM2008 contra el del levantamiento), no ruido.
Es un DSM (superficie), aunque en las torres no se ve el sobreelevado por edificios o árboles. El corte
de la herramienta usará Copernicus **sin corregir**, declarando el sesgo, salvo que se decida
desplazarlo +3,2 m para calzar con el datum del estudio.

El DWG general (726 MB) queda como fuente posible de curvas a 5 m; no se ha intentado extraer.

## 4. Expropiación y sobrevuelo

1. **Faja de afectación** bajo el trazado, de ancho parametrizable. Por defecto 15 m (7,5 m a cada
   lado del eje), que es el valor del P178 (Cap 14 §14.1.5). Se suman las huellas de estación
   (parámetro de largo × ancho) y las bases de torre.
2. **Predios afectados**: polígonos SII (`comunas_parquet/Talcahuano_8206`) que intersectan la faja.
   Para cada uno se registra la superficie de terreno dentro de la faja.
3. **Edificaciones y viviendas sobrevoladas**: huellas SECTRA (`EDIFICACION.shp`) que intersectan la
   faja. Las viviendas se cuentan como roles habitacionales SII del predio, de modo que un edificio de
   16 departamentos cuenta 16. Las huellas sin rol SII (tomas) se cuentan aparte.
4. **Valor**: UF/m² observado en las escrituras F2890 del área de estudio (2015–2025), por tipología
   (casa, departamento, sitio), sin estacionamientos ni bodegas. Se reporta mediana y rango P25–P75.
   - Estación o torre sobre el predio → expropiación total del predio.
   - **Faja de sobrevuelo sobre viviendas → se pinta como capa en el mapa y se analiza el efecto de
     expropiar esas viviendas** (acordado 2026-10-02): número de viviendas y hogares, personas
     desplazadas y costo en UF. La expropiación no se limita a pilonas y estaciones.
   - Faja sobre terreno sin edificación → **expropiación del terreno bajo la faja, a valor de suelo
     solo, sin construcción** (acordado 2026-10-02). Bajo el cable queda una servidumbre, pero se
     valoriza como terreno expropiado.

### 4.1 Escenarios normativos (contexto de Rodrigo, 2026-10-02)

En Chile no hay norma que diga si el sobrevuelo de un teleférico obliga a expropiar. El precedente es
el Teleférico Bicentenario, que tuvo demandas, entre ellas la de un cementerio por el sobrevuelo. Ante
ese vacío legal, la herramienta **no elige un régimen: muestra los escenarios lado a lado**.

| Escenario | Qué se expropia | Para qué sirve |
|---|---|---|
| **E1 — Expropiar la faja** | Estaciones y torres (predio completo); viviendas bajo la faja (terreno + construcción); terreno sin construir bajo la faja (sólo suelo) | Cuánto cuesta el sobrevuelo si se resuelve expropiando: cota superior |
| **E2 — Norma complementada que permite el sobrevuelo** | Sólo estaciones y torres | Cuánto cuesta el proyecto si se complementa la ley; la diferencia E1 − E2 es lo que vale la modificación normativa |

La diferencia E1 − E2, en UF y en viviendas y personas desplazadas, es el resultado que importa para la
discusión normativa. Se reporta por tramo y por estación.
5. **Resultado del contraste (2026-10-02, `scripts/02_contraste_dgc.py`).** Eje exacto del anteproyecto: las torres de cada tramo están en una recta (desvío 0,0 m) y se extienden a las estaciones terminales con las progresivas del plano TEL (`datos/referencia/eje_anteproyecto_P178.geojson`). Faja de 15 m:

   | Tramo | DGC | Herramienta |
   |---|---|---|
   | T1 Las Antenas–Centinela II | 4 edificios, 64 viviendas | **4 edificios, 61 viviendas** (regla volumétrica) |
   | T2 completo | 74 terrenos con vivienda (62 regulares + 12 tomas) | **69 lotes SII con vivienda**; las tomas no tienen rol y aún no se identifican |

   **Dos métricas distintas**, que la herramienta reporta por separado:
   - **Terrenos con vivienda sobrevolados**: lotes SII habitacionales que toca la faja. Es lo que contó la DGC en el T2.
   - **Viviendas bajo la faja**: edificios que toca la faja. En lotes multivivienda: huella × pisos SII ÷ m² construidos por vivienda del lote (el lote que más se superpone con el edificio). En lotes de 1–2 viviendas: sus roles, asignados sólo al edificio mayor del lote. Repartir los roles por superficie daba 43 en el T1, y contar todos los roles de los lotes tocados daba 168.
   - **Expropiación E1**: edificio habitacional bajo la faja → terreno + construcción; lote tocado sin edificio bajo la faja → sólo el suelo bajo la faja.
6. **Contraste obligatorio** antes de dar por buena la herramienta. Con el anteproyecto debe
   reproducir lo que contó la DGC: el T1 sobre 4 edificios de 16 departamentos, y el T2 sobre 74
   terrenos con vivienda (62 regulares y 12 tomas).

🔴 El valor sale de transacciones privadas: **la herramienta es de uso local y nunca va a GitHub Pages.**

## 5. Área de influencia y área de estudio

- **Área de influencia de cada estación**: isócrona de caminata por la red, de 2 a 10 minutos a
  1,1 m/s (P178 Cap 14). **[propuesta]** La velocidad se corrige por pendiente con el DEM.
- **Área de estudio: candidata B** (zonas EOD de las macrozonas Cerros Nte/Pte/Ote + Centro), elegida por Rodrigo el 2026-10-02. Hexágonos H3 **resolución 9** confirmados.

## 6. Área de estudio — candidatas

| Candidata | Fuente | Superficie | Manzanas censo 2024 | Personas | Hogares |
|---|---|---|---|---|---|
| A. `AREA_DIVIDIDA.kmz` | Drive MTT, «Cartografía Base»: zona STU dividida para teleférico | 2.660 ha | 388 | 36.592 | 12.193 |
| B. Zonas EOD de las macrozonas Cerros Nte/Pte/Ote + Centro (`MZONA_TELE`, 15 zonas) | `Zona_EOD_2020_Talcahuano_v2.xlsx` + `EODs/GEO` | 748 ha | 364 | 34.530 | 11.688 |

La A incluye la península de Tumbes (zonas forestales de 900 y 1.115 ha) y sólo una zona del centro.
La B incluye el centro y deja fuera el bosque de Tumbes. Población: suma de manzanas cuyo centroide cae
dentro de cada candidata.
