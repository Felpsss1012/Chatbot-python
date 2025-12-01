# scripts/mark_conversational.py
import mysql.connector
import re
from normalizacao import normalizar

GREETINGS = {"oi","olá","ola","e aí","e ai","tudo bem","tudo bem?","como você está","como voce esta","bom dia","boa tarde","boa noite","até logo","ate logo"}

def mark(host="127.0.0.1", user="root", passwd=None, db="chatbot"):
    conn = mysql.connector.connect(host=host, user=user, password=passwd, database=db)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, texto FROM respostas")
    rows = cur.fetchall()
    for r in rows:
        rid = r["id"]
        txt = (r["texto"] or "").strip()
        low = normalizar(txt)
        is_conv = False
        if len(txt) < 120:
            # check greeting tokens
            if any(g in low for g in GREETINGS):
                is_conv = True
            else:
                # token overlap heuristic: many stopwords only -> conversacional
                tokens = [t for t in re.findall(r"[^\W\d_]+", low) if len(t) > 1]
                if len(tokens) <= 4:
                    is_conv = True
        cur.execute("UPDATE respostas SET is_conversational = %s WHERE id = %s", (is_conv, rid))
    conn.commit()
    cur.close()
    conn.close()
    print("Marcação finalizada.")
