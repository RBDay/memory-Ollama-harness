# Estructura del Proyecto: Memory_Ollama

El proyecto está dividido en dos componentes principales:
1. **API (Back-end)**
2. **CLI (Interfaz de Línea de Comandos)**

---

## 1. API (Back-end)

La parte de la API está ubicada en el directorio `Memory_Ollama/API/app`, donde reside la lógica principal del proyecto.

### 1.1. Directorio Principal (`Memory_Ollama/API/app`)
Contiene los siguientes archivos y subdirectorios clave:
* **`models.py`**: Define los modelos de datos utilizados por el proyecto (`SchemaSession`, `Message`, etc.).
* **`base.py`**: Contiene la configuración de la base de datos, el motor de SQLAlchemy y la inicialización.
* **`db.py`**: Maneja la conexión a la base de datos y la creación de sesiones.
* **`endpoints.py`**: Define los endpoints de la API REST.
* **`handlers.py`**: Contiene las funciones `main` y `handler` para gestionar las solicitudes de la API.
* **`schemas.py`**: Define los esquemas de validación de datos para los modelos ORM.
* **`session.py`**: Maneja la lógica de creación y recuperación de sesiones persistentes.
* **`user_management.py`**: Permite la gestión de usuarios y sus sesiones asociadas.

### 1.2. Archivo Principal (`Memory_Ollama/API/app/main.py`)
Punto de entrada de la API, donde se configuran las rutas principales y la inicialización de la aplicación.

```python
@app.get("/list")
async def list_sessions():
    """Lista todas las sesiones disponibles."""
    sessions = await db.session.query(SchemaSession).all()
    return sessions

@app.post("/create")
async def create_session(request: SchemaSessionCreate):
    """Crea una nueva sesión."""
    new_session = SchemaSession(**request.dict())
    await db.session.add(new_session)
    await db.session.commit()
    return new_session

@app.post("/chat")
async def chat(request: SchemaMessageCreate):
    """Realiza una conversación con el modelo de lenguaje."""
    session = await db.session.query(SchemaSession).get(request.session_id)
    response = await handler.chat(session, request.text)
    return {"response": response}
```

### 1.3. Manejo del Modelo (`Memory_Ollama/API/app/harness.py`)
Gestiona el flujo de chat, incorporando el historial de mensajes en la conversación y persistiendo las respuestas en la base de datos.

```python
async def chat(session, text):
    messages = await db.session.query(Message).filter(Message.session_id == session.id).all()
    full_system_content = ""
    for message in messages:
        full_system_content += f"{message.role}: {message.text}\n\n"
        
    instructions = "\n\n[INSTRUCCIONES DE CONTEXTO]:\nTienes acceso directo a la siguiente estructura de archivos..."
    
    if full_system_content:
        full_system_content += instructions
    else:
        full_system_content = f"Eres un asistente analítico experto...{instructions}"
        
    response = await ollama_client.generate(full_system_content, text)
    new_message = Message(session_id=session.id, role="assistant", text=response)
    await db.session.add(new_message)
    await db.session.commit()
    return response
```

---

## 2. CLI (Interfaz de Línea de Comandos)

La herramienta de línea de comandos está ubicada en el directorio `Memory_Ollama/CLI/app`.

### 2.1. Directorio Principal (`Memory_Ollama/CLI/app`)
* **`main.py`**: Define los comandos y la lógica de gestión de sesiones desde la terminal.
* **`utils.py`**: Contiene funciones utilitarias, como la autenticación y la gestión de la consola.

### 2.2. Archivo Principal (`Memory_Ollama/CLI/app/main.py`)
Gestiona la ejecución de los comandos proporcionados por el usuario.

```python
@app.command()
def list():
    """Lista todas las sesiones disponibles."""
    sessions = await db.session.query(SchemaSession).all()
    return sessions

@app.command()
def create(session_id: str, title: str, model: str):
    """Crea una nueva sesión."""
    session = SchemaSession(session_id=session_id, title=title, model=model)
    await db.session.add(session)
    await db.session.commit()
    return session

@app.command()
def chat(session_id: str, text: str):
    """Realiza una conversación con el modelo de lenguaje."""
    session = await db.session.query(SchemaSession).get(session_id)
    response = await handler.chat(session, text)
    return response
```

### 2.3. Handlers (`Memory_Ollama/CLI/app/handlers.py`)
Contiene las funciones que manejan la lógica de negocio subyacente para los comandos de la CLI.

```python
async def chat(session, text):
    messages = await db.session.query(Message).filter(Message.session_id == session.id).all()
    full_system_content = ""
    for message in messages:
        full_system_content += f"{message.role}: {message.text}\n\n"
        
    instructions = "\n\n[INSTRUCCIONES DE CONTEXTO]:\nTienes acceso directo..."
    
    if full_system_content:
        full_system_content += instructions
    else:
        full_system_content = f"Eres un asistente analítico experto...{instructions}"
        
    response = await ollama_client.generate(full_system_content, text)
    new_message = Message(session_id=session.id, role="assistant", text=response)
    await db.session.add(new_message)
    await db.session.commit()
    return response
```

---

## Resumen del Proyecto

* **API**: Proporciona una interfaz RESTful para interactuar con el sistema, permitiendo la creación, consulta y gestión de sesiones.
* **CLI**: Ofrece una interfaz de línea de comandos para facilitar el uso desde el terminal.
* **Estructura de Directorios**:
  * `Memory_Ollama/API/app`: Lógica central del back-end.
  * `Memory_Ollama/CLI/app`: Lógica central de la interfaz de comandos.