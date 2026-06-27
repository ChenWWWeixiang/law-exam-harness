"""合并 fetch_results/ 下所有法条 JSON 文件 → data/laws.json"""
import json, sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "fetch_results"
COMMERCIAL = RESULTS / "commercial"
TARGET = Path(__file__).resolve().parent / "server" / "data" / "laws.json"

# 合并顺序
laws = {}

# 1) 完整法律(来自 fetch_results/*.json,排除商经法相关)
for f in sorted(RESULTS.glob("*.json")):
    name = f.stem
    if name == "商经法相关":
        continue  # 用独立的单行法文件代替
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        laws.update(data)
        arts = sum(len(v) for v in data.values())
        print(f"  {name}: {arts}条")
    except Exception as e:
        print(f"  {name}: 跳过({e})", file=sys.stderr)

# 2) 商经单行法(来自 fetch_results/commercial/*.json)
for f in sorted(COMMERCIAL.glob("*.json")):
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        laws.update(data)
        arts = sum(len(v) for v in data.values())
        print(f"  {f.stem}: {arts}条")
    except Exception as e:
        print(f"  {f.stem}: 跳过({e})", file=sys.stderr)

# 写
TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_text(
    json.dumps(laws, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
total_arts = sum(len(v) for v in laws.values())
print(f"\n✅ 已写入 {TARGET}")
print(f"   共 {len(laws)} 部法律, {total_arts} 条")
print(f"   文件大小: {TARGET.stat().st_size / 1024:.0f} KB")
