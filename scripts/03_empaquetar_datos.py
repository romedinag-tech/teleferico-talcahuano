"""Empaqueta las capas de datos/cache en un JSON compacto que se incrusta en el HTML.

Entrada: salidas de 01_preparar_capas.py y datos/referencia/. Salida: datos/cache/paquete_herramienta.json
Correr: python -X utf8 scripts/03_empaquetar_datos.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RAIZ = Path(__file__).resolve().parents[1]
C = RAIZ / "datos" / "cache"
REF = RAIZ / "datos" / "referencia"
UTM = 32718
ND = 6  # decimales en grados (~0,1 m)


def anillos(geom, tol_m=0.5):
    """Polígono (EPSG:4326) → lista de anillos exteriores [[lon,lat],...] redondeados."""
    out = []
    geoms = getattr(geom, "geoms", [geom])
    for g in geoms:
        if g.geom_type != "Polygon" or g.is_empty:
            continue
        out.append([[round(c[0], ND), round(c[1], ND)] for c in g.exterior.coords])  # ignora Z
    return out


def simplificar(gdf, tol_m):
    g = gdf.to_crs(UTM).copy()
    g["geometry"] = g.simplify(tol_m, preserve_topology=True)
    return g.to_crs(4326)


# --- área de estudio
area = gpd.read_file(C / "area_estudio.geojson")

# --- manzanas: centroide, población y personas por vivienda ocupada
mz = gpd.read_parquet(C / "capa_manzanas.parquet")
mz_utm = mz.to_crs(UTM)
cen = mz_utm.representative_point().to_crs(4326)
mz["lon"], mz["lat"] = cen.x.round(ND), cen.y.round(ND)
mz["en_area"] = mz_utm.representative_point().within(area.to_crs(UTM).union_all())
mz["per_viv"] = (mz.n_per / mz.n_vp_ocupada).where(mz.n_vp_ocupada > 0)

# --- red peatonal → grafo (nodos con cota DEM)
red = gpd.read_parquet(C / "capa_red_peatonal.parquet")
nodos = {}
for r in red.itertuples():
    (x0, y0), (x1, y1) = r.geometry.coords[0], r.geometry.coords[-1]
    nodos.setdefault(r.n_a, (x0, y0)); nodos.setdefault(r.n_b, (x1, y1))
ids = list(nodos); idx = {n: i for i, n in enumerate(ids)}
xy = np.array([nodos[n] for n in ids])

dem = np.load(C / "dem_area.npz")
z, xll, yll, cell = dem["z"], float(dem["xll"]), float(dem["yll"]), float(dem["cell"])
nfil, ncol = z.shape


def cota(lon, lat):
    """Bilineal sobre la grilla AAIGrid (fila 0 = norte)."""
    c = (lon - xll) / cell - 0.5
    f = (yll + nfil * cell - lat) / cell - 0.5
    c0 = np.clip(np.floor(c).astype(int), 0, ncol - 2); f0 = np.clip(np.floor(f).astype(int), 0, nfil - 2)
    dc, df = np.clip(c - c0, 0, 1), np.clip(f - f0, 0, 1)
    return (z[f0, c0] * (1 - dc) * (1 - df) + z[f0, c0 + 1] * dc * (1 - df)
            + z[f0 + 1, c0] * (1 - dc) * df + z[f0 + 1, c0 + 1] * dc * df)


zn = cota(xy[:, 0], xy[:, 1])
aristas = {}
for r in red.itertuples():
    a, b = idx[r.n_a], idx[r.n_b]
    if a == b:
        continue
    k = (min(a, b), max(a, b))
    aristas[k] = min(aristas.get(k, 1e9), r.largo_m)
grafo = {"n": [[round(x, ND), round(y, ND), round(float(h), 1)] for (x, y), h in zip(xy, zn)],
         "e": [[a, b, round(L, 1)] for (a, b), L in aristas.items()]}

# manzanas → nodo más cercano (distancia de enganche en metros)
lat0 = float(np.mean(xy[:, 1]))
kx, ky = 111320 * np.cos(np.radians(lat0)), 110540
tree = cKDTree(np.c_[xy[:, 0] * kx, xy[:, 1] * ky])
d, j = tree.query(np.c_[mz.lon * kx, mz.lat * ky])
mz["nodo"], mz["enganche_m"] = j, d.round(1)
manzanas = [[r.lon, r.lat, None if pd.isna(r.n_per) else int(r.n_per), None if pd.isna(r.n_hog) else int(r.n_hog),
             None if pd.isna(r.n_vp) else int(r.n_vp), None if pd.isna(r.per_viv) else round(float(r.per_viv), 2),
             int(r.nodo), float(r.enganche_m), int(r.en_area)] for r in mz.itertuples()]
mz_s = simplificar(mz[["n_per", "geometry"]], 1.0)
manzanas_geo = [anillos(g) for g in mz_s.geometry]

# --- predios (lotes SII agregados) y edificaciones con la regla de viviendas
pr = gpd.read_parquet(C / "capa_predios.parquet").reset_index(drop=True)
ed = gpd.read_parquet(C / "capa_edificaciones.parquet").reset_index(drop=True)
pr["pid"], ed["eid"] = pr.index, ed.index
pr_u, ed_u = pr.to_crs(UTM), ed.to_crs(UTM)
x = gpd.overlay(ed_u[["eid", "geometry"]], pr_u[["pid", "n_hab", "sup_cons", "pisos", "geometry"]],
                how="intersection", keep_geom_type=True)
x["a"] = x.area
dom = x.sort_values("a").drop_duplicates("eid", keep="last")[["eid", "pid"]]
dom = dom.merge(pr[["pid", "n_hab", "sup_cons", "pisos", "destinos"]], on="pid").merge(ed[["eid", "area_m2"]], on="eid")
m2_viv = (dom.sup_cons / dom.n_hab).where((dom.sup_cons > 0) & (dom.n_hab > 0))
vol = dom.area_m2 * dom.pisos.fillna(1) / m2_viv
mayor = dom.sort_values("area_m2").drop_duplicates("pid", keep="last").eid
chico = dom.n_hab.where(dom.eid.isin(mayor), 0)
dom["viv"] = vol.where(dom.n_hab > 2, chico).fillna(chico).fillna(0)
# superficie construida atribuida al edificio (para valorizar construcción)
dom["sup_cons_e"] = np.where(dom.n_hab > 2, dom.area_m2 * dom.pisos.fillna(1),
                             np.where(dom.eid.isin(mayor), dom.sup_cons.fillna(0), 0))
dom["pisos_e"] = dom.pisos
pr_area = pr_u.area
dom["cuota_suelo"] = np.where(dom.n_hab > 2, dom.pid.map(pr_area) * (dom.viv / dom.n_hab).clip(upper=1), 0)
ed = ed.merge(dom[["eid", "pid", "viv", "sup_cons_e", "pisos_e", "n_hab", "cuota_suelo"]], on="eid", how="left")
ed["cuota_suelo"] = ed.cuota_suelo.fillna(0)
ed[["viv", "sup_cons_e"]] = ed[["viv", "sup_cons_e"]].fillna(0)
# manzana del edificio → personas por vivienda
j2 = gpd.sjoin(ed_u.assign(geometry=ed_u.representative_point())[["eid", "geometry"]],
               mz_utm[["geometry"]].assign(mzi=range(len(mz))), predicate="within", how="left").drop_duplicates("eid")
ed["mzi"] = ed.eid.map(j2.set_index("eid").mzi)
ed_s = simplificar(ed, 0.3)
edificaciones = []
for r, g in zip(ed.itertuples(), ed_s.geometry):
    edificaciones.append([anillos(g), None if pd.isna(r.pid) else int(r.pid), round(float(r.viv or 0), 2),
                          round(float(r.sup_cons_e or 0)), None if pd.isna(r.pisos_e) else int(r.pisos_e),
                          None if pd.isna(r.mzi) else int(r.mzi), round(float(r.area_m2)), round(float(r.cuota_suelo))])

pr["con_edif"] = pr.pid.isin(dom.pid)
pr["area_m2"] = pr_u.area  # el pol_area_m2 del catastro viene nulo en algunos lotes
pr["sup_cons"] = pr.sup_cons.fillna(0)
pr_s = simplificar(pr, 0.3)
predios = [[anillos(g), int(r.n_roles), int(r.n_hab), round(float(r.area_m2 or 0)), round(float(r.sup_cons or 0)),
            (r.destinos or "").split("|")[0][:24]] for r, g in zip(pr.itertuples(), pr_s.geometry)]

# --- anteproyecto (eje oficial, estaciones por progresiva, torres, huellas)
eje = gpd.read_file(REF / "eje_oficial_Tel-Thno.geojson")
est = gpd.read_file(REF / "estaciones_anteproyecto_P178.geojson")
tor = pd.read_csv(REF / "torres_anteproyecto_P178.csv")
tor_g = gpd.GeoDataFrame(tor, geometry=gpd.points_from_xy(tor.x_32718, tor.y_32718), crs=UTM).to_crs(4326)
eje_u = eje.to_crs(UTM).set_index("tramo")
ante = {"lineas": []}
for tr in ["T1", "T2"]:
    e = est[est.tramo == tr].sort_values("progresiva_m")
    ante["lineas"].append({"nombre": f"Anteproyecto {tr}",
                           "estaciones": [[round(p.x, ND), round(p.y, ND), n] for p, n in zip(e.geometry, e.estacion)]})
torres = []
for r, p in zip(tor.itertuples(), tor_g.geometry):
    torres.append([r.tramo, r.torre, round(p.x, ND), round(p.y, ND), r.progresiva_m, r.cota_terreno_m, r.cota_cable_m])
ante["torres"] = torres

valores = json.loads((C / "valores_suelo.json").read_text(encoding="utf-8"))
paq = {
    "meta": {"generado": pd.Timestamp.now().isoformat(timespec="seconds"),
             "fuentes": "Censo 2024 (INE) · SII catastro Talcahuano · SECTRA ortofoto 2023-24 · OSM · Copernicus GLO-30 · "
                        "SII F2890 · SECTRA P178/P246 · MTT Tel-Thno.kmz"},
    "area": [anillos(g) for g in area.geometry][0],
    "manzanas": manzanas, "manzanas_geo": manzanas_geo,
    "grafo": grafo, "edificaciones": edificaciones, "predios": predios,
    "dem": {"z": np.round(z, 1).tolist(), "xll": xll, "yll": yll, "cell": cell},
    "anteproyecto": ante, "valores": valores,
}
out = C / "paquete_herramienta.json"
clase = lambda nh: 0 if nh <= 0 else (1 if nh <= 2 else 3)
pub = dict(paq)
pub["meta"] = dict(paq["meta"], publico=True)
pub["predios"] = [[p[0], None, clase(p[2]), round(p[3], -1), None, ""] for p in predios]
pub["edificaciones"] = [[e[0], e[1], round(e[2], 1), round(e[3], -1), None, e[5], e[6], round(e[7], -1)] for e in edificaciones]
(C / "paquete_publico.json").write_text(json.dumps(pub, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
out.write_text(json.dumps(paq, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"paquete: {out.stat().st_size/1e6:.1f} MB · manzanas {len(manzanas)} · nodos {len(grafo['n'])} · "
      f"aristas {len(grafo['e'])} · edificaciones {len(edificaciones)} · predios {len(predios)} · "
      f"viviendas totales (regla) {ed.viv.sum():,.0f} · roles hab {pr.n_hab.sum():,}")
print("enganche manzana→red: mediana", mz.enganche_m.median(), "m · p95", mz.enganche_m.quantile(.95), "m")
