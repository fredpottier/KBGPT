"""
Client vLLM pour le POC Lecture Stratifiee

Client simple pour communiquer avec un serveur vLLM.
"""

import json
import httpx
from typing import Optional, Dict, Any


class VLLMClient:
    """
    Client pour serveur vLLM.
    Compatible avec l'API OpenAI.
    """

    def __init__(
        self,
        base_url: str = "http://3.123.41.100:8000",
        model: str = "/model",  # Nom du modele expose par vLLM
        timeout: float = 300.0,  # 5 minutes pour grands prompts
        max_tokens: int = 2048,  # Reduit pour contexte 8k
        temperature: float = 0.1
    ):
        """
        Args:
            base_url: URL du serveur vLLM
            model: Nom du modele (souvent le chemin du volume Docker)
            timeout: Timeout en secondes
            max_tokens: Nombre max de tokens en sortie
            temperature: Temperature de generation
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    def health_check(self) -> bool:
        """Verifie que le serveur est accessible"""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Genere une reponse via vLLM.

        Args:
            system_prompt: Prompt systeme
            user_prompt: Prompt utilisateur
            max_tokens: Override max tokens
            temperature: Override temperature

        Returns:
            Texte genere par le LLM
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "stream": False
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()

                data = response.json()
                return data["choices"][0]["message"]["content"]

        except httpx.TimeoutException:
            raise TimeoutError(f"vLLM timeout apres {self.timeout}s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"vLLM HTTP error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"vLLM error: {e}")

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Genere une reponse JSON via vLLM.

        Returns:
            Dict parse depuis la reponse JSON
        """
        response = self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens
        )

        # Extraire le JSON du bloc de code si present
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Essayer de parser directement
            json_str = response

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Reponse non-JSON: {e}\nReponse: {response[:500]}")
