# Teleférico de Talcahuano — herramienta de trazados

**Abrir la herramienta:** https://romedinag-tech.github.io/teleferico-talcahuano/

Herramienta para probar trazados de teleférico urbano. Las estaciones se ubican sobre el mapa y el
navegador calcula:

- población a ≤ N minutos de caminata, con isócronas por la red peatonal y corrección por pendiente;
- tiempo puerta a puerta al centro, desagregado en acceso, espera, viaje, transbordo y egreso;
- largo, desnivel, ángulo y tiempo por tramo;
- corte topográfico;
- viviendas y terrenos bajo la faja de sobrevuelo;
- costo de expropiación en dos escenarios: **E1**, que expropia la faja, y **E2**, con la norma
  complementada para permitir el sobrevuelo.

Trae precargado el anteproyecto SECTRA P178 (2025) con el eje oficial del MTT.

**Versión pública.** Los resultados se muestran agregados por trazado. No incluye atributos del
catastro SII por lote ni por edificio, y los valores de suelo y construcción son medianas de
escrituras de toda el área.

Fuentes: Censo 2024 (INE) · catastro SII · ortofoto SECTRA 2023-24 · OpenStreetMap ·
Copernicus GLO-30 · SII F2890 (agregado) · SECTRA P178/P246 · MTT.

Método: `docs/METODO_v0.md`. Los scripts de `scripts/` reconstruyen la herramienta desde datos
locales que no se publican.
