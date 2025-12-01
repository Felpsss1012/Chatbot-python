# core/check_csv.py
import csv, sys
path = "data/meus_qna.csv"
terms = ["senha", "alterar senha", "osso", "maior osso"]
found = {t: [] for t in terms}
with open(path, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        txt = (row.get("pergunta") or row.get("resposta") or row.get("texto") or "").lower()
        for t in terms:
            if t in txt:
                found[t].append(txt[:200])
for t in terms:
    print(f"=== Termo: {t} -> {len(found[t])} ocorrências ===")
    for ex in found[t][:5]:
        print(" -", ex)
