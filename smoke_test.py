import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as s

tmp = tempfile.mkdtemp()
txt = os.path.join(tmp, "libro.txt")
open(txt, "w", encoding="utf-8").write("Ficciones\n\nHola mundo.\n")

print(s.calibre_info())
r = s.convert_book(txt, "epub", overwrite=True)
print("convert:", r)
print("set:", s.set_metadata(r["output"], title="Ficciones", authors=["Jorge Luis Borges"], tags=["cuentos"]))
print("fetch:", json.dumps(s.fetch_metadata(title="Ficciones", authors=["Jorge Luis Borges"]), ensure_ascii=False)[:500])
print("autofill:", s.auto_fill_metadata(r["output"]).get("fields_written"))
print("batch dry:", s.batch_convert(tmp, "mobi")["count"])
print("tools:", [t.name for t in asyncio.run(s.mcp.list_tools())])
