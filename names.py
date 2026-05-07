import json
from pathlib import Path


PROJECT_DIR = Path(".").resolve()

INPUT_DIR = PROJECT_DIR / "data" / "parsed" / "101_forms"
OUTPUT_PATH = PROJECT_DIR / "data" / "parsed" / "bank_names_101.txt"


bank_names = []

for json_path in sorted(INPUT_DIR.glob("*.json")):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    name = data.get("name")

    if not name:
        print(f"Не удалось найти name в файле: {json_path.name}")
        continue

    bank_names.append(name)


with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for name in bank_names:
        f.write(name + "\n")

print(f"Готово. Записано банков: {len(bank_names)}")
print(f"Файл: {OUTPUT_PATH}")