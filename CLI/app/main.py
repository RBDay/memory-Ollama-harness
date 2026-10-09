import os
import sys
import argparse
from typing import Optional, List
from app.api_client import APIClient, collect_files_from_paths
from app.ui import (
    print_banner,
    print_success,
    print_error,
    print_info,
    print_sessions_table,
    print_session_header,
    print_history_banner,
    render_message,
    print_files_table,
    print_vector_context_summary,
    format_size,
    RICH_AVAILABLE,
    console,
)

if RICH_AVAILABLE:
    from rich.prompt import Prompt, Confirm


def cmd_list(client: APIClient, args):
    """Lista todas las sesiones registradas en MongoDB."""
    try:
        data = client.list_sessions(limit=100)
        sessions = data.get("sessions", [])
        print_sessions_table(sessions)
    except Exception as e:
        print_error(f"No se pudieron listar las sesiones: {e}")


def cmd_create(client: APIClient, args):
    """Crea una nueva sesión con su propio contexto inicial y memoria vectorial opcional."""
    title = getattr(args, "title", None)
    system_prompt = getattr(args, "prompt", None)
    model = getattr(args, "model", None)
    session_id = getattr(args, "id", None)
    files = getattr(args, "files", None)
    dir_path = getattr(args, "dir", None)

    is_interactive = (getattr(args, "command", None) is None) and sys.stdin.isatty()

    # Modo interactivo si falta información básica y estamos en modo menú
    if not title:
        if is_interactive and RICH_AVAILABLE:
            title = Prompt.ask("[bold]Título de la sesión[/bold]", default="Nueva Sesión")
        elif is_interactive:
            title = input("Título de la sesión [Nueva Sesión]: ") or "Nueva Sesión"
        else:
            title = "Nueva Sesión"

    if system_prompt is None:
        if is_interactive and RICH_AVAILABLE:
            system_prompt = Prompt.ask(
                "[bold]Contexto inicial / System Prompt (opcional)[/bold]", default=""
            )
        elif is_interactive:
            system_prompt = input("Contexto inicial / System Prompt (opcional): ")
        else:
            system_prompt = None

    if system_prompt and not system_prompt.strip():
        system_prompt = None

    if not model:
        default_model = "qwen2.5-coder:7b"
        if is_interactive and RICH_AVAILABLE:
            model = Prompt.ask(
                "[bold]Modelo de Ollama[/bold]", default=default_model
            ).strip()
        elif is_interactive:
            model = input(f"Modelo de Ollama [{default_model}]: ").strip() or default_model
        else:
            model = default_model

    # Archivos para memoria vectorial
    paths_to_collect: List[str] = []
    if files:
        paths_to_collect.extend(files)
    if dir_path:
        paths_to_collect.append(dir_path)

    # Si estamos en modo interactivo y no se pasaron archivos por flags, preguntar al usuario
    if not paths_to_collect and is_interactive:
        attach_files = False
        if RICH_AVAILABLE:
            attach_files = Confirm.ask(
                "¿Deseas adjuntar archivos o una carpeta para memoria vectorial en LanceDB?",
                default=False,
            )
        else:
            ans = input("¿Adjuntar archivos/carpeta para memoria vectorial? (s/N): ").strip().lower()
            attach_files = ans in ("s", "si", "y", "yes")

        if attach_files:
            input_path = (
                Prompt.ask("Ruta del archivo, ZIP o carpeta a indexar").strip()
                if RICH_AVAILABLE
                else input("Ruta de archivo/carpeta: ").strip()
            )
            if input_path:
                paths_to_collect.append(input_path)

    collected_files: List[tuple] = []
    if paths_to_collect:
        try:
            collected_files = collect_files_from_paths(paths_to_collect)
            print_info(f"Se encontraron {len(collected_files)} archivos locales listos para indexar.")
        except Exception as e:
            print_error(f"Error procesando archivos locales: {e}")
            return

    try:
        sess_id = None
        if collected_files:
            if RICH_AVAILABLE:
                with console.status(
                    "[bold green]Generando embeddings con Ollama e indexando en LanceDB...[/bold green]",
                    spinner="dots",
                ):
                    res = client.create_session(
                        title=title,
                        system_prompt=system_prompt,
                        model=model,
                        session_id=session_id,
                        files=collected_files,
                    )
            else:
                print("Indexando archivos en LanceDB y MinIO...")
                res = client.create_session(
                    title=title,
                    system_prompt=system_prompt,
                    model=model,
                    session_id=session_id,
                    files=collected_files,
                )

            sess_info = res.get("session", {})
            v_ctx = res.get("vector_context", {})
            sess_id = sess_info.get("session_id")
            print_success(f"Sesión creada con memoria vectorial: [bold cyan]{sess_id}[/bold cyan]")
            if v_ctx:
                print_vector_context_summary(v_ctx)
            print_info(f"Modelo configurado: [bold green]{sess_info.get('model')}[/bold green]")
        else:
            res = client.create_session(
                title=title,
                system_prompt=system_prompt,
                model=model,
                session_id=session_id,
            )
            sess_id = res["session_id"]
            print_success(f"Sesión creada exitosamente: [bold cyan]{sess_id}[/bold cyan]")
            print_info(f"Modelo configurado: [bold green]{res.get('model')}[/bold green]")

        if system_prompt:
            print_info(f"Contexto configurado: \"{system_prompt}\"")

        # Preguntar si iniciar chat de inmediato (solo en modo interactivo)
        start_now = False
        if is_interactive and sess_id:
            if RICH_AVAILABLE:
                start_now = Confirm.ask("¿Deseas entrar al chat con esta sesión ahora?", default=True)
            else:
                ans = input("¿Deseas entrar al chat ahora? (S/n): ").strip().lower()
                start_now = ans in ("", "s", "si", "y", "yes")

        if start_now and sess_id:
            run_chat(client, sess_id)

    except Exception as e:
        print_error(f"Error creando la sesión: {e}")


