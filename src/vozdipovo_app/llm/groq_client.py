#!src/vozdipovo_app/llm/groq_client.py
from __future__ import annotations

import json
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from vozdipovo_app.llm.http_transport import HTTPTransport
from vozdipovo_app.llm.models import ChatMessage, ChatRequest, ChatResponse


class GroqSettings(BaseSettings):
    """Configuração do cliente Groq.

    Attributes:
        groq_api_key: Chave da API da Groq.
        timeout_seconds: Timeout total por pedido, em segundos.
        base_url: URL base da API.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str
    timeout_seconds: int = 45
    base_url: str = "https://api.groq.com/openai/v1"


class GroqConfig(GroqSettings):
    """Compat layer para código antigo.

    O código legado espera um tipo GroqConfig com from_env.
    """

    @classmethod
    def from_env(cls) -> "GroqConfig":
        """Carrega configuração a partir do ambiente e env file.

        Returns:
            GroqConfig: Instância configurada.
        """
        return cls()


class GroqClient:
    """Cliente Groq compatível com rotas tipo OpenAI chat completions."""

    def __init__(self, settings: GroqSettings) -> None:
        """Inicializa o cliente.

        Args:
            settings: Configuração do cliente.
        """
        self._settings = settings

    @property
    def settings(self) -> GroqSettings:
        """Retorna a configuração atual.

        Returns:
            GroqSettings: Configuração.
        """
        return self._settings

    def chat(self, req: ChatRequest) -> ChatResponse:
        """Executa uma chamada de chat.

        Args:
            req: Pedido estruturado.

        Returns:
            ChatResponse: Resposta do modelo.
        """
        return self._chat_with_timeout(
            req=req, timeout_seconds=int(self.settings.timeout_seconds)
        )

    def chat_completions(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format_json: bool = False,
        timeout_seconds: int | None = None,
    ) -> str:
        """Compat layer para chamadas no estilo router legado.

        Args:
            model: Nome do modelo.
            messages: Lista de mensagens no formato dict.
            temperature: Temperatura.
            max_tokens: Máximo de tokens.
            response_format_json: Se True, pede output JSON.
            timeout_seconds: Timeout total opcional.

        Returns:
            str: Conteúdo textual da resposta.
        """
        chat_messages = [
            ChatMessage(role=m["role"], content=m["content"]) for m in messages
        ]
        response_format = {"type": "json_object"} if response_format_json else None
        req = ChatRequest(
            model=model,
            messages=chat_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        eff_timeout = (
            int(timeout_seconds)
            if timeout_seconds is not None
            else int(self.settings.timeout_seconds)
        )
        return self._chat_with_timeout(req=req, timeout_seconds=eff_timeout).text

    def _chat_with_timeout(
        self, *, req: ChatRequest, timeout_seconds: int
    ) -> ChatResponse:
        """Executa a chamada usando um timeout específico.

        Args:
            req: Pedido estruturado.
            timeout_seconds: Timeout total.

        Returns:
            ChatResponse: Resposta do modelo.
        """
        transport = HTTPTransport(timeout_seconds=timeout_seconds)

        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            f"Content{chr(45)}Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": req.temperature,
        }
        if req.max_tokens is not None:
            payload["max_tokens"] = int(req.max_tokens)
        if req.response_format is not None:
            payload["response_format"] = dict(req.response_format)

        resp = transport.post_json(
            url=f"{self.settings.base_url}/chat/completions",
            headers=headers,
            payload=payload,
            provider="groq",
            model=str(req.model or ""),
        )

        content = ""
        try:
            choice0 = (resp.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            content = str(msg.get("content") or "").strip()
        except Exception:
            content = ""

        return ChatResponse(raw=resp, text=content)

    @staticmethod
    def extract_json_object(text: str) -> dict[str, Any]:
        """Extrai um objeto JSON do texto.

        Args:
            text: Texto possivelmente contendo JSON.

        Returns:
            dict[str, Any]: Objeto JSON.

        Raises:
            ValueError: Se não for possível extrair JSON válido.
        """
        s = (text or "").strip()
        if not s:
            raise ValueError("Resposta vazia")

        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("JSON não encontrado")

        chunk = s[start : end + 1]
        obj = json.loads(chunk)
        if not isinstance(obj, dict):
            raise ValueError("JSON não é objeto")
        return obj


if __name__ == "__main__":
    cfg = GroqConfig.from_env()
    client = GroqClient(cfg)
    out = client.chat_completions(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": "Devolve um JSON com chave ok e valor true"}
        ],
        response_format_json=True,
        timeout_seconds=30,
    )
    print(out)
