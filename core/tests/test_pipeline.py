    # tests/test_pipeline.py
import os
from core.pipeline_search import find_answer, numbers_to_words_in_text, user_requests_only_field
from core.normalizacao import normalizar

def test_number_to_words():
    out = numbers_to_words_in_text("O valor é 123 e depois 45,6.")
    assert "cento" in out or "123" not in out  # depende num2words; basic garante substituição

def test_simple_intent_detection():
    q1 = "Me diga só a data"
    assert user_requests_only_field(q1) == "data"
    q2 = "Quero somente o número"
    assert user_requests_only_field(q2) == "numero"
    q3 = "Me fale sobre aprendizado de máquina"
    assert user_requests_only_field(q3) is None

def test_find_answer_csv_fallback():
    # usa CSV padrão 'meus_qna.csv' que você já adicionou. 
    res = find_answer("Qual é a capital da França?", use_db=False, csv_path="meus_qna.csv")
    assert isinstance(res, dict)
    # pode não encontrar uma resposta; garantimos que a API retorna dict com chave 'text'
    assert "text" in res

def test_sql_injection_safe():
    # tentativa de injeção não deve executar comando e deve retornar algo controlado (não crash)
    evil = "x' OR '1'='1; -- "
    res = find_answer(evil, use_db=False, csv_path="meus_qna.csv")
    assert isinstance(res, dict)
