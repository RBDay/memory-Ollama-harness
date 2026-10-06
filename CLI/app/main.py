import sys
import argparse
from typing import Optional
from app.api_client import APIClient
from app.ui import (
    print_banner,
    print_success,
    print_error,
    print_info,
    print_sessions_table,
    print_session_header,
    print_history_banner,
    render_message,
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
    """Crea una nueva sesión con su propio contexto inicial."""
    title = args.title
    system_prompt = args.prompt
    model = args.model
    session_id = args.id

    # Modo interactivo si falta información
    if not title:
        if RICH_AVAILABLE:
            title = Prompt.ask("[bold]Título de la sesión[/bold]", default="Nueva Sesión")
        else:
            title = input("Título de la sesión [Nueva Sesión]: ") or "Nueva Sesión"

    if system_prompt is None:
        if RICH_AVAILABLE:
            system_prompt = Prompt.ask(
                "[bold]Contexto inicial / System Prompt (opcional)[/bold]", default=""
            )
        else:
            system_prompt = input("Contexto inicial / System Prompt (opcional): ")

    if not system_prompt.strip():
        system_prompt = None

    if not model:
        default_model = "qwen2.5-coder:7b"
        if RICH_AVAILABLE:
            model = Prompt.ask(
                "[bold]Modelo de Ollama[/bold]", default=default_model
            ).strip()
        else:
            model = input(f"Modelo de Ollama [{default_model}]: ").strip() or default_model

    try:
        res = client.create_session(
            title=title,
            system_prompt=system_prompt,
            model=model,
            session_id=session_id,
        )
        print_success(f"Sesión creada exitosamente: [bold cyan]{res['session_id']}[/bold cyan]")
        print_info(f"Modelo configurado: [bold green]{res.get('model')}[/bold green]")
        if res.get("system_prompt"):
            print_info(f"Contexto configurado: \"{res['system_prompt']}\"")

        # Preguntar si iniciar chat de inmediato
        start_now = False
        if RICH_AVAILABLE:
            start_now = Confirm.ask("¿Deseas entrar al chat con esta sesión ahora?", default=True)
        else:
            ans = input("¿Deseas entrar al chat ahora? (S/n): ").strip().lower()
            start_now = ans in ("", "s", "si", "y", "yes")

        if start_now:
            run_chat(client, res["session_id"])

    except Exception as e:
        print_error(f"Error creando la sesión: {e}")


def cmd_delete(client: APIClient, args):
    """Elimina una sesión y vacía su memoria en MongoDB."""
    session_id = args.session_id
    if not session_id:
        print_error("Debes especificar el ID de la sesión a eliminar.")
        return

    # Confirmación
    confirm = False
    if RICH_AVAILABLE:
        confirm = Confirm.ask(
            f"¿Estás seguro de que deseas eliminar la sesión '[cyan]{session_id}[/cyan]' y toda su memoria?",
            default=False,
        )
    else:
        ans = input(f"¿Eliminar sesión '{session_id}' y toda su memoria? (s/N): ").strip().lower()
        confirm = ans in ("s", "si", "y", "yes")

    if not confirm:
        print_info("Operación cancelada.")
        return

    try:
        res = client.delete_session(session_id)
        print_success(
            f"Sesión '{session_id}' eliminada ({res.get('deleted_messages_count', 0)} mensajes borrados)."
        )
    except Exception as e:
        print_error(f"Error eliminando la sesión: {e}")


def cmd_clear(client: APIClient, args):
    """Vacía la memoria de una sesión manteniendo la sesión activa."""
    session_id = args.session_id
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
    # 1. Obtener detalles de la sesión
    try:
        session = client.get_session(session_id)
    except Exception as e:
        print_error(f"No se pudo cargar la sesión '{session_id}': {e}")
        return

    print_session_header(session)

    # 2. Cargar hasta los últimos 50 mensajes para dar contexto al usuario humano
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
                )
        else:
            print_info("La memoria de esta sesión está vacía. Inicia la conversación a continuación.")
    except Exception as e:
        print_error(f"No se pudo recuperar el historial previo: {e}")

    if RICH_AVAILABLE:
        console.print("[dim]Comandos especiales: /clear (vaciar memoria) | /context (ver contexto) | /exit (salir)[/dim]\n")
    else:
        print("Comandos: /clear, /context, /exit\n")

    # 3. Bucle interactivo de chat
    while True:
        try:
            if RICH_AVAILABLE:
                user_input = Prompt.ask("[bold cyan]Tú[/bold cyan]").strip()
            else:
                user_input = input("Tú > ").strip()

            if not user_input:
                continue

            # Comandos dentro del chat
            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                print_info("Saliendo de la sesión de chat...")
                break

            if user_input.lower() == "/context":
                ctx = session.get("system_prompt") or "Sin contexto inicial asignado."
                print_info(f"System Prompt / Contexto: {ctx}")
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
                print_info("Comandos disponibles:")
                print("  /clear   - Vacía la memoria de la conversación")
                print("  /context - Muestra el contexto / system_prompt de la sesión")
                print("  /exit    - Vuelve al menú o sale de la CLI")
                continue

            # Enviar mensaje a través del Harness
            if RICH_AVAILABLE:
                with console.status(f"[bold green]Pensando ({session.get('model', 'ollama')})...[/bold green]", spinner="dots"):
                    chat_res = client.chat(session_id, user_input)
            else:
                print("Pensando...")
                chat_res = client.chat(session_id, user_input)

            assistant_msg = chat_res.get("assistant_message", {})
            render_message(
                role="assistant",
                content=assistant_msg.get("content", ""),
                model=chat_res.get("model"),
            )

        except (KeyboardInterrupt, EOFError):
            print("\n")
            print_info("Chat interrumpido por el usuario. Saliendo...")
            break
        except Exception as e:
            print_error(f"Error durante la inferencia: {e}")