def cmd_refresh(client: APIClient, args):
    """Refresca el contexto vectorial de una sesión reemplazando los archivos en LanceDB y MinIO."""
    session_id = getattr(args, "session_id", None)
    files = getattr(args, "files", None)
    dir_path = getattr(args, "dir", None)

    if not session_id:
        try:
            data = client.list_sessions(limit=50)
            sessions = data.get("sessions", [])
            if not sessions:
                print_error("No hay sesiones disponibles para refrescar.")
                return
            print_sessions_table(sessions)
            session_id = (
                Prompt.ask("[bold]Introduce el ID de la sesión a refrescar[/bold]")
                if RICH_AVAILABLE
                else input("ID de la sesión: ").strip()
            )
        except Exception as e:
            print_error(f"Error listando sesiones: {e}")
            return

    paths_to_collect: List[str] = []
    if files:
        paths_to_collect.extend(files)
    if dir_path:
        paths_to_collect.append(dir_path)

    if not paths_to_collect:
        input_path = (
            Prompt.ask("Ruta del nuevo archivo, ZIP o carpeta para el contexto vectorial").strip()
            if RICH_AVAILABLE
            else input("Ruta de archivo o carpeta: ").strip()
        )
        if input_path:
            paths_to_collect.append(input_path)

    if not paths_to_collect:
        print_error("Debes especificar al menos un archivo o carpeta para refrescar.")
        return

    try:
        collected = collect_files_from_paths(paths_to_collect)
        print_info(f"Se encontraron {len(collected)} archivos locales listos para sustituir el contexto.")
        if RICH_AVAILABLE:
            with console.status(
                "[bold green]Reemplazando contexto y reindexando en LanceDB...[/bold green]",
                spinner="dots",
            ):
                res = client.refresh_session_files(session_id, collected)
        else:
            print("Reindexando archivos...")
            res = client.refresh_session_files(session_id, collected)

        print_success(f"Contexto vectorial refrescado con éxito para la sesión '{session_id}'.")
        print_vector_context_summary(res)
    except Exception as e:
        print_error(f"Error refrescando el contexto vectorial: {e}")


