from setuptools import setup, find_packages

setup(
    name="ollama-local-chat-memory",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.25.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "ollama_local_chat_memory=app.main:main",
        ],
    },
)
