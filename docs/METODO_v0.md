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

## 7. Inversión proporcional al presupuesto P178 (2026-10-02)

Costos unitarios de costo directo en UF (valor UF al 31-12-2024), sacados del presupuesto del
anteproyecto (carpeta Drive «1. Presupuesto»):

| Partida | Unitario | Origen |
|---|---|---|
| Estación motriz / retorno / intermedia (electromecánica) | 116.183 / 67.580 / 62.178 por estación | 14_P178-TEL_TEL.xlsx, T1 y T2 |
| Garaje de cabinas | 45.851 por línea | idem |
| Torres | 39.885 UF/km (31 torres en 4,18 km ≈ 7,4/km) | idem |
| Cables (comunicaciones + portante-tractor) | 4,72 + 8,04 UF/m | idem |
| Cabinas | 39,58 UF/m + 20.030 por estación (ajuste exacto a T1 y T2) | idem |
| Herramientas, repuestos y rescate | 18.624 + 7,13 UF/m por línea | idem |
| Montaje | 6,22 % del suministro | idem |
| Arquitectura | extremo 44.682 · intermedia 42.733 · transbordo 67.701 por estación | 05_P178-TEL_ARQ.xlsx (7 estaciones) |
| Estructuras | 1.756 por estación | Cuadro 1.2-11, ítem 4 / 7 |
| Instalaciones eléctricas | 16.154 por estación y línea | 15_P178-TEL_ELEC.xlsx / 8 |
| Obras urbanas complementarias | 36.490 por estación física | Cuadro 1.2-11, ítems 1–3 y 6–13 / 7 |
| Recargo por ángulo | P246 Cuadro 1.2-5 (punto medio del rango) sobre electromecánica y arquitectura | P246 |
| GG y U · IVA | 35 % · 19 % | P178 |

**Contraste con el anteproyecto completo:**
- Costo directo: 2.140.543 UF contra 2.127.475 UF del P178 (+0,6 %).
- Total sin expropiación: 3.438.782 UF contra 3.417.788 UF (+0,6 %).
- Electromecánica por tramo: dentro de ±2,3 %.

**Límite:** las torres se estiman por km, no por la topografía del corte.

## 8. Motor fuera del Gran Concepción

Prueba en Valparaíso (2026-10-02, proyecto de prueba retirado del índice). Todo funcionó:
- huso UTM 19;
- descarga automática del tile Copernicus;
- catastro SII y escrituras.

**Advertencia:** fuera del vuelo SECTRA, las edificaciones vienen de OSM. Ahí la cobertura es
incompleta: 2.441 edificios contra 6.174 lotes SII, y la regla estima 5.215 viviendas contra 8.244
roles habitacionales. **Fuera del Gran Concepción, el conteo de viviendas bajo la faja queda
subestimado.** Hay que sumar otra fuente de huellas (Microsoft o Google Open Buildings) antes de
usarlo en otras ciudades.

## 9. Rasante y torres (2026-10-02)

El cable no puede quedar bajo la topografía. Entre dos estaciones se parte de la cuerda recta, con el
cable a `h_est` (8 m) sobre cada andén. Luego se insertan apoyos de forma recursiva:
- en el punto de mayor déficit de gálibo, con la cima a gálibo (10 m) sobre el terreno, hasta que
  ningún punto del tramo quede por debajo;
- se excluye la zona de estación (media huella + 10 m), donde el cable baja al andén;
- después se agregan apoyos sobre la misma recta donde el vano supera 320 m.

El modelo no incluye catenaria.

Contraste con el anteproyecto: **30 torres (19 + 11) contra 31 del P178 (21 + 10)**. Torre más alta:
31 m, contra 42 m en el P178. Costo directo: 2.135.103 UF, +0,4 % sobre el del P178. El P178 trae pares
de torres a 10–19 m (P9–P10, P17–P18), por eso la fusión de apoyos cercanos (`vano_min`) queda apagada
por defecto. Cada torre se valoriza a 5.374 UF (166.590 UF / 31).

## 10. Prioridad de estaciones

**Población potencial** de una estación: personas dentro de su cobertura, aunque otra estación les dé
un menor tiempo total. La prioridad es relativa a la estación de mayor población potencial: alta
≥ 66 %, media ≥ 33 %, baja bajo eso. La población **exclusiva** (asignada por menor tiempo al centro)
se reporta aparte.