def cmd_files(client: APIClient, args):
    """Lista todos los archivos almacenados e indexados para una sesión."""
    session_id = getattr(args, "session_id", None)
    if not session_id:
        try:
            data = client.list_sessions(limit=50)
            sessions = data.get("sessions", [])
            if not sessions:
                print_error("No hay sesiones registradas.")
                return
            print_sessions_table(sessions)
            session_id = (
                Prompt.ask("[bold]Introduce el ID de la sesión[/bold]")
                if RICH_AVAILABLE
                else input("ID de la sesión: ").strip()
            )
        except Exception as e:
            print_error(f"Error listando sesiones: {e}")
            return

    try:
        res = client.list_session_files(session_id)
        files = res.get("files", [])
        print_files_table(session_id, files)
    except Exception as e:
        print_error(f"Error obteniendo archivos de la sesión: {e}")


def cmd_export(client: APIClient, args):
    """Descarga todos los archivos de una sesión recursivamente en un archivo ZIP."""
    session_id = getattr(args, "session_id", None)
    destination = getattr(args, "output", None)

    if not session_id:
        try:
            data = client.list_sessions(limit=50)
            sessions = data.get("sessions", [])
            if not sessions:
                print_error("No hay sesiones registradas.")
                return
            print_sessions_table(sessions)
            session_id = (
                Prompt.ask("[bold]Introduce el ID de la sesión a exportar[/bold]")
                if RICH_AVAILABLE
                else input("ID de la sesión: ").strip()
            )
        except Exception as e:
            print_error(f"Error listando sesiones: {e}")
            return

    try:
        if RICH_AVAILABLE:
            with console.status(
                "[bold green]Descargando y empaquetando archivos en ZIP desde MinIO...[/bold green]",
                spinner="dots",
            ):
                saved_path = client.export_session_files(session_id, destination)
        else:
            print("Descargando archivo ZIP...")
            saved_path = client.export_session_files(session_id, destination)

        size = os.path.getsize(saved_path)
        print_success(
            f"Archivos exportados exitosamente en: [bold cyan]{saved_path}[/bold cyan] ({format_size(size)})"
        )
    except Exception as e:
        print_error(f"Error exportando archivos: {e}")


def cmd_delete(client: APIClient, args):
    """Elimina una sesión y vacía su memoria en MongoDB y LanceDB/MinIO."""
    session_id = getattr(args, "session_id", None)
    if not session_id:
        print_error("Debes especificar el ID de la sesión a eliminar.")
        return

    confirm = False
    if getattr(args, "yes", False) or not sys.stdin.isatty():
        confirm = True
    elif RICH_AVAILABLE:
        confirm = Confirm.ask(
            f"¿Estás seguro de que deseas eliminar la sesión '[cyan]{session_id}[/cyan]' y todas sus memorias?",
            default=False,
        )
    else:
        ans = input(f"¿Eliminar sesión '{session_id}' y memorias? (s/N): ").strip().lower()
        confirm = ans in ("s", "si", "y", "yes")

    if not confirm:
        print_info("Operación cancelada.")
        return

    try:
        res = client.delete_session(session_id)
        msgs_cnt = res.get("deleted_messages_count", 0)
        vec_cnt = res.get("deleted_vector_objects_count", 0)
        extra_info = f"{msgs_cnt} mensajes"
        if vec_cnt > 0:
            extra_info += f", {vec_cnt} objetos vectoriales LanceDB/MinIO eliminados"
        print_success(f"Sesión '{session_id}' eliminada ({extra_info}).")
    except Exception as e:
        print_error(f"Error eliminando la sesión: {e}")


def cmd_clear(client: APIClient, args):
    """Vacía la memoria de una sesión manteniendo la sesión activa."""
    session_id = getattr(args, "session_id", None)
    if not session_id:
        print_error("Debes especificar el ID de la sesión.")
        return

    try:
        res = client.clear_session_memory(session_id)
        print_success(f"Memoria de la sesión vaciada ({res.get('deleted_count', 0)} mensajes eliminados).")
    except Exception as e:
        print_error(f"Error vaciando la memoria: {e}")


