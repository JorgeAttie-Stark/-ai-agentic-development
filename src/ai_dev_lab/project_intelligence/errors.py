"""Erro de tool compartilhado entre `protocol.py` e os módulos de tool.

Módulo isolado para evitar import circular: `protocol.py` precisa de
`ToolError` para traduzir falhas esperadas em resposta JSON-RPC, e os módulos
de tool (`exploration.py`, ...) precisam da mesma classe para levantá-las.
"""


class ToolError(Exception):
    """Falha esperada de execução de uma tool — mensagem já é segura para o cliente."""
