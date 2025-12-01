# core/gerenciador_memoria.py
from __future__ import annotations

import os
import csv
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Any

from config import LOG_DIR
from normalizacao import normalizar
from banco import (
    adicionar_memoria,
    listar_memorias,
    remover_memoria_por_id,
    editar_memoria,
)

logger = logging.getLogger(__name__)
os.makedirs(LOG_DIR, exist_ok=True)


# ---------- Helpers ----------
def _parse_date_input(date_input: str) -> Optional[str]:
    """
    Aceita: "dd/mm/yyyy", "dd/mm/yyyy hh:mm", "yyyy-mm-dd", "yyyy-mm-dd hh:mm"
    Tenta usar dateparser se disponível (mais flexível). Retorna string no formato MySQL '%Y-%m-%d %H:%M:%S' ou None.
    """
    if not date_input:
        return None
    date_input = date_input.strip()
    # tentativa com dateparser (opcional)
    try:
        import dateparser
        dt = dateparser.parse(date_input, languages=['pt'])
        if dt:
            # padroniza: sempre incluir horas
            if dt.hour == 0 and dt.minute == 0 and "h" not in date_input and ":" not in date_input:
                # sem hora informada -> deixa 00:00:00
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # tentativa manual com formatos comuns
    fmts = ["%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_input, fmt)
            # se o formato não inclui segundos, garante formatação completa
            if fmt == "%d/%m/%Y":
                dt = dt.replace(hour=0, minute=0, second=0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return None


def _normalize_tags(tags_str: Optional[str]) -> Optional[str]:
    if not tags_str:
        return None
    tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
    return ",".join(sorted(dict.fromkeys(tags))) if tags else None


def _format_datetime_for_display(dt_value: Any) -> str:
    if not dt_value:
        return "(sem data definida)"
    if isinstance(dt_value, str):
        try:
            # tentamos parsear formato MySQL
            dt = datetime.strptime(dt_value[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(dt_value)
    if isinstance(dt_value, datetime):
        return dt_value.strftime("%d/%m/%Y %H:%M")
    return str(dt_value)


# ---------- Funções interativas / utilitárias ----------
def listar_e_mostrar(conn, tipo: Optional[str] = None) -> List[Tuple[int, str, str, Any, bool, Optional[str]]]:
    """
    Lista memórias (usa listar_memorias do banco) e imprime de forma legível.
    Retorna a lista de tuplas conforme o retorno de listar_memorias.
    """
    memorias = listar_memorias(conn, tipo)
    if not memorias:
        print("🤖 Nenhum registro encontrado.\n")
        return []

    print("📋 Lista de memórias:")
    for i, row in enumerate(memorias, 1):
        # Suporta tuplas com diferentes comprimentos. Padrão esperado:
        # (id, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags, ...)
        memoria_id = row[0] if len(row) > 0 else None
        tipo_mem = row[1] if len(row) > 1 else "(sem tipo)"
        descricao = row[2] if len(row) > 2 else "(sem descrição)"
        data_evento = row[3] if len(row) > 3 else None
        repetir_anualmente = row[4] if len(row) > 4 else False
        prioridade = row[5] if len(row) > 5 else None
        tags = row[6] if len(row) > 6 else None

        data_str = _format_datetime_for_display(data_evento)
        tags_str = tags if tags else "(nenhuma)"
        print(f"{i}. [#{memoria_id}] [{tipo_mem}] {descricao} | Data: {data_str} | Repetir: {'Sim' if repetir_anualmente else 'Não'} | Prioridade: {prioridade or '(nenhuma)'} | Tags: {tags_str}")
    print()
    return memorias


def adicionar_memoria_interativa(conn) -> Optional[int]:
    """
    Interativo: coleta dados do usuário e chama adicionar_memoria(conn,...).
    Retorna id (quando o banco retornar) ou True/None conforme sucesso/falha.
    """
    print("\n📌 Adicionar nova memória (modo interativo)\n")
    tipo = input("Tipo (tarefa/evento/aniversario/lembrete): ").strip().lower()
    if tipo == "":
        tipo = "lembrete"
    descricao = input("Descrição: ").strip() or None
    data_input = input("Data (opcional, ex: 05/07/2025 14:00): ").strip()
    data_evento = _parse_date_input(data_input) if data_input else None

    repetir = input("Repetir anualmente? (s/n) [n]: ").strip().lower()
    repetir_anualmente = repetir == "s"

    prioridade = input("Prioridade (baixa/media/alta) (opcional): ").strip().lower() or None
    if prioridade and prioridade not in {"baixa", "media", "alta"}:
        print("Prioridade inválida; usando None.")
        prioridade = None

    tags_input = input("Tags (opcional, sep. por vírgula): ").strip()
    tags = _normalize_tags(tags_input)

    # confirmar
    print("\nConfirme:")
    print(f"Tipo: {tipo}")
    print(f"Descrição: {descricao or '(sem descrição)'}")
    print(f"Data: {_format_datetime_for_display(data_evento)}")
    print(f"Repetir anualmente: {'Sim' if repetir_anualmente else 'Não'}")
    print(f"Prioridade: {prioridade or '(nenhuma)'}")
    print(f"Tags: {tags or '(nenhuma)'}")
    ok = input("Salvar? (s/n): ").strip().lower()
    if ok != "s":
        print("Operação cancelada.")
        return None

    try:
        # adicionar_memoria deve suportar assinatura (conn, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags)
        adicionar_memoria(conn, tipo, descricao, data_evento, repetir_anualmente, prioridade, tags)
        print("✅ Memória salva com sucesso.\n")
        return True
    except Exception as e:
        logger.error("Falha ao salvar memória: %s", e)
        print("❌ Erro ao salvar memória.\n")
        return None


def remover_memoria_interativa(conn) -> None:
    memorias = listar_e_mostrar(conn)
    if not memorias:
        return
    pos = input("Digite o número da memória a remover: ").strip()
    if not pos.isdigit() or not (1 <= int(pos) <= len(memorias)):
        print("Número inválido.")
        return
    idx = int(pos) - 1
    memoria_id = memorias[idx][0]
    confirmar = input(f"Confirma remover #{memoria_id}? (s/n): ").strip().lower()
    if confirmar != "s":
        print("Cancelado.")
        return
    try:
        remover_memoria_por_id(conn, memoria_id)
        print("🗑️ Memória removida.\n")
    except Exception as e:
        logger.error("Erro ao remover memória: %s", e)
        print("Erro ao remover memória.\n")


def editar_memoria_interativa(conn) -> None:
    memorias = listar_e_mostrar(conn)
    if not memorias:
        return
    pos = input("Digite o número da memória a editar: ").strip()
    if not pos.isdigit() or not (1 <= int(pos) <= len(memorias)):
        print("Número inválido.")
        return
    idx = int(pos) - 1
    memoria_id = memorias[idx][0]

    nova_descricao = input("Nova descrição (deixe em branco para manter): ").strip() or None
    nova_data = input("Nova data (dd/mm/yyyy ou dd/mm/yyyy hh:mm) (ou deixe em branco): ").strip()
    nova_data_formatada = _parse_date_input(nova_data) if nova_data else None
    nova_prioridade = input("Nova prioridade (baixa/media/alta) (ou em branco): ").strip().lower() or None
    if nova_prioridade and nova_prioridade not in {"baixa", "media", "alta"}:
        print("Prioridade inválida; ignorando.")
        nova_prioridade = None
    nova_tags = input("Novas tags (sep. por vírgula) (ou em branco): ").strip() or None
    nova_tags = _normalize_tags(nova_tags) if nova_tags else None

    if not any([nova_descricao, nova_data_formatada, nova_prioridade, nova_tags]):
        print("Nada para alterar.")
        return

    try:
        editar_memoria(conn, memoria_id, nova_descricao, nova_data_formatada, nova_prioridade, nova_tags)
        print("✅ Memória atualizada.\n")
    except Exception as e:
        logger.error("Erro ao editar memória: %s", e)
        print("Erro ao atualizar memória.\n")


def listar_memorias_interativa(conn) -> None:
    """
    Menu interativo de listagem: filtrar por tipo, tag, intervalo de datas ou buscar por texto.
    """
    print("\nComo deseja filtrar as memórias?")
    print("1) Todas")
    print("2) Por tipo")
    print("3) Por tag")
    print("4) Próximos X dias")
    print("5) Buscar texto")
    opcao = input("Escolha: ").strip()
    if opcao == "1":
        listar_e_mostrar(conn, None)
    elif opcao == "2":
        t = input("Tipo (tarefa/evento/aniversario/lembrete): ").strip().lower()
        listar_e_mostrar(conn, t)
    elif opcao == "3":
        tag = input("Tag (ex: escola): ").strip().lower()
        memorias = listar_memorias(conn, None)
        filtradas = [m for m in memorias if len(m) > 6 and m[6] and tag in str(m[6]).lower()]
        if not filtradas:
            print("Nenhuma memória com essa tag.")
            return
        for i, m in enumerate(filtradas, 1):
            print(f"{i}. [{m[0]}] {m[2]} | Tags: {m[6]}")
    elif opcao == "4":
        dias = input("Quantos dias à frente? (ex: 7): ").strip()
        try:
            dias_i = int(dias)
        except Exception:
            dias_i = 7
        agora = datetime.now()
        limite = agora + timedelta(days=dias_i)
        memorias = listar_memorias(conn, None)
        proximas = []
        for m in memorias:
            data = m[3] if len(m) > 3 else None
            try:
                if data:
                    dt = datetime.strptime(str(data)[:19], "%Y-%m-%d %H:%M:%S")
                    if agora <= dt <= limite:
                        proximas.append(m)
            except Exception:
                continue
        if not proximas:
            print("Nenhuma memória nos próximos dias.")
            return
        for i, m in enumerate(proximas, 1):
            print(f"{i}. [{m[0]}] {m[2]} | {m[3]}")
    elif opcao == "5":
        q = input("Digite termo de busca: ").strip().lower()
        memorias = listar_memorias(conn, None)
        encontrados = []
        # tenta fuzzy com rapidfuzz se disponível
        try:
            from rapidfuzz import fuzz
            for m in memorias:
                texto = " ".join([str(x) for x in m[2:6] if x])
                score = fuzz.partial_ratio(q, texto.lower())
                if score >= 60:
                    encontrados.append((score, m))
            encontrados.sort(key=lambda t: t[0], reverse=True)
            encontrados = [m for _, m in encontrados]
        except Exception:
            for m in memorias:
                texto = " ".join([str(x) for x in m[2:6] if x]).lower()
                if q in texto:
                    encontrados.append(m)
        if not encontrados:
            print("Nenhuma memória encontrada.")
            return
        for i, m in enumerate(encontrados, 1):
            print(f"{i}. [{m[0]}] {m[2]} | {m[3]} | Tags: {m[6] if len(m)>6 else ''}")
    else:
        print("Opção inválida.")


# ---------- Export / Import ----------
def exportar_memorias_csv(conn, out_path: Optional[str] = None) -> str:
    """
    Exporta todas as memórias para CSV. Retorna caminho do arquivo gerado.
    """
    out_path = out_path or os.path.join(LOG_DIR, f"memorias_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    memorias = listar_memorias(conn, None)
    if not memorias:
        raise RuntimeError("Nenhuma memória para exportar.")
    header = ["id", "tipo", "descricao", "data_evento", "repetir_anualmente", "prioridade", "tags"]
    try:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for m in memorias:
                row = [m[i] if i < len(m) else "" for i in range(7)]
                writer.writerow(row)
    except Exception as e:
        logger.error("Erro ao exportar memórias: %s", e)
        raise
    return out_path


def exportar_memorias_json(conn, out_path: Optional[str] = None) -> str:
    out_path = out_path or os.path.join(LOG_DIR, f"memorias_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    memorias = listar_memorias(conn, None)
    if not memorias:
        raise RuntimeError("Nenhuma memória para exportar.")
    payload = []
    for m in memorias:
        payload.append({
            "id": m[0] if len(m) > 0 else None,
            "tipo": m[1] if len(m) > 1 else None,
            "descricao": m[2] if len(m) > 2 else None,
            "data_evento": m[3] if len(m) > 3 else None,
            "repetir_anualmente": m[4] if len(m) > 4 else False,
            "prioridade": m[5] if len(m) > 5 else None,
            "tags": m[6] if len(m) > 6 else None,
        })
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Erro ao exportar JSON: %s", e)
        raise
    return out_path


# ---------- Lembretes / Agendamento simples ----------
def verificar_e_alertar(conn, dias_a_frente: int = 1) -> List[Tuple]:
    """
    Verifica memórias com data nos próximos `dias_a_frente` dias e retorna lista.
    Não faz TTS por si só; retorna para o caller decidir (main_chat pode chamar speaker).
    """
    memorias = listar_memorias(conn, None)
    if not memorias:
        return []
    agora = datetime.now()
    limite = agora + timedelta(days=dias_a_frente)
    proximas = []
    for m in memorias:
        data = m[3] if len(m) > 3 else None
        try:
            if data:
                dt = datetime.strptime(str(data)[:19], "%Y-%m-%d %H:%M:%S")
                if agora <= dt <= limite:
                    proximas.append(m)
        except Exception:
            continue
    return proximas


def agendar_verificacao_periodica(conn, intervalo_minutos: int = 60, dias_a_frente: int = 1):
    """
    Inicia thread que a cada `intervalo_minutos` verifica memórias próximas e grava em log
    (ou você pode ligar isso ao speaker do main_chat).
    """
    def _loop():
        while True:
            try:
                proximas = verificar_e_alertar(conn, dias_a_frente)
                if proximas:
                    logger.info("Memórias próximas: %d itens", len(proximas))
                # pause
            except Exception as e:
                logger.error("Erro no agendamento de verificação: %s", e)
            finally:
                import time
                time.sleep(max(1, intervalo_minutos) * 60)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


# ---------- CLI de demonstração ----------
if __name__ == "__main__":
    # modo demo: conecta ao banco e exibe menu simples
    try:
        from core.banco import inicializar_banco
        conn = inicializar_banco()
    except Exception as e:
        print("Erro ao inicializar banco:", e)
        conn = None

    while True:
        print("\nO que deseja fazer? add/list/remove/edit/export/next/quit")
        cmd = input("Comando: ").strip().lower()
        if cmd in {"q", "quit", "exit"}:
            break
        if cmd == "add":
            if conn:
                adicionar_memoria_interativa(conn)
            else:
                print("Sem conexão com banco.")
        elif cmd == "list":
            if conn:
                listar_memorias_interativa(conn)
            else:
                print("Sem conexão com banco.")
        elif cmd == "remove":
            if conn:
                remover_memoria_interativa(conn)
            else:
                print("Sem conexão com banco.")
        elif cmd == "edit":
            if conn:
                editar_memoria_interativa(conn)
            else:
                print("Sem conexão com banco.")
        elif cmd == "export":
            if conn:
                p = exportar_memorias_csv(conn)
                print("Exportado para:", p)
            else:
                print("Sem conexão com banco.")
        elif cmd == "next":
            if conn:
                prox = verificar_e_alertar(conn, dias_a_frente=7)
                if not prox:
                    print("Nenhum lembrete nos próximos 7 dias.")
                else:
                    for m in prox:
                        print(f"- [{m[0]}] {m[2]} em {m[3]}")
            else:
                print("Sem conexão com banco.")
        else:
            print("Comando inválido.")
