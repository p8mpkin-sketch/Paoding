"""拼成单文件：python3 build.py（在本目录运行）。"""
from pathlib import Path
H = Path(__file__).resolve().parent
css = (H / "style.css").read_text(encoding="utf-8")
js = (H / "app.js").read_text(encoding="utf-8")
data = (H / "data.json").read_text(encoding="utf-8").replace("</", "<\\/")
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>方案分析原型</title>
<style>{css}</style></head><body><div id="root"></div>
<script>window.DATA={data};</script><script>{js}</script></body></html>"""
(H / "index.html").write_text(html, encoding="utf-8")
print("ok", len(html))
