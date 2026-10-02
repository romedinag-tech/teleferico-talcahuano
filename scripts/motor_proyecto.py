"""Motor de proyectos: arma los datos de la herramienta para cualquier área de estudio de Chile.

Un proyecto vive en proyectos/<id>/config.json:
  {"id": "talcahuano", "nombre": "...", "area": <GeoJSON Polygon 4326>,
   "referencial": {"lineas": [{"nombre": "...", "estaciones": [[lon, lat, "nombre"], ...]}]},
   "centro": [lon, lat], "margen_m": 500, "extras": {"torres_csv": "ruta opcional"}}

Uso:
  python -X utf8 scripts/motor_proyecto.py talcahuano        # (re)construye un proyecto
  python -X utf8 scripts/motor_proyecto.py --solicitudes     # procesa solicitudes/*.json bajadas desde la web
  python -X utf8 scripts/motor_proyecto.py --todos           # reconstruye todos

Fuentes en SOLO LECTURA desde Análisis RMG y D:\\Biblioteca_MTT. Escribe sólo en proyectos/<id>/.
Salidas por proyecto: cache/*.parquet, datos_completo.json (🔴 atributos SII por lote: privado),
datos_publico.json (sin atributos por lote ni por edificio). Índice: proyectos/index.json.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import ctypes
import json
import os
import shutil
import subprocess
import unicodedata
import urllib.request
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
import pyogrio
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Polygon, shape

RAIZ = Path(__file__).resolve().parents[1]
PROY = RAIZ / "proyectos"
RMG = Path(r"C:\Users\Rodrigo\Análisis RMG")
US = RMG / "GIS Gran Concepción" / "Analisis uso de suelo Gran Concepción"
COMUNAS = RMG / "Hub Multidato/datos_oro/uso_suelo/comuna.geojson"
CENSO = US / "Censo/2024/Cartografia_censo2024_Pais/Cartografia_censo2024_Pais_Manzanas.parquet"
SII_DIR = US / "comunas_parquet"
TRANS = US / "Transparencia/transacciones.parquet"
TRANS_PT = US / "_producto_data/puntos_transacciones.parquet"
SECTRA = Path(r"D:\Biblioteca_MTT\Programa de Vialidad y Transporte Urbano"
              r"\Actualización del Plan de Transporte del Gran Concepción, Etapa II, Ortofotografía")
SECTRA_BBOX_32718 = (661245, 5890251, 686833, 5956378)   # extensión medida de EDIFICACION_MENOR
PBF = RMG / "Red Vial de Chile/data/raw/osm/chile-latest.osm.pbf"
DEM_DIR = RAIZ / "datos/crudo/dem"
GDAL = Path(r"C:\Program Files\QGIS 3.44.11\bin")
ND = 6
EDADES = ["n_edad_0_5", "n_edad_6_13", "n_edad_14_17", "n_edad_18_24", "n_edad_25_44", "n_edad_45_59", "n_edad_60_mas"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.lower().replace("_", " ").replace("-", " ").strip()


def ruta_corta(p):
    """libosmium no abre rutas con tildes en Windows: nombre corto 8.3."""
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024)
    return buf.value


def utm_de(lon):
    return 32718 if lon < -72 else 32719


# ------------------------------------------------------------------ capas
def comunas_del_area(marco_4326):
    c = gpd.read_file(COMUNAS)
    return c[c.intersects(marco_4326)][["cut", "comuna"]].reset_index(drop=True)


def manzanas(cuts, marco_4326):
    con = duckdb.connect(); con.execute("LOAD spatial;")
    lista = ",".join(str(int(c)) for c in cuts)
    df = con.execute(f"""
        select lpad(cast(cast(MANZENT as bigint) as varchar),14,'0') manzent, CUT cut,
               n_per, n_hog, n_vp, n_vp_ocupada, n_edad_0_5, n_edad_6_13, n_edad_14_17, n_edad_18_24,
               n_edad_25_44, n_edad_45_59, n_edad_60_mas, ST_AsWKB(SHAPE) w
        from '{CENSO.as_posix()}' where CUT in ({lista})""").df()
    g = gpd.GeoDataFrame(df.drop(columns="w"), geometry=gpd.GeoSeries.from_wkb(df.w.apply(bytes)), crs=4674)
    g = g.set_crs(4326, allow_override=True)          # SIRGAS ≈ WGS84: identidad
    g["geometry"] = g.geometry.make_valid()
    g = g[g.intersects(marco_4326)].copy()
    for col in ["n_per", "n_hog", "n_vp", "n_vp_ocupada"] + EDADES:
        g[col] = pd.to_numeric(g[col], errors="coerce")   # '*' secreto estadístico → NULL
    return g


def archivos_sii(comunas):
    """Catastro SII por nombre normalizado (código SII ≠ INE). Devuelve [(cut, archivo, cod_sii)] y faltantes."""
    idx = {}
    for f in SII_DIR.glob("*.parquet"):
        nombre, _, cod = f.stem.rpartition("_")
        idx.setdefault(norm(nombre), []).append((f, cod))
    out, faltan = [], []
    for r in comunas.itertuples():
        hits = idx.get(norm(r.comuna), [])
        if not hits:
            faltan.append(r.comuna)
        for f, cod in hits:
            out.append((r.cut, f, cod))
    return out, faltan


def predios(archivos, marco_4326):
    con = duckdb.connect(); con.execute("LOAD spatial;")
    partes = []
    for _, f, _ in archivos:
        df = con.execute(f"""
            select ST_AsWKB(geometry) w, destinoDescripcion destino,
                   try_cast(sup_construida_total as double) sup_cons, try_cast(pisos_max as integer) pisos
            from '{f.as_posix()}' where geometry is not null""").df()
        partes.append(df)
    if not partes:
        return gpd.GeoDataFrame(columns=["n_roles", "n_hab", "destinos", "sup_cons", "pisos", "geometry"], crs=4326)
    df = pd.concat(partes, ignore_index=True)
    df["hab"] = df.destino.fillna("").str.upper().str.startswith("HABITACIONAL")
    df["w"] = df.w.apply(bytes)
    agg = df.groupby("w").agg(n_roles=("destino", "size"), n_hab=("hab", "sum"),
                              destinos=("destino", lambda s: "|".join(sorted(set(s.dropna())))),
                              sup_cons=("sup_cons", "sum"), pisos=("pisos", "max")).reset_index()
    g = gpd.GeoDataFrame(agg.drop(columns="w"), geometry=gpd.GeoSeries.from_wkb(agg.w), crs=4326)
    return g[g.intersects(marco_4326)].copy()


class Edificios(osmium.SimpleHandler):
    def __init__(self, bbox):
        super().__init__(); self.bbox = bbox; self.pol = []

    def way(self, w):
        if "building" not in w.tags or not w.is_closed():
            return
        try:
            pts = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        x0, y0, x1, y1 = self.bbox
        if len(pts) >= 4 and any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
            self.pol.append(Polygon(pts))


def edificaciones(marco_4326, utm):
    m32718 = gpd.GeoSeries([marco_4326], crs=4326).to_crs(32718).iloc[0]
    x0, y0, x1, y1 = m32718.bounds
    bx = SECTRA_BBOX_32718
    if x0 >= bx[0] and y0 >= bx[1] and x1 <= bx[2] and y1 <= bx[3]:
        capas = []
        for nombre in ["EDIFICACION_MAYOR", "EDIFICACION_MENOR"]:
            f = next(SECTRA.glob(f"*CONSTRUCCION/{nombre}.shp"))
            capas.append(gpd.read_file(f, bbox=(x0, y0, x1, y1), engine="pyogrio"))
        e = pd.concat(capas, ignore_index=True)
        e = e[e.intersects(m32718)][["geometry"]]
        fuente = "SECTRA ortofoto Gran Concepción 2023-24"
        e = e.to_crs(4326)
    else:
        h = Edificios(marco_4326.bounds)
        h.apply_file(osmium.io.File(ruta_corta(PBF), "pbf"), locations=True, idx="flex_mem")
        e = gpd.GeoDataFrame(geometry=h.pol, crs=4326)
        e = e[e.intersects(marco_4326)]
        fuente = "OpenStreetMap (building=*), cobertura variable"
    e = e.copy()
    e["area_m2"] = e.to_crs(utm).area
    return e.reset_index(drop=True), fuente


class Caminable(osmium.SimpleHandler):
    EXCLUIR = {"motorway", "motorway_link", "construction", "proposed", "raceway", "bus_guideway"}

    def __init__(self, bbox):
        super().__init__(); self.bbox = bbox; self.filas = []

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
            self.filas.append((hw, ids[i], ids[i + 1], LineString([pts[i], pts[i + 1]])))


def red_peatonal(marco_4326, utm):
    h = Caminable(marco_4326.bounds)
    h.apply_file(osmium.io.File(ruta_corta(PBF), "pbf"), locations=True, idx="flex_mem")
    g = gpd.GeoDataFrame(pd.DataFrame(h.filas, columns=["highway", "n_a", "n_b", "geometry"]), crs=4326)
    g = g[g.intersects(marco_4326)].copy()
    g["largo_m"] = g.to_crs(utm).length
    return g


def dem(marco_4326, destino):
    """Copernicus GLO-30: baja los tiles que falten (fuente aprobada por Rodrigo, 2026-10-02) y recorta."""
    x0, y0, x1, y1 = marco_4326.bounds
    DEM_DIR.mkdir(parents=True, exist_ok=True)
    tiles = []
    for la in range(int(np.floor(y0)), int(np.floor(y1)) + 1):
        for lo in range(int(np.floor(x0)), int(np.floor(x1)) + 1):
            n = f"Copernicus_DSM_COG_10_{'S' if la < 0 else 'N'}{abs(la):02d}_00_{'W' if lo < 0 else 'E'}{abs(lo):03d}_00_DEM"
            f = DEM_DIR / f"{n}.tif"
            if not f.exists():
                urllib.request.urlretrieve(f"https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif", f)
            tiles.append(f)
    env = dict(os.environ, PATH=str(GDAL) + os.pathsep + os.environ["PATH"])
    src = tiles[0]
    if len(tiles) > 1:
        src = destino / "_dem.vrt"
        subprocess.run([str(GDAL / "gdalbuildvrt.exe"), str(src), *map(str, tiles)], check=True, env=env,
                       capture_output=True)
    asc = destino / "_dem.asc"
    r = subprocess.run([str(GDAL / "gdal_translate.exe"), "-of", "AAIGrid", "-projwin", str(x0), str(y1), str(x1),
                        str(y0), str(src), str(asc)], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr)
    hdr, saltar = {}, 0
    with open(asc) as fh:
        for linea in fh:
            k, *v = linea.split()
            if not k[0].isalpha():
                break
            hdr[k.lower()] = float(v[0]); saltar += 1
    z = np.loadtxt(asc, skiprows=saltar, dtype=np.float32)
    for extra in destino.glob("_dem.*"):
        extra.unlink()
    return {"z": z, "xll": hdr["xllcorner"], "yll": hdr["yllcorner"], "cell": hdr["cellsize"]}


def valores_suelo(area_4326, cods_sii):
    """🔴 Escrituras F2890 en el área: sólo cuantiles por tipología, nunca filas."""
    con = duckdb.connect(); con.execute("LOAD spatial;")
    lista = ",".join(f"'{c}'" for c in cods_sii) or "''"
    llaves = con.execute(f"""
        select distinct comuna, manzana, predio from '{TRANS_PT.as_posix()}'
        where comuna in ({lista}) and lat is not null
          and ST_Within(ST_Point(lon, lat), ST_GeomFromText('{area_4326.wkt}'))""").df()
    con.register("llaves", llaves)
    t = con.execute(f"""
        select t.tipo_propiedad, t.monto_uf, t.uf_m2_construido, t.uf_m2_terreno
        from '{TRANS.as_posix()}' t join llaves l on t.comuna=l.comuna and t.manzana=l.manzana and t.predio=l.predio
        where t.anio between 2015 and 2025""").df()
    out = {"fuente": "SII F2890 (Transparencia), escrituras 2015-2025 en el área de estudio", "por_tipologia": {}}
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
    return out


# ------------------------------------------------------------------ empaquetado
def anillos(geom):
    out = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type == "Polygon" and not g.is_empty:
            out.append([[round(c[0], ND), round(c[1], ND)] for c in g.exterior.coords])
    return out


def simplificar(gdf, tol, utm):
    g = gdf.to_crs(utm).copy(); g["geometry"] = g.simplify(tol, preserve_topology=True)
    return g.to_crs(4326)


def empaquetar(cfg, area, mz, pr, ed, fuente_ed, red, dm, valores, utm, faltan):
    area_u = area.to_crs(utm).union_all()
    mz_u = mz.to_crs(utm)
    rp = mz_u.representative_point()
    cen = rp.to_crs(4326)
    mz = mz.assign(lon=cen.x.round(ND), lat=cen.y.round(ND), en_area=rp.within(area_u).values,
                   per_viv=(mz.n_per / mz.n_vp_ocupada).where(mz.n_vp_ocupada > 0))
    # grafo peatonal con cota DEM
    nodos = {}
    for r in red.itertuples():
        (x0, y0), (x1, y1) = r.geometry.coords[0], r.geometry.coords[-1]
        nodos.setdefault(r.n_a, (x0, y0)); nodos.setdefault(r.n_b, (x1, y1))
    ids = list(nodos); idx = {n: i for i, n in enumerate(ids)}
    xy = np.array([nodos[n] for n in ids])
    z, xll, yll, cell = dm["z"], dm["xll"], dm["yll"], dm["cell"]
    nf, nc = z.shape

    def cota(lon, lat):
        c = (lon - xll) / cell - .5; f = (yll + nf * cell - lat) / cell - .5
        c0 = np.clip(np.floor(c).astype(int), 0, nc - 2); f0 = np.clip(np.floor(f).astype(int), 0, nf - 2)
        dc, df = np.clip(c - c0, 0, 1), np.clip(f - f0, 0, 1)
        return (z[f0, c0] * (1 - dc) * (1 - df) + z[f0, c0 + 1] * dc * (1 - df)
                + z[f0 + 1, c0] * (1 - dc) * df + z[f0 + 1, c0 + 1] * dc * df)

    zn = cota(xy[:, 0], xy[:, 1])
    aristas = {}
    for r in red.itertuples():
        a, b = idx[r.n_a], idx[r.n_b]
        if a != b:
            k = (min(a, b), max(a, b)); aristas[k] = min(aristas.get(k, 1e9), r.largo_m)
    grafo = {"n": [[round(x, ND), round(y, ND), round(float(h), 1)] for (x, y), h in zip(xy, zn)],
             "e": [[a, b, round(L, 1)] for (a, b), L in aristas.items()]}
    lat0 = float(np.mean(xy[:, 1])); kx, ky = 111320 * np.cos(np.radians(lat0)), 110540
    d, j = cKDTree(np.c_[xy[:, 0] * kx, xy[:, 1] * ky]).query(np.c_[mz.lon * kx, mz.lat * ky])
    mz = mz.assign(nodo=j, enganche_m=d.round(1))
    nn = lambda v, f=int: None if pd.isna(v) else f(v)
    manzanas = [[r.lon, r.lat, nn(r.n_per), nn(r.n_hog), nn(r.n_vp), nn(r.per_viv, lambda x: round(float(x), 2)),
                 int(r.nodo), float(r.enganche_m), int(r.en_area),
                 [nn(getattr(r, c)) for c in EDADES]] for r in mz.itertuples()]   # [9]: tramos de edad (censo 2024)
    manzanas_geo = [anillos(g) for g in simplificar(mz[["geometry"]], 1.0, utm).geometry]

    # viviendas por edificio (regla volumétrica, contrastada contra la DGC: 61 vs 64)
    pr = pr.reset_index(drop=True); ed = ed.reset_index(drop=True)
    pr["pid"], ed["eid"] = pr.index, ed.index
    pr_u, ed_u = pr.to_crs(utm), ed.to_crs(utm)
    pr["area_m2"] = pr_u.area; pr["sup_cons"] = pr.sup_cons.fillna(0)
    x = gpd.overlay(ed_u[["eid", "geometry"]], pr_u[["pid", "geometry"]], how="intersection", keep_geom_type=True)
    x["a"] = x.area
    dom = x.sort_values("a").drop_duplicates("eid", keep="last")[["eid", "pid"]]
    dom = dom.merge(pr[["pid", "n_hab", "sup_cons", "pisos"]], on="pid").merge(ed[["eid", "area_m2"]], on="eid")
    m2_viv = (dom.sup_cons / dom.n_hab).where((dom.sup_cons > 0) & (dom.n_hab > 0))
    vol = dom.area_m2 * dom.pisos.fillna(1) / m2_viv
    mayor = dom.sort_values("area_m2").drop_duplicates("pid", keep="last").eid
    chico = dom.n_hab.where(dom.eid.isin(mayor), 0)
    dom["viv"] = vol.where(dom.n_hab > 2, chico).fillna(chico).fillna(0)
    dom["sup_cons_e"] = np.where(dom.n_hab > 2, dom.area_m2 * dom.pisos.fillna(1),
                                 np.where(dom.eid.isin(mayor), dom.sup_cons, 0))
    dom["cuota_suelo"] = np.where(dom.n_hab > 2, dom.pid.map(pr.area_m2) * (dom.viv / dom.n_hab).clip(upper=1), 0)
    ed = ed.merge(dom[["eid", "pid", "viv", "sup_cons_e", "pisos", "cuota_suelo"]], on="eid", how="left")
    ed[["viv", "sup_cons_e", "cuota_suelo"]] = ed[["viv", "sup_cons_e", "cuota_suelo"]].fillna(0)
    j2 = gpd.sjoin(ed_u.assign(geometry=ed_u.representative_point())[["eid", "geometry"]],
                   mz_u[["geometry"]].assign(mzi=range(len(mz))), predicate="within", how="left").drop_duplicates("eid")
    ed["mzi"] = ed.eid.map(j2.set_index("eid").mzi)
    eds = simplificar(ed[["geometry"]], .3, utm)
    edificaciones = [[anillos(g), nn(r.pid), round(float(r.viv), 2), round(float(r.sup_cons_e)), nn(r.pisos), nn(r.mzi),
                      round(float(r.area_m2)), round(float(r.cuota_suelo))] for r, g in zip(ed.itertuples(), eds.geometry)]
    prs = simplificar(pr[["geometry"]], .3, utm)
    predios = [[anillos(g), int(r.n_roles), int(r.n_hab), round(float(r.area_m2)), round(float(r.sup_cons)),
                (r.destinos or "").split("|")[0][:24]] for r, g in zip(pr.itertuples(), prs.geometry)]

    ref = {"lineas": cfg["referencial"]["lineas"], "torres": []}
    tc = cfg.get("extras", {}).get("torres_csv")
    if tc:
        t = pd.read_csv(RAIZ / tc)
        tg = gpd.GeoDataFrame(t, geometry=gpd.points_from_xy(t.x_32718, t.y_32718), crs=32718).to_crs(4326)
        ref["torres"] = [[r.tramo, r.torre, round(p.x, ND), round(p.y, ND), r.progresiva_m, r.cota_terreno_m,
                          r.cota_cable_m] for r, p in zip(t.itertuples(), tg.geometry)]
    meta = {"id": cfg["id"], "nombre": cfg["nombre"], "generado": pd.Timestamp.now().isoformat(timespec="seconds"),
            "centro": cfg.get("centro"), "fuente_edificaciones": fuente_ed, "comunas_sin_catastro_sii": faltan,
            "fuentes": f"Censo 2024 (INE) · catastro SII · {fuente_ed} · OpenStreetMap · Copernicus GLO-30 · "
                       f"SII F2890 (agregado) · " + cfg.get("fuentes_extra", "")}
    completo = {"meta": meta, "area": anillos(area.union_all())[0], "manzanas": manzanas, "manzanas_geo": manzanas_geo,
                "grafo": grafo, "edificaciones": edificaciones, "predios": predios,
                "dem": {"z": np.round(z, 1).tolist(), "xll": xll, "yll": yll, "cell": cell},
                "anteproyecto": ref, "valores": valores}
    clase = lambda nh: 0 if nh <= 0 else (1 if nh <= 2 else 3)
    publico = dict(completo, meta=dict(meta, publico=True),
                   predios=[[p[0], None, clase(p[2]), round(p[3], -1), None, ""] for p in predios],
                   edificaciones=[[e[0], e[1], round(e[2], 1), round(e[3], -1), None, e[5], e[6], round(e[7], -1)]
                                  for e in edificaciones])
    return completo, publico, {"viviendas_regla": float(ed.viv.sum()), "roles_hab": int(pr.n_hab.sum()),
                               "personas": float(mz.n_per.sum()), "manzanas": len(mz), "edificaciones": len(ed),
                               "lotes": len(pr), "nodos": len(ids)}


# ------------------------------------------------------------------ orquestación
def construir(pid):
    d = PROY / pid
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    area = gpd.GeoDataFrame(geometry=[shape(cfg["area"])], crs=4326)
    lon_c = area.union_all().centroid.x
    utm = utm_de(lon_c)
    marco_u = area.to_crs(utm).buffer(cfg.get("margen_m", 500)).union_all()
    marco = gpd.GeoSeries([marco_u], crs=utm).to_crs(4326).iloc[0]
    print(f"[{pid}] UTM {utm} · comunas:", end=" ")
    com = comunas_del_area(marco); print(", ".join(com.comuna))
    mz = manzanas(com.cut, marco); print(f"  manzanas {len(mz)} · personas {mz.n_per.sum():,.0f}")
    arch, faltan = archivos_sii(com)
    if faltan:
        print(f"  ⚠ sin catastro SII por nombre: {faltan}")
    pr = predios(arch, marco); print(f"  lotes SII {len(pr)} · roles hab {int(pr.n_hab.sum()):,}")
    ed, fuente_ed = edificaciones(marco, utm); print(f"  edificaciones {len(ed)} ({fuente_ed})")
    red = red_peatonal(marco, utm); print(f"  red peatonal {len(red)} aristas · {red.largo_m.sum()/1000:.1f} km")
    dm = dem(marco, d); print(f"  DEM {dm['z'].shape}")
    val = valores_suelo(area.union_all(), sorted({c for _, _, c in arch}))
    print("  escrituras:", {k: v["n"] for k, v in val["por_tipologia"].items()})
    completo, publico, ctrl = empaquetar(cfg, area, mz, pr, ed, fuente_ed, red, dm, val, utm, faltan)
    for nombre, obj in [("datos_completo.json", completo), ("datos_publico.json", publico)]:
        tmp = d / (nombre + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, d / nombre)
    (d / "control.json").write_text(json.dumps(ctrl, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  control:", ctrl)
    actualizar_indice()


def actualizar_indice():
    items = []
    for d in sorted(p for p in PROY.iterdir() if (p / "config.json").exists()):
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        listo = (d / "datos_publico.json").exists()
        b = shape(cfg["area"]).bounds
        items.append({"id": cfg["id"], "nombre": cfg["nombre"], "listo": listo,
                      "bbox": [round(v, 5) for v in b], "centro": cfg.get("centro")})
    (PROY / "index.json").write_text(json.dumps({"proyectos": items}, ensure_ascii=False, indent=1), encoding="utf-8")


def procesar_solicitudes():
    sol = RAIZ / "solicitudes"
    for f in sorted(sol.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        pid = s["id"]
        d = PROY / pid
        if (d / "config.json").exists():
            print(f"[{pid}] ya existe: se omite {f.name} (renombrar el id para crear otro)"); continue
        d.mkdir(parents=True)
        cfg = {"id": pid, "nombre": s["nombre"], "area": s["area"], "referencial": s["referencial"],
               "centro": s.get("centro"), "margen_m": 500, "origen": f"solicitud {f.name}"}
        (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        construir(pid)
        procesadas = sol / "procesadas"; procesadas.mkdir(exist_ok=True)
        shutil.move(str(f), procesadas / f.name)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--todos"
    if arg == "--solicitudes":
        procesar_solicitudes()
    elif arg == "--todos":
        for d in sorted(PROY.iterdir()):
            if (d / "config.json").exists():
                construir(d.name)
    else:
        construir(arg)
