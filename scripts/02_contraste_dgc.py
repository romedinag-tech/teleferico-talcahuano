"""Contraste obligatorio: ¿la faja de sobrevuelo reproduce lo que contó la DGC sobre el anteproyecto?

DGC (minuta MTT-MOP 07-08-2025): T1, entre Las Antenas y Centinela II, pasa sobre 4 edificaciones
habitacionales de 16 viviendas cada una (64); T2 sobrevuela 74 terrenos con vivienda (62 regulares + 12 tomas).
Eje: datos/referencia/eje_oficial_Tel-Thno.geojson (KMZ oficial MTT, carpeta «1. Anteproyecto Tel Thno IF»);
coincide a ≤ 0,8 m con la recta de las torres del P178 (eje_anteproyecto_P178.geojson).
Correr: python -X utf8 scripts/02_contraste_dgc.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import substring

RAIZ = Path(__file__).resolve().parents[1]
C = RAIZ / "datos" / "cache"
t = pd.read_csv(RAIZ / "datos/referencia/torres_anteproyecto_P178.csv")
ed = gpd.read_parquet(C / "capa_edificaciones.parquet").to_crs(32718).reset_index(drop=True)
pr = gpd.read_parquet(C / "capa_predios.parquet").to_crs(32718).reset_index(drop=True)
ed["eid"], pr["pid"] = ed.index, pr.index

# Viviendas por edificio: los roles habitacionales de cada lote SII se reparten entre los edificios
# del lote según la superficie de intersección. La «altura» SECTRA no sirve para pisos (ver CLAUDE.md).
x = gpd.overlay(ed[["eid", "geometry"]], pr[pr.n_hab > 0][["pid", "n_hab", "geometry"]],
                how="intersection", keep_geom_type=True)
x["a"] = x.area
x["viv"] = x.n_hab * x.a / x.groupby("pid").a.transform("sum")
ed["viv_est"] = ed.eid.map(x.groupby("eid").viv.sum()).fillna(0)

# Regla adoptada (2026-10-02): en lotes multivivienda, viviendas = huella × pisos SII ÷ m² construidos
# por vivienda del lote (el lote que más se superpone con el edificio); en lotes de 1-2 viviendas, sus roles.
x["a_lote_int"] = x.a
dom = x.sort_values("a_lote_int").drop_duplicates("eid", keep="last")[["eid", "pid"]]
dom = dom.merge(pr[["pid", "n_hab", "sup_cons", "pisos"]], on="pid")
dom = dom.merge(ed[["eid", "area_m2"]], on="eid")
m2_viv = (dom.sup_cons / dom.n_hab).where(dom.sup_cons > 0)
vol = dom.area_m2 * dom.pisos.fillna(1) / m2_viv
# en lotes de 1-2 viviendas sólo el edificio más grande del lote lleva sus roles (el resto son anexos)
mayor = dom.sort_values("area_m2").drop_duplicates("pid", keep="last").eid
chico = dom.n_hab.where(dom.eid.isin(mayor), 0)
dom["viv_regla"] = vol.where(dom.n_hab > 2, chico).fillna(chico)
ed["viv_regla"] = ed.eid.map(dom.set_index("eid").viv_regla).fillna(0)

eje = gpd.read_file(RAIZ / "datos/referencia/eje_oficial_Tel-Thno.geojson").to_crs(32718).set_index("tramo")
TRAMOS = {"T1 E3-E4 (DGC: 4 edif., 64 viv.)": ("T1", 1350.29, 2194.69),
          "T2 completo (DGC: 74 terrenos con vivienda)": ("T2", 0, 1e9)}
for nombre, (tr, a, b) in TRAMOS.items():
    L = eje.geometry[tr]
    S = substring(L, a, min(b, L.length))
    print(nombre)
    for w in (10, 15, 20):
        F = S.buffer(w / 2, cap_style=2)
        e = ed[ed.intersects(F)]
        p = pr[pr.intersects(F) & (pr.n_hab > 0)]
        print(f"  faja {w:>2} m: edificaciones {len(e):>3} · con vivienda {int((e.viv_est > .5).sum()):>3} · "
              f"viviendas: reparto {e.viv_est.sum():>4.0f} · regla volumétrica {e.viv_regla.sum():>4.0f} · lotes con vivienda {len(p):>3} · "
              f"roles hab. de esos lotes {int(p.n_hab.sum()):>4}")
