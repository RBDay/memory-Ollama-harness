from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.box import ROUNDED, SIMPLE
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


def print_banner():
    if RICH_AVAILABLE:
        title = Text("🧠 Ollama Local Chat Memory", style="bold cyan")
        subtitle = Text("Harness local con persistencia y contexto en MongoDB", style="dim white")
        console.print(Panel(Text.assemble(title, "\n", subtitle), border_style="cyan", box=ROUNDED))
    else:
        print("=" * 60)
        print("🧠 Ollama Local Chat Memory (FastAPI + MongoDB)")
        print("=" * 60)


def print_success(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold green]✔[/bold green] {message}")
    else:
        print(f"[OK] {message}")


def print_error(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold red]✘ Error:[/bold red] {message}")
    else:
        print(f"[ERROR] {message}")


def print_info(message: str):
    if RICH_AVAILABLE:
        console.print(f"[bold blue]ℹ[/bold blue] {message}")
    else:
        print(f"[INFO] {message}")


def print_sessions_table(sessions: List[Dict[str, Any]]):
    if not sessions:
        if RICH_AVAILABLE:
            console.print("[yellow]No hay sesiones registradas. Crea una con el comando 'create'.[/yellow]")
        else:
            print("No hay sesiones registradas.")
        return

    if RICH_AVAILABLE:
        table = Table(title="Sesiones de Conversación Disponibles", box=ROUNDED, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("ID de Sesión", style="cyan", no_wrap=True)
        table.add_column("Título", style="bold white")
        table.add_column("Modelo", style="green")
        table.add_column("Msgs", justify="right", style="yellow")
        table.add_column("Contexto Inicial (System Prompt)", style="dim", max_width=40)

        for i, s in enumerate(sessions, 1):
            prompt = s.get("system_prompt") or "-"
            if len(prompt) > 37:
                prompt = prompt[:37] + "..."
            table.add_row(
                str(i),
                s.get("session_id", ""),
                s.get("title", ""),
                s.get("model", ""),
                str(s.get("message_count", 0)),
                prompt,
            )
        console.print(table)
    else:
        print("\n--- SESIONES ---")
        for i, s in enumerate(sessions, 1):
            print(f"[{i}] ID: {s.get('session_id')} | Título: {s.get('title')} | Mensajes: {s.get('message_count', 0)}")


def print_session_header(session: Dict[str, Any]):
    session_id = session.get("session_id", "")
    title = session.get("title", "Sin título")
    model = session.get("model", "")
    system_prompt = session.get("system_prompt") or "Ninguno"
    msgs = session.get("message_count", 0)

    if RICH_AVAILABLE:
        content = (
            f"[bold]ID:[/] [cyan]{session_id}[/]\n"
            f"[bold]Título:[/] [white]{title}[/]\n"
            f"[bold]Modelo:[/] [green]{model}[/] | [bold]Mensajes en memoria:[/] [yellow]{msgs}[/]\n"
            f"[bold]Contexto inicial:[/] [dim]{system_prompt}[/]"
        )
        console.print(Panel(content, title="💬 Sesión Activa", border_style="green", box=ROUNDED))
    else:
        print(f"\n=== Chat: {title} ({session_id}) [Modelo: {model}] ===")
        print(f"Contexto: {system_prompt}\n")


def print_history_banner(displayed: int, total: int):
    if RICH_AVAILABLE:
        if total > displayed:
            console.print(
                f"[dim]── Mostrando los últimos {displayed} mensajes (de un total de {total} en memoria) ──[/dim]\n"
            )
        else:
            console.print(f"[dim]── Historial previo cargado ({displayed} mensajes) ──[/dim]\n")
    else:
        print(f"--- Historial previo ({displayed} mensajes) ---")


def render_message(
    role: str,
    content: str,
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    if RICH_AVAILABLE:
        if role == "user":
            console.print(f"[bold cyan]🧑 Tú:[/bold cyan] {content}\n")
        elif role == "assistant":
            header = f"[bold green]🤖 Ollama ({model or 'assistant'}):[/bold green]"
            console.print(header)
            console.print(Markdown(content))
            if metadata:
                v_chunks = metadata.get("vector_chunks_used", 0)
                v_sources = metadata.get("vector_sources", [])
                if v_chunks > 0 and v_sources:
                    sources_str = ", ".join(v_sources[:4])
                    if len(v_sources) > 4:
                        sources_str += f" (+{len(v_sources) - 4} más)"
                    console.print(f"\n[dim cyan]📚 Contexto vectorial LanceDB:[/] [dim]{sources_str} ({v_chunks} fragmentos)[/dim]")
            console.print()
        elif role == "system":
            console.print(f"[bold magenta]⚙ Sistema:[/bold magenta] [dim]{content}[/dim]\n")
    else:
        prefix = "Tú" if role == "user" else f"Ollama ({model or 'assistant'})"
        print(f"[{prefix}]: {content}")
        if metadata and metadata.get("vector_chunks_used", 0) > 0:
            sources_str = ", ".join(metadata.get("vector_sources", [])[:3])
            print(f"[Contexto vectorial LanceDB: {sources_str}]")
        print()


def format_size(size_bytes: int) -> str:
    """Formatea bytes a formato legible (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def print_files_table(session_id: str, files: List[Dict[str, Any]]):
    """Muestra la tabla de archivos indexados en LanceDB/MinIO para la sesión."""
    if not files:
        if RICH_AVAILABLE:
            console.print(f"[yellow]La sesión '[cyan]{session_id}[/cyan]' no tiene archivos indexados en LanceDB.[/yellow]")
        else:
            print(f"La sesión '{session_id}' no tiene archivos indexados.")
        return

    if RICH_AVAILABLE:
        table = Table(
            title=f"Archivos en Memoria Vectorial (Sesión: {session_id})",
            box=ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Ruta Relativa del Archivo", style="cyan")
        table.add_column("Tamaño", style="green", justify="right")
        table.add_column("Última Modificación", style="dim")

        for i, f in enumerate(files, 1):
            table.add_row(
                str(i),
                f.get("file_path", ""),
                format_size(f.get("size_bytes", 0)),
                f.get("last_modified", "-"),
            )
        console.print(table)
    else:
        print(f"\n--- ARCHIVOS EN MEMORIA VECTORIAL ({session_id}) ---")
        for i, f in enumerate(files, 1):
            print(f"[{i}] {f.get('file_path')} ({format_size(f.get('size_bytes', 0))})")


def print_vector_context_summary(vector_context: Dict[str, Any]):
    """Muestra un resumen de la ingesta e indexación en LanceDB."""
    files_count = vector_context.get("files_count", 0)
    chunks_count = vector_context.get("chunks_count", 0)
    model = vector_context.get("embedding_model", "-")
    dim = vector_context.get("vector_dimension", "-")
    files = vector_context.get("indexed_files", [])

    if RICH_AVAILABLE:
        content = (
            f"[bold green]✔ Memoria Vectorial LanceDB Generada[/bold green]\n\n"
            f"• [bold]Archivos indexados:[/] [cyan]{files_count}[/]\n"
            f"• [bold]Fragmentos (chunks):[/] [yellow]{chunks_count}[/]\n"
            f"• [bold]Modelo de embeddings:[/] [green]{model}[/] (dimensión: {dim})\n"
        )
        if files:
            preview = ", ".join(files[:5])
            if len(files) > 5:
                preview += f" ... (+{len(files) - 5} más)"
            content += f"• [bold]Archivos:[/] [dim]{preview}[/dim]"
        console.print(Panel(content, border_style="cyan", box=ROUNDED))
    else:
        print(f"[OK] Memoria Vectorial: {files_count} archivos, {chunks_count} chunks (modelo: {model})")

