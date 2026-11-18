"""A conexão criada numa thread funciona em outra? (somente leitura)"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from titan_match.resolve_bridge import ResolveBridge  # noqa: E402

holder = {}


def worker():
    br = ResolveBridge()
    holder["br"] = br
    holder["item"] = br.target_item()
    holder["n_worker"] = len(br.inspect(holder["item"]))


t = threading.Thread(target=worker)
t.start()
t.join()
print("na thread de fundo: nós =", holder["n_worker"])
try:
    br, item = holder["br"], holder["item"]
    print("na thread principal: nome =", item.GetName())
    print("na thread principal: versão =", item.GetCurrentVersion())
    g = item.GetNodeGraph()
    print("na thread principal: grafo =", g, "| nós =", g.GetNumNodes() if g else None)
    print("na thread principal: projeto =", br.project.GetName())
except Exception as e:
    print("ERRO na thread principal:", type(e).__name__, e)
