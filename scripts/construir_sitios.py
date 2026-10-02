"""Arma los dos sitios de la herramienta multi-proyecto a partir de scripts/app.html y proyectos/<id>/.

  salidas/sitio/  → versión interna (datos_completo.json: atributos SII por lote) · sólo local / repo privado
  publico/        → versión pública (datos_publico.json) · repo público + GitHub Pages
Correr: python -X utf8 scripts/construir_sitios.py   (después de motor_proyecto.py)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
import shutil
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
V = RAIZ / "scripts/vendor"
app = (RAIZ / "scripts/app.html").read_text(encoding="utf-8")
version = datetime.now().strftime("%Y%m%d%H%M")
for marca, archivo in [("/*__LEAFLET_CSS__*/", "leaflet.css"), ("/*__LEAFLET_JS__*/", "leaflet.js"), ("/*__TURF_JS__*/", "turf.min.js")]:
    assert marca in app, marca
    app = app.replace(marca, (V / archivo).read_text(encoding="utf-8").replace("</script", r"<\/script"))
app = app.replace("/*__VERSION__*/", version)
indice = json.loads((RAIZ / "proyectos/index.json").read_text(encoding="utf-8"))
for destino, datos in [(RAIZ / "salidas/sitio", "datos_completo.json"), (RAIZ / "publico", "datos_publico.json")]:
    (destino / "proyectos").mkdir(parents=True, exist_ok=True)
    (destino / "index.html").write_text(app, encoding="utf-8")
    (destino / "proyectos/index.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in indice["proyectos"]:
        f = RAIZ / "proyectos" / p["id"] / datos
        if f.exists():
            shutil.copyfile(f, destino / "proyectos" / f"{p['id']}.json")
    (destino / "version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    print(f"{destino.relative_to(RAIZ)}: index.html {len(app)/1e6:.2f} MB · {len(indice['proyectos'])} proyecto(s) · v{version}")