def cmd_chat(client: APIClient, args):
    """Inicia el chat interactivo para la sesión indicada o permite seleccionarla."""
    session_id = args.session_id
    if not session_id:
        # Listar y pedir selección
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

    # Comprobación inicial de salud
    try:
        health = client.check_health()
        ollama_status = health.get("ollama", {}).get("status", "unknown")
        mongo_status = health.get("mongo", "unknown")
        if RICH_AVAILABLE:
            console.print(
                f"[dim]MongoDB: [green]{mongo_status}[/] | Ollama: [green]{ollama_status}[/] | Backend: [cyan]{client.base_url}[/][/dim]\n"
            )
    except Exception:
        print_error(
            f"No se pudo contactar con la API en '{client.base_url}'. Asegúrate de que el contenedor de Docker esté activo."
        )

    while True:
        try:
            if RICH_AVAILABLE:
                console.print("[bold cyan]Opciones:[/bold cyan]")
                print("  [1] Listar sesiones")
                print("  [2] Iniciar chat con una sesión")
                print("  [3] Crear una nueva sesión")
                print("  [4] Vaciar memoria de una sesión")
                print("  [5] Eliminar una sesión")
                print("  [6] Salir")
                choice = Prompt.ask("\nSelecciona una opción", choices=["1", "2", "3", "4", "5", "6"], default="1")
            else:
                print("\nOpciones: [1] Listar  [2] Chat  [3] Crear  [4] Vaciar  [5] Eliminar  [6] Salir")
                choice = input("Opción: ").strip()

            if choice == "1":
                cmd_list(client, None)
            elif choice == "2":
                class DummyArgs:
                    session_id = None
                cmd_chat(client, DummyArgs())
            elif choice == "3":
                class DummyArgs:
                    title = None
                    prompt = None
                    model = None
                    id = None
                cmd_create(client, DummyArgs())
            elif choice == "4":
                if RICH_AVAILABLE:
                    s_id = Prompt.ask("ID de la sesión a vaciar")
                else:
                    s_id = input("ID de la sesión: ")
                class DummyArgs:
                    session_id = s_id
                cmd_clear(client, DummyArgs())
            elif choice == "5":
                if RICH_AVAILABLE:
                    s_id = Prompt.ask("ID de la sesión a eliminar")
                else:
                    s_id = input("ID de la sesión: ")
                class DummyArgs:
                    session_id = s_id
                cmd_delete(client, DummyArgs())
            elif choice == "6":
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
        description="CLI para gestionar sesiones y chatear con Ollama manteniendo memoria en MongoDB.",
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

    # chat
    p_chat = subparsers.add_parser("chat", help="Entrar al chat en tiempo real de una sesión")
    p_chat.add_argument("session_id", nargs="?", default=None, help="ID de la sesión a cargar")

    # delete
    p_del = subparsers.add_parser("delete", help="Eliminar una sesión y su memoria")
    p_del.add_argument("session_id", help="ID de la sesión a eliminar")

    # clear
    p_clear = subparsers.add_parser("clear", help="Vaciar la memoria de una sesión")
    p_clear.add_argument("session_id", help="ID de la sesión a vaciar")

    args = parser.parse_args()
    client = APIClient(base_url=args.api_url)

    if args.command == "list":
        cmd_list(client, args)
    elif args.command == "create":
        cmd_create(client, args)
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
