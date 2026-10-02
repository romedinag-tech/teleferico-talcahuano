"""Recorta y destila las capas base de la herramienta al área de estudio (+ margen).

Lee SOLO LECTURA desde otros proyectos de Análisis RMG y desde D:\\Biblioteca_MTT; escribe
únicamente en datos/cache/ de este proyecto. Correr con: python -X utf8 scripts/01_preparar_capas.py

Salidas (EPSG:4326 salvo que se indique):
  capa_manzanas.parquet      manzanas censo 2024 (población, hogares, viviendas)
  capa_predios.parquet       polígonos SII agregados por lote (n roles, n habitacionales, sup.)
  capa_edificaciones.parquet huellas SECTRA 2023-24 con altura
  capa_red_peatonal.parquet  aristas OSM caminables (incluye pasajes, escaleras, senderos)
  dem_area.npz               grilla Copernicus recortada + transformación
  valores_suelo.json         🔴 PRIVADO: UF/m² de escrituras F2890 en el área, por tipología
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
import subprocess
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
import pyogrio
from shapely.geometry import LineString

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "datos" / "cache"
RMG = Path(r"C:\Users\Rodrigo\Análisis RMG")
US = RMG / "GIS Gran Concepción" / "Analisis uso de suelo Gran Concepción"
CENSO = US / "Censo/2024/Cartografia_censo2024_Pais/Cartografia_censo2024_Pais_Manzanas.parquet"
PREDIOS = US / "comunas_parquet/Talcahuano_8206.parquet"
TRANS = US / "Transparencia/transacciones.parquet"
TRANS_PT = US / "_producto_data/puntos_transacciones.parquet"
SECTRA = Path(r"D:\Biblioteca_MTT\Programa de Vialidad y Transporte Urbano"
              r"\Actualización del Plan de Transporte del Gran Concepción, Etapa II, Ortofotografía")
PBF = RMG / "Red Vial de Chile/data/raw/osm/chile-latest.osm.pbf"
DEM = RAIZ / "datos/crudo/dem/Copernicus_DSM_COG_10_S37_00_W074_00_DEM.tif"
GDAL_BIN = Path(r"C:\Program Files\QGIS 3.44.11\bin")

MARGEN_M = 500          # margen alrededor del área para estaciones de borde y caminatas
UTM = 32718             # huso 18S: el del estudio P178


def area_y_marco():
    a = gpd.read_file(CACHE / "area_estudio.geojson").to_crs(UTM)
    marco = a.buffer(MARGEN_M).union_all()
    marco_4326 = gpd.GeoSeries([marco], crs=UTM).to_crs(4326).iloc[0]
    return marco, marco_4326


def manzanas(marco_4326):
    con = duckdb.connect(); con.execute("LOAD spatial;")
    df = con.execute(f"""
        select lpad(cast(cast(MANZENT as bigint) as varchar),14,'0') manzent,
               n_per, n_hog, n_vp, n_vp_ocupada, n_tipo_viv_casa, n_tipo_viv_depto,
               ST_AsWKB(SHAPE) w
        from '{CENSO.as_posix()}' where CUT = 8110""").df()
    g = gpd.GeoDataFrame(df.drop(columns="w"), geometry=gpd.GeoSeries.from_wkb(df.w.apply(bytes)),
                         crs=4674)
    g = g.set_crs(4326, allow_override=True)          # SIRGAS 4674 ≈ WGS84: identidad
    g["geometry"] = g.geometry.make_valid()
    g = g[g.intersects(marco_4326)].copy()
    for c in ["n_per", "n_hog", "n_vp", "n_vp_ocupada", "n_tipo_viv_casa", "n_tipo_viv_depto"]:
        # '*' = secreto estadístico: queda NULL, no cero
        g[c] = pd.to_numeric(g[c], errors="coerce")
    return g


def predios(marco_4326):
    con = duckdb.connect(); con.execute("LOAD spatial;")
    df = con.execute(f"""
        select ST_AsWKB(geometry) w, destinoDescripcion destino,
               try_cast(sup_construida_total as double) sup_cons,
               try_cast(pisos_max as integer) pisos,
               try_cast("cap__áreas_homogéneas_rav_no_agrícola_2022__valor_m²_de_terreno" as double) vf_m2,
               pol_area_m2, _match_dist_m
        from '{PREDIOS.as_posix()}' where geometry is not null""").df()
    df["hab"] = df.destino.fillna("").str.upper().str.startswith("HABITACIONAL")
    df["w"] = df.w.apply(bytes)
    agg = df.groupby("w").agg(
        n_roles=("destino", "size"), n_hab=("hab", "sum"),
        destinos=("destino", lambda s: "|".join(sorted(set(s.dropna())))),
        sup_cons=("sup_cons", "sum"), pisos=("pisos", "max"), vf_m2_fiscal=("vf_m2", "median"),
        area_m2=("pol_area_m2", "first"), match_dist_m=("_match_dist_m", "max")).reset_index()
    g = gpd.GeoDataFrame(agg.drop(columns="w"), geometry=gpd.GeoSeries.from_wkb(agg.w), crs=4326)
    return g[g.intersects(marco_4326)].copy()


def edificaciones(marco):
    bb = tuple(marco.bounds)
    capas = []
    for nombre in ["EDIFICACION_MAYOR", "EDIFICACION_MENOR"]:
        f = next(SECTRA.glob(f"*CONSTRUCCION/{nombre}.shp"))
        e = gpd.read_file(f, bbox=bb, engine="pyogrio")
        e["fuente"] = nombre
        capas.append(e)
    e = pd.concat(capas, ignore_index=True)
    e = e[e.intersects(marco)][["ALTURA", "fuente", "geometry"]].rename(columns={"ALTURA": "altura_m"})
    e["area_m2"] = e.area
    return e.to_crs(4326)


class Caminable(osmium.SimpleHandler):
    """Aristas OSM por las que se puede caminar dentro de un bbox."""
    EXCLUIR = {"motorway", "motorway_link", "construction", "proposed", "raceway", "bus_guideway"}

    def __init__(self, bbox):
        super().__init__()
        self.bbox = bbox
        self.filas = []

    def way(self, w):
        hw = w.tags.get("highway")
        if hw is None or hw in self.EXCLUIR or w.tags.get("foot") == "no" or w.tags.get("access") == "private":
            return
        try:
            pts = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        x0, y0, x1, y1 = self.bbox
        if not any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
            return
        ids = [n.ref for n in w.nodes]
        for i in range(len(pts) - 1):
            self.filas.append((w.id, hw, ids[i], ids[i + 1], LineString([pts[i], pts[i + 1]])))


def red_peatonal(marco_4326):
    h = Caminable(marco_4326.bounds)
    # libosmium no abre rutas con «Análisis» en Windows: se usa el nombre corto 8.3
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(PBF), buf, 1024)
    h.apply_file(osmium.io.File(buf.value, "pbf"), locations=True, idx="flex_mem")
    g = gpd.GeoDataFrame(pd.DataFrame(h.filas, columns=["way_id", "highway", "n_a", "n_b", "geometry"]),
                         crs=4326)
    g = g[g.intersects(marco_4326)].copy()
    g["largo_m"] = g.to_crs(UTM).length
    return g


def dem(marco_4326):
    x0, y0, x1, y1 = marco_4326.bounds
    asc = CACHE / "_dem_area.asc"
    env = dict(os.environ, PATH=str(GDAL_BIN) + os.pathsep + os.environ["PATH"])
    r = subprocess.run([str(GDAL_BIN / "gdal_translate.exe"), "-of", "AAIGrid", "-projwin",
                        str(x0), str(y1), str(x1), str(y0), str(DEM), str(asc)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    hdr, saltar = {}, 0
    with open(asc) as f:
        for linea in f:                         # el encabezado AAIGrid trae 5 o 6 líneas
            k, *v = linea.split()
            if not k[0].isalpha():
                break
            hdr[k.lower()] = float(v[0]); saltar += 1
    z = np.loadtxt(asc, skiprows=saltar, dtype=np.float32)
    for extra in asc.parent.glob("_dem_area.*"):
        extra.unlink()
    np.savez_compressed(CACHE / "dem_area.npz", z=z, xll=hdr["xllcorner"], yll=hdr["yllcorner"],
                        cell=hdr["cellsize"], nodata=hdr.get("nodata_value", -9999))
    return z.shape, float(np.nanmin(z)), float(np.nanmax(z))


def valores_suelo(area_4326):
    """🔴 Escrituras F2890 dentro del área: estadísticos por tipología, sin filas individuales."""
    con = duckdb.connect(); con.execute("LOAD spatial;")
    llaves = con.execute(f"""
        select distinct manzana, predio from '{TRANS_PT.as_posix()}'
        where comuna='8206' and lat is not null
          and ST_Within(ST_Point(lon, lat), ST_GeomFromText('{area_4326.wkt}'))""").df()
    con.register("llaves", llaves)
    t = con.execute(f"""
        select t.tipo_propiedad, t.anio, t.monto_uf, t.uf_m2_construido, t.uf_m2_terreno,
               t.sup_terreno, t.sup_construida
        from '{TRANS.as_posix()}' t join llaves l using (manzana, predio)
        where t.comuna='8206' and t.anio between 2015 and 2025""").df()
    out = {"fuente": "SII F2890 (Transparencia), escrituras 2015-2025 en el área de estudio B",
           "privacidad": "PRIVADO: sólo uso local", "por_tipologia": {}}
    for tipo, s in t.groupby("tipo_propiedad"):
        if tipo in ("Estacionamiento", "Bodega"):
            continue
        d = {"n": int(len(s))}
        for c in ["monto_uf", "uf_m2_construido", "uf_m2_terreno"]:
            v = s[c].replace([np.inf, -np.inf], np.nan).dropna()
            v = v[v > 0]
            if len(v):
                d[c] = {"n": int(len(v)), "p25": round(float(v.quantile(.25)), 3),
                        "p50": round(float(v.median()), 3), "p75": round(float(v.quantile(.75)), 3)}
        out["por_tipologia"][tipo] = d
    (CACHE / "valores_suelo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    return out


if __name__ == "__main__":
    marco, marco_4326 = area_y_marco()
    area_4326 = gpd.read_file(CACHE / "area_estudio.geojson").union_all()

    m = manzanas(marco_4326); m.to_parquet(CACHE / "capa_manzanas.parquet")
    print(f"manzanas: {len(m)} · personas {m.n_per.sum():,.0f} · hogares {m.n_hog.sum():,.0f} "
          f"· viviendas {m.n_vp.sum():,.0f} · con secreto (n_per nulo) {m.n_per.isna().sum()}")

    p = predios(marco_4326); p.to_parquet(CACHE / "capa_predios.parquet")
    print(f"predios (lotes): {len(p)} · roles {p.n_roles.sum():,} · habitacionales {p.n_hab.sum():,}")

    e = edificaciones(marco); e.to_parquet(CACHE / "capa_edificaciones.parquet")
    print(f"edificaciones: {len(e)} · {e.fuente.value_counts().to_dict()} · altura mediana "
          f"{e.altura_m.median():.1f} m · máx {e.altura_m.max():.0f} m")

    r = red_peatonal(marco_4326); r.to_parquet(CACHE / "capa_red_peatonal.parquet")
    print(f"red peatonal: {len(r)} aristas · {r.largo_m.sum()/1000:.1f} km · "
          f"{r.groupby('highway').largo_m.sum().div(1000).round(1).sort_values(ascending=False).head(10).to_dict()}")

    print("dem:", dem(marco_4326))
    v = valores_suelo(area_4326)
    print("valores_suelo:", {k: (d["n"], d.get("uf_m2_terreno", {}).get("p50"), d.get("uf_m2_construido", {}).get("p50"))
                             for k, d in v["por_tipologia"].items()})
