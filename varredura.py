"""Varredura de hora em hora do D.News: coleta as notícias, dispara os alertas quentes e atualiza as trilhas.

Uso: python -I painel_rotinas\\varredura.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alertas  # noqa: E402
import coletor  # noqa: E402
import trilhas  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        d = coletor.coletar(verbose=False)
        print(f"coleta: {len(d['itens'])} notícias hoje · fontes {d['fontes_ok']}/{d['fontes_total']}")
        for e in d.get("erros", []):
            print(f"  fonte com erro: {e['fonte']} → {e['erro']}")
    except Exception as e:  # noqa: BLE001
        print(f"ALERTA coleta falhou: {type(e).__name__}: {e}")
    print("alertas:", alertas.rodar())
    try:
        print("trilhas:", trilhas.atualizar_todas(verbose=False), "matérias novas")
    except Exception as e:  # noqa: BLE001
        print(f"ALERTA trilhas falharam: {type(e).__name__}: {e}")