def run_chat(client: APIClient, session_id: str):
    """Bucle principal de conversación interactiva con contexto y memoria previa."""
    try:
        session = client.get_session(session_id)
    except Exception as e:
        print_error(f"No se pudo cargar la sesión '{session_id}': {e}")
        return

    print_session_header(session)

    try:
        mem_data = client.get_session_memory(session_id, limit=50)
        messages = mem_data.get("messages", [])
        total = mem_data.get("total", len(messages))

        if messages:
            print_history_banner(len(messages), total)
            for msg in messages:
                render_message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    model=session.get("model"),
                    metadata=msg.get("metadata"),
                )
        else:
            print_info("La memoria de esta sesión está vacía. Inicia la conversación a continuación.")
    except Exception as e:
        print_error(f"No se pudo recuperar el historial previo: {e}")

    if RICH_AVAILABLE:
        console.print(
            "[dim]Comandos especiales: /files (ver archivos) | /export (descargar ZIP) | /refresh (sustituir archivos) | /clear (vaciar memoria) | /context (ver prompt) | /exit (salir)[/dim]\n"
        )
    else:
        print("Comandos: /files, /export, /refresh, /clear, /context, /exit\n")

    while True:
        try:
            if RICH_AVAILABLE:
                user_input = Prompt.ask("[bold cyan]Tú[/bold cyan]").strip()
            else:
                user_input = input("Tú > ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                print_info("Saliendo de la sesión de chat...")
                break

            if user_input.lower() == "/context":
                ctx = session.get("system_prompt") or "Sin contexto inicial asignado."
                print_info(f"System Prompt / Contexto: {ctx}")
                continue

            if user_input.lower() == "/files":
                try:
                    f_res = client.list_session_files(session_id)
                    print_files_table(session_id, f_res.get("files", []))
                except Exception as e:
                    print_error(f"Error listando archivos: {e}")
                continue

            if user_input.lower().startswith("/export"):
                parts = user_input.split(maxsplit=1)
                dest = parts[1].strip() if len(parts) > 1 else None
                try:
                    out = client.export_session_files(session_id, dest)
                    print_success(f"Archivos exportados a: [cyan]{out}[/cyan]")
                except Exception as e:
                    print_error(f"Error exportando archivos: {e}")
                continue

            if user_input.lower() == "/refresh":
                p = (
                    Prompt.ask("Ruta del archivo o carpeta para el nuevo contexto").strip()
                    if RICH_AVAILABLE
                    else input("Ruta: ").strip()
                )
                if p:
                    try:
                        coll = collect_files_from_paths([p])
                        res = client.refresh_session_files(session_id, coll)
                        print_success("Contexto vectorial actualizado en LanceDB.")
                        print_vector_context_summary(res)
                    except Exception as e:
                        print_error(f"Error refrescando contexto: {e}")
                continue

            if user_input.lower() == "/clear":
                confirm = (
                    Confirm.ask("¿Vaciar memoria de esta sesión?", default=False)
                    if RICH_AVAILABLE
                    else input("¿Vaciar memoria? (s/N): ").lower() in ("s", "si")
                )
                if confirm:
                    client.clear_session_memory(session_id)
                    print_success("Memoria reiniciada.")
                continue

            if user_input.lower() == "/help":
                print_info("Comandos disponibles en el chat:")
                print("  /files    - Ver archivos indexados en LanceDB")
                print("  /export   - Descargar archivos de la sesión en un archivo ZIP")
                print("  /refresh  - Reemplazar archivos de contexto con nueva carpeta/archivo")
                print("  /clear    - Vacía la memoria de la conversación")
                print("  /context  - Muestra el contexto / system_prompt de la sesión")
                print("  /exit     - Vuelve al menú o sale de la CLI")
                continue

            # Inferencia con Ollama a través del Harness
            if RICH_AVAILABLE:
                with console.status(
                    f"[bold green]Pensando ({session.get('model', 'ollama')})...[/bold green]",
                    spinner="dots",
                ):
                    chat_res = client.chat(session_id, user_input)
            else:
                print("Pensando...")
                chat_res = client.chat(session_id, user_input)

            assistant_msg = chat_res.get("assistant_message", {})
            render_message(
                role="assistant",
                content=assistant_msg.get("content", ""),
                model=chat_res.get("model"),
                metadata=assistant_msg.get("metadata"),
            )

        except (KeyboardInterrupt, EOFError):
            print("\n")
            print_info("Chat interrumpido por el usuario. Saliendo...")
            break
        except Exception as e:
            print_error(f"Error durante la inferencia: {e}")


def cmd_chat(client: APIClient, args):
    """Inicia el chat interactivo para la sesión indicada o permite seleccionarla."""
    session_id = getattr(args, "session_id", None)
    if not session_id:
        try:
            data = client.list_sessions(limit=50)
            sessions = data.get("sessions", [])
            if not sessions:
                print_error("No hay sesiones disponibles. Primero crea una sesión con 'create'.")
                return
            print_sessions_table(sessions)
            if RICH_AVAILABLE:
                session_id = Prompt.ask("[bold]Introduce el ID de la sesión a abrir[/bold]")
            else:
                session_id = input("Introduce el ID de la sesión: ").strip()
        except Exception as e:
            print_error(f"Error listando sesiones: {e}")
            return

    if session_id:
        run_chat(client, session_id.strip())


def interactive_menu(client: APIClient):
    """Menú interactivo guiado cuando no se proveen argumentos."""
    print_banner()

    try:
        health = client.check_health()
        ollama_status = health.get("ollama", {}).get("status", "unknown")
        mongo_status = health.get("mongo", "unknown")
        minio_status = health.get("minio", "unknown")
        if RICH_AVAILABLE:
            console.print(
                f"[dim]MongoDB: [green]{mongo_status}[/] | MinIO: [green]{minio_status}[/] | Ollama: [green]{ollama_status}[/] | Backend: [cyan]{client.base_url}[/][/dim]\n"
            )
    except Exception:
        print_error(
            f"No se pudo contactar con la API en '{client.base_url}'. Asegúrate de que los contenedores estén activos."
        )

    while True:
        try:
            if RICH_AVAILABLE:
                console.print("[bold cyan]Opciones:[/bold cyan]")
                print("  [1] Listar sesiones")
                print("  [2] Iniciar chat con una sesión")
                print("  [3] Crear una nueva sesión (con o sin archivos/carpeta)")
                print("  [4] Listar archivos de una sesión (LanceDB / MinIO)")
                print("  [5] Refrescar contexto vectorial de una sesión")
                print("  [6] Exportar archivos de una sesión (ZIP)")
                print("  [7] Vaciar memoria conversacional de una sesión")
                print("  [8] Eliminar una sesión (y su memoria vectorial)")
                print("  [9] Salir")
                choice = Prompt.ask(
                    "\nSelecciona una opción",
                    choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
                    default="1",
                )
            else:
                print("\nOpciones: [1] Listar [2] Chat [3] Crear [4] Archivos [5] Refrescar [6] Exportar [7] Vaciar [8] Eliminar [9] Salir")
                choice = input("Opción: ").strip()

            if choice == "1":
                cmd_list(client, None)
            elif choice == "2":
                class DummyChatArgs:
                    session_id = None
                cmd_chat(client, DummyChatArgs())
            elif choice == "3":
                class DummyCreateArgs:
                    title = None
                    prompt = None
                    model = None
                    id = None
                    files = None
                    dir = None
                    command = None
                cmd_create(client, DummyCreateArgs())
            elif choice == "4":
                class DummyFilesArgs:
                    session_id = None
                cmd_files(client, DummyFilesArgs())
            elif choice == "5":
                class DummyRefreshArgs:
                    session_id = None
                    files = None
                    dir = None
                cmd_refresh(client, DummyRefreshArgs())
            elif choice == "6":
                class DummyExportArgs:
                    session_id = None
                    output = None
                cmd_export(client, DummyExportArgs())
            elif choice == "7":
                s_id = (
                    Prompt.ask("ID de la sesión a vaciar")
                    if RICH_AVAILABLE
                    else input("ID de la sesión: ")
                )
                class DummyClearArgs:
                    session_id = s_id
                cmd_clear(client, DummyClearArgs())
            elif choice == "8":
                s_id = (
                    Prompt.ask("ID de la sesión a eliminar")
                    if RICH_AVAILABLE
                    else input("ID de la sesión: ")
                )
                class DummyDeleteArgs:
                    session_id = s_id
                cmd_delete(client, DummyDeleteArgs())
            elif choice == "9":
                print_info("¡Hasta pronto!")
                break
            print()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            print_info("Saliendo...")
            break


def main():
    parser = argparse.ArgumentParser(
        prog="ollama_local_chat_memory",
        description="CLI para gestionar sesiones, memoria conversacional en MongoDB y memoria vectorial en LanceDB + MinIO.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="URL base de la API (por defecto: http://localhost:8001/api/v1 o variable API_URL)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # list
    subparsers.add_parser("list", help="Listar todas las sesiones registradas")

    # create
    p_create = subparsers.add_parser("create", help="Crear una nueva sesión con contexto")
    p_create.add_argument("--id", default=None, help="ID personalizado para la sesión")
    p_create.add_argument("--title", default=None, help="Título de la sesión")
    p_create.add_argument("--prompt", default=None, help="System prompt o contexto inicial")
    p_create.add_argument("--model", default=None, help="Modelo Ollama a utilizar")
    p_create.add_argument("--files", nargs="+", default=None, help="Uno o varios archivos para indexar en LanceDB")
    p_create.add_argument("--dir", "--folder", dest="dir", default=None, help="Carpeta local para indexar recursivamente en LanceDB")

    # refresh
    p_refresh = subparsers.add_parser("refresh", help="Refrescar el contexto vectorial de una sesión con nuevos archivos")
    p_refresh.add_argument("session_id", nargs="?", default=None, help="ID de la sesión")
    p_refresh.add_argument("--files", nargs="+", default=None, help="Uno o varios archivos para el nuevo contexto")
    p_refresh.add_argument("--dir", "--folder", dest="dir", default=None, help="Carpeta local para el nuevo contexto")

    # files
    p_files = subparsers.add_parser("files", help="Listar los archivos indexados de una sesión")
    p_files.add_argument("session_id", nargs="?", default=None, help="ID de la sesión")

    # export
    p_export = subparsers.add_parser("export", help="Exportar archivos de una sesión recursivamente como ZIP")
    p_export.add_argument("session_id", nargs="?", default=None, help="ID de la sesión")
    p_export.add_argument("-o", "--output", default=None, help="Ruta de destino del archivo ZIP descargado")

    # chat
    p_chat = subparsers.add_parser("chat", help="Entrar al chat en tiempo real de una sesión")
    p_chat.add_argument("session_id", nargs="?", default=None, help="ID de la sesión a cargar")

    # delete
    p_del = subparsers.add_parser("delete", help="Eliminar una sesión y todas sus memorias")
    p_del.add_argument("session_id", help="ID de la sesión a eliminar")
    p_del.add_argument("-y", "--yes", action="store_true", help="Confirmar eliminación sin preguntar interactiva")

    # clear
    p_clear = subparsers.add_parser("clear", help="Vaciar la memoria de una sesión")
    p_clear.add_argument("session_id", help="ID de la sesión a vaciar")

    args = parser.parse_args()
    client = APIClient(base_url=args.api_url)

    if args.command == "list":
        cmd_list(client, args)
    elif args.command == "create":
        cmd_create(client, args)
    elif args.command == "refresh":
        cmd_refresh(client, args)
    elif args.command == "files":
        cmd_files(client, args)
    elif args.command == "export":
        cmd_export(client, args)
    elif args.command == "chat":
        cmd_chat(client, args)
    elif args.command == "delete":
        cmd_delete(client, args)
    elif args.command == "clear":
        cmd_clear(client, args)
    else:
        interactive_menu(client)


if __name__ == "__main__":
    main()
