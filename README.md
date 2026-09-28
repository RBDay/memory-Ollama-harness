# 🚀 Local Ollama Harness API

Este repositorio contiene una API REST desarrollada con **FastAPI** que implementa un **Harness (Andamiaje)** local para modelos de lenguaje (LLM). Su propósito principal es gestionar la memoria de conversación y el contexto de forma persistente utilizando una base de datos SQLite ligera, desacoplando el entorno de la API (Docker) del motor de inferencia (Ollama en el Host).

---

## 🛠️ Cómo Levantar el Proyecto

Sigue estos pasos para preparar el entorno e iniciar la aplicación.

### 1.1. Instalar Ollama y descargar el modelo `qwen2.5`

Dado que la inferencia del modelo se ejecuta en la máquina host para aprovechar la aceleración por GPU, primero debes instalar Ollama en tu sistema Linux y descargar el modelo deseado.

1. **Instalar Ollama en Linux:**
   Abre una terminal e ejecuta el script oficial de instalación:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. **Verificar que el servicio de Ollama está activo:**
   ```bash
   systemctl status ollama
   ```
   *(Si no está activo, puedes iniciarlo con `ollama serve` o `sudo systemctl start ollama`).*

3. **Descargar el modelo `qwen2.5`:**
   Ejecuta el siguiente comando para descargar la variante de 7B parámetros:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```
   *(También puedes usar la versión general de `qwen2.5:7b` según tus necesidades).*

---

### 1.2. Levantar los contenedores con Docker

Una vez que Ollama está activo y con el modelo descargado en el host, puedes levantar la API aislada en Docker.

1. **Clonar el repositorio y situarte en la carpeta raíz:**
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd harness-ollama-local
   ```

2. **Construir e iniciar los contenedores con Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

3. **Verificar el estado del servicio:**
   La API estará disponible en `http://localhost:8000`. Puedes acceder a la documentación interactiva de Swagger UI en:
   👉 **`http://localhost:8000/docs`**

---

## 📌 ¿Qué hace este Proyecto?

Los Modelos de Lenguaje (LLM) son **amnésicos por naturaleza**: no recuerdan interacciones pasadas a menos que se les vuelva a enviar todo el historial en cada petición. 

Este **Harness** actúa como un middleware inteligente entre el cliente y el modelo de lenguaje:

1. **Intercepta las peticiones:** Recibe el mensaje del usuario junto a un identificador de sesión (`session_id`).
2. **Reconstruye el contexto:** Consulta la base de datos **SQLite** para recuperar los mensajes anteriores asociados a esa sesión y reensambla la conversación completa.
3. **Consulta al LLM:** Envía la conversación estructurada a **Ollama** utilizando el cliente oficial compatible con la API de OpenAI.
4. **Persiste la memoria:** Al recibir la respuesta del LLM, guarda tanto el mensaje del usuario como la respuesta del asistente en la base de datos para futuras interacciones.

---

## 🛠️ Tecnologías Utilizadas

* **Python 3.11 & FastAPI:** Framework asíncrono para exponer la API REST.
* **SQLite:** Base de datos relacional sin servidor que almacena de forma persistente el historial de conversación.
* **Docker & Docker Compose:** Entorno de despliegue contenerizado para la API.
* **Ollama (`qwen2.5-coder:7b`):** Motor de inferencia local ejecutado directamente en la GPU del host.
* **OpenAI Python SDK:** Cliente para comunicación estandarizada con Ollama.

---

## 📁 Estructura del Proyecto

```text
harness-ollama-local/
├── app/
│   ├── __init__.py      # Inicializador del paquete Python.
│   ├── database.py      # Gestor de persistencia SQLite (guardar/leer historial por sesión).
│   ├── harness.py       # Lógica principal del Harness (reconstrucción de contexto e inferencia).
│   └── main.py          # Definición de endpoints FastAPI y esquemas Pydantic.
├── data/                # Volumen montado en Docker donde reside la BD (memory.db).
├── Dockerfile           # Configuración de la imagen Docker de la API.
├── docker-compose.yml   # Orquestación del contenedor y red puente hacia el Host.
├── requirements.txt     # Dependencias de Python.
├── MEMORY.md            # Memoria técnica detallada del proyecto.
└── README.md            # Guía rápida de instalación y uso.
```

---

## 📄 Documentación Técnica Completa (Memoria)

Para obtener un desglose detallado de las decisiones de arquitectura, benchmarks, flujo de datos interno y justificaciones técnicas del proyecto, consulta el archivo de documentación técnica adjunto:

👉 **[MEMORY.md](./MEMORY.md)**