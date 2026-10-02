"""Incrusta los paquetes de datos en la plantilla y escribe las dos versiones de la herramienta.

Correr: python -X utf8 scripts/04_construir_html.py  (después de 03_empaquetar_datos.py)
🔴 salidas/herramienta_teleferico_talcahuano.html: versión completa (atributos SII por lote) → sólo local / repo privado.
   publico/index.html: versión saneada (sin atributos por lote ni por edificio) → repo público + GitHub Pages.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
plantilla = (RAIZ / "scripts/plantilla_herramienta.html").read_text(encoding="utf-8")
assert "/*__DATOS__*/null" in plantilla
for paquete, out in [("paquete_herramienta.json", RAIZ / "salidas/herramienta_teleferico_talcahuano.html"),
                     ("paquete_publico.json", RAIZ / "publico/index.html")]:
    datos = (RAIZ / "datos/cache" / paquete).read_text(encoding="utf-8")
    out.parent.mkdir(exist_ok=True)
    out.write_text(plantilla.replace("/*__DATOS__*/null", datos.replace("</", "<\\/")), encoding="utf-8")
    print(f"{out.relative_to(RAIZ)}: {out.stat().st_size/1e6:.1f} MB")
