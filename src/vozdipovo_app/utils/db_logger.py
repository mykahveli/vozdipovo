# src/vozdipovo_app/utils/db_logger.py
import socket
import sqlite3


def log_pipeline_event(
    db_path: str, legal_doc_id: int, stage: str, status: str, message: str = None
):
    """
    Regista um evento do pipeline na tabela de log da base de dados.
    """
    try:
        conn = sqlite3.connect(db_path)
        hostname = socket.gethostname()

        conn.execute(
            """
            INSERT INTO pipeline_log (legal_doc_id, stage, status, message, hostname)
            VALUES (?, ?, ?, ?, ?)
            """,
            (legal_doc_id, stage, status, message, hostname),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Em caso de falha no logging, imprimir para a consola para não perder a informação
        print(f"!!! FALHA CRÍTICA AO REGISTAR NO LOG DA BASE DE DADOS: {e} !!!")
        print(
            f"    Evento não registado: ID={legal_doc_id}, Stage={stage}, Status={status}, Msg={message}"
        )
