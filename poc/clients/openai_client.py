"""
Client OpenAI pour le POC Lecture Stratifiee

Client pour comparer les résultats avec GPT-4o vs Qwen.
"""

import os
import json
import re
from typing import Optional, Dict, Any


class OpenAIClient:
    """
    Client pour OpenAI GPT-4o.
    Même interface que VLLMClient pour comparaison.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        max_tokens: int = 4096,
        temperature: float = 0.1
    ):
        """
        Args:
            model: Modèle OpenAI (gpt-4o, gpt-4-turbo, etc.)
            api_key: Clé API OpenAI (ou env OPENAI_API_KEY)
            timeout: Timeout en secondes
            max_tokens: Nombre max de tokens en sortie
            temperature: Temperature de génération
        """
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY non configurée")

        # Import OpenAI
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        except ImportError:
            raise ImportError("openai package non installé. pip install openai")

    def health_check(self) -> bool:
        """Vérifie que l'API est accessible"""
        try:
            # Simple test avec un prompt minimal
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5
            )
            return True
        except Exception as e:
            print(f"OpenAI health check failed: {e}")
            return False

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Génère une réponse via OpenAI.

        Args:
            system_prompt: Prompt système
            user_prompt: Prompt utilisateur
            max_tokens: Override max tokens
            temperature: Override temperature

        Returns:
            Texte généré par le LLM
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature or self.temperature
            )
            return response.choices[0].message.content

        except Exception as e:
            raise RuntimeError(f"OpenAI error: {e}")

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Génère une réponse JSON via OpenAI.

        Returns:
            Dict parsé depuis la réponse JSON
        """
        response = self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens
        )

        # Extraire le JSON du bloc de code si présent
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Réponse non-JSON: {e}\nRéponse: {response[:500]}")
