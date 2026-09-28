# Local Ollama Harness API — Documentación del Proyecto

## 📌 Descripción del Proyecto
Este proyecto implementa un **Harness (Andamiaje)** local para modelos de lenguaje (LLM). Dado que los LLM son amnésicos por naturaleza, este Harness actúa como un middleware que intercepta las peticiones, gestiona la persistencia de datos y reconstruye la memoria de la conversación antes de invocar al modelo.

Toda la infraestructura de la API corre aislada dentro de un contenedor **Docker**, mientras que las inferencias del modelo las realiza **Ollama** en la máquina host (aprovechando la aceleración por GPU local).

---

## 🛠️ Tecnologías Utilizadas

* **Python 3.11 & FastAPI:** Framework asíncrono de alto rendimiento para exponer la API REST.
* **SQLite:** Base de datos relacional ligera sin servidor que almacena el historial de conversaciones de forma persistente en disco.
* **Docker & Docker Compose:** Entorno de despliegue para la API y la base de datos, garantizando portabilidad sin ensuciar el sistema base.
* **Ollama (`qwen2.5-coder:7b`):** Motor de inferencia local para ejecutar el LLM en la GPU del sistema.
* **OpenAI Python Client:** Librería utilizada para comunicarse con Ollama aprovechando su compatibilidad con la API de OpenAI.

---

## 📁 Estructura del Proyecto y Componentes

```text
harness-ollama-local/
├── app/
│   ├── __init__.py      # Inicializador del paquete Python.
│   ├── database.py      # Gestor de persistencia SQLite (guardar/leer historial por sesión).
│   ├── harness.py       # El corazón del Harness (reconstruye contexto y consulta al LLM).
│   └── main.py          # Definición de endpoints FastAPI y validaciones Pydantic.
├── data/                # Carpeta montada en volumen Docker donde reside la BD (memory.db).
├── Dockerfile           # Configuración de la imagen del contenedor de la API.
├── docker-compose.yml   # Orquestación del contenedor y puente de red con el Host.
├── requirements.txt     # Dependencias de Python.
└── MEMORY.md            # Memoria y documentación técnica del proyecto.
└── README.md            # Instrucciones para levantar el proyecto


