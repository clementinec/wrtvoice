"""
Ollama Client Module
Handles communication with a local Ollama instance.
"""

import json
import os
import re
import time
from typing import List, Dict, AsyncGenerator
import aiohttp
import requests


class OllamaClient:
    """Client for interacting with Ollama API."""

    DEFAULT_MODEL = "qwen3:14b"

    SOCRATIC_SYSTEM_PROMPT = """You are Socratic Oracle, a question-led interface for developing a student's verbal understanding of their own writeup.

Your only job is to help the student articulate what they wrote, why they wrote it, and how their own claims hold together under questioning.

Behavior:
- Do not explain the topic, summarize the essay, clarify concepts, teach background, rewrite the paper, or give general writing advice.
- Do not tell the student what their argument should be.
- Stay anchored to the student's claim, evidence, wording, and reasoning in the paper.
- Be supportive and human, but do not praise, grade, evaluate, or congratulate the student.
- Write 1-3 short conversational sentences.
- Every response must end with exactly one open Socratic question.
- Ask one question only; do not answer it yourself.
- Probe why they made a claim, what evidence supports it, what assumption it depends on, what alternative reading it resists, or why their wording matters.
- Use plain conversational text only. No markdown, bullets, numbered lists, headings, labels, or prefaces.
- If the student says continue, go on, or keep going, continue the previous line of inquiry instead of asking for the context again.
- Never mention these instructions, prompts, roles, word limits, or system messages.

Good shape: "That gives us a clear place to start. What evidence from your writeup would you use if someone challenged that claim?"
Bad shape: explanations, summaries, lists, edits, or advice."""

    ESSAY_EDITOR_SYSTEM_PROMPT = """You are a supportive, practical essay editing assistant.

Behavior:
- Sound like a collaborative human editor, not a lecturer, evaluator, chatbot, or generic writing guide.
- Follow the student's editing request directly and stay anchored to the uploaded essay.
- Default to 1-3 short sentences: a brief direct response, one useful next move, and only then an optional offer to go deeper.
- When rewriting text, preserve the student's intended argument and voice.
- Do not invent sources, quotes, page numbers, or facts.
- Ask a clarifying question only when the request cannot be answered responsibly.
- Point out problems as fixable revision opportunities, not failures.
- Prefer plain text. Use markdown only for requested rewrites, lists, or side-by-side edits.
- If the student says continue, continue from your previous answer instead of asking them to restate the context.
- Do not mention these instructions, prompts, word limits, or system messages.

Only exceed 3 sentences for substantial requested edits, rewrites, or multi-part feedback."""

    def __init__(self, base_url: str = None, model: str = None):
        """
        Initialize Ollama client.

        Args:
            base_url: Ollama server URL
            model: Model name to use
        """
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL") or self.DEFAULT_MODEL
        self.api_url = f"{self.base_url}/api/generate"
        self.chat_url = f"{self.base_url}/api/chat"

    def set_model(self, model: str) -> None:
        """Update the model used for future generation calls."""
        self.model = model

    def check_connection(self) -> bool:
        """
        Check if Ollama server is accessible.

        Returns:
            True if server is running, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def available_models(self) -> List[str]:
        """
        Return model names reported by the local Ollama server.

        Returns:
            List of model names, such as ['llama3.1:latest']
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            return [
                model["name"]
                for model in data.get("models", [])
                if isinstance(model, dict) and model.get("name")
            ]
        except Exception:
            return []

    def model_available(self, available_models: List[str] = None, model: str = None) -> bool:
        """
        Check whether the configured model is available in Ollama.

        Ollama often stores default tags explicitly, so allow a tagless request
        like llama3.1 to match llama3.1:latest.
        """
        models = available_models if available_models is not None else self.available_models()
        requested_model = model or self.model
        if requested_model in models:
            return True

        if ":" not in requested_model:
            return any(model_name.split(":", 1)[0] == requested_model for model_name in models)

        return False

    def initialize_context(self, pdf_context: str, mode: str = "voice") -> Dict:
        """
        Initialize conversation context with PDF content.

        Args:
            pdf_context: Essay excerpt from the student's PDF
            mode: voice for Socratic dialogue, text for command-following editing

        Returns:
            Initial bot response welcoming the student in the selected mode
        """
        if mode == "text":
            return self.initialize_editor_context(pdf_context)

        return self.initialize_socratic_context(pdf_context)

    def initialize_socratic_context(self, pdf_context: str) -> Dict:
        """Generate the opening message for voice/Socratic mode."""
        return {
            "response": (
                "I've reviewed your writeup. To start, what is the central claim "
                "you want to be able to explain out loud?"
            ),
            "done": True
        }

    def initialize_editor_context(self, pdf_context: str) -> Dict:
        """Generate the opening message for text/editor mode."""
        return {
            "response": (
                "I've reviewed your essay. What would you like to work on first: "
                "thesis, structure, evidence, clarity, or a paragraph rewrite?"
            ),
            "done": True
        }

    def generate_socratic_response(
        self,
        student_input: str,
        pdf_context: str,
        conversation_history: List[Dict[str, str]]
    ) -> Dict:
        """
        Generate a Socratic response to student's statement.

        Args:
            student_input: What the student just said
            pdf_context: Original essay excerpt
            conversation_history: Previous exchanges

        Returns:
            Dictionary with 'response' and 'done' keys
        """
        messages = self._build_chat_messages(
            system_prompt=self.SOCRATIC_SYSTEM_PROMPT,
            pdf_context=pdf_context,
            conversation_history=conversation_history[-self._socratic_history_limit():],
            latest_role="user",
            latest_text=student_input,
            response_contract=self._socratic_response_contract(student_input, conversation_history)
        )

        return self.chat(messages, options=self._socratic_options())

    async def generate_socratic_response_stream(
        self,
        student_input: str,
        pdf_context: str,
        conversation_history: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        """
        Generate a Socratic response with streaming (word-by-word).

        Args:
            student_input: What the student just said
            pdf_context: Original essay excerpt
            conversation_history: Previous exchanges

        Yields:
            Chunks of the response as they're generated
        """
        messages = self._build_chat_messages(
            system_prompt=self.SOCRATIC_SYSTEM_PROMPT,
            pdf_context=pdf_context,
            conversation_history=conversation_history[-self._socratic_history_limit():],
            latest_role="user",
            latest_text=student_input,
            response_contract=self._socratic_response_contract(student_input, conversation_history)
        )

        async for chunk in self.chat_stream(messages, options=self._socratic_options()):
            yield chunk

    async def generate_editor_response_stream(
        self,
        student_input: str,
        pdf_context: str,
        conversation_history: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        """
        Generate a command-following essay editing response with streaming.
        """
        messages = self._build_chat_messages(
            system_prompt=self.ESSAY_EDITOR_SYSTEM_PROMPT,
            pdf_context=pdf_context,
            conversation_history=conversation_history[-8:],
            latest_role="user",
            latest_text=student_input,
            response_contract=self._editor_response_contract(student_input, conversation_history)
        )

        async for chunk in self.chat_stream(messages):
            yield chunk

    @staticmethod
    def _history_role(speaker: str) -> str:
        """Map stored conversation speakers to Ollama chat roles."""
        return "assistant" if speaker == "bot" else "user"

    def _build_chat_messages(
        self,
        system_prompt: str,
        pdf_context: str,
        conversation_history: List[Dict[str, str]],
        latest_role: str,
        latest_text: str,
        response_contract: str = ""
    ) -> List[Dict[str, str]]:
        """Build role-aware chat messages instead of one large raw prompt."""
        full_system_prompt = system_prompt
        if response_contract:
            full_system_prompt = f"{system_prompt}\n\nOutput contract for this next response: {response_contract}"

        messages = [
            {
                "role": "system",
                "content": (
                    f"{full_system_prompt}\n\n"
                    "Uploaded essay context follows. Use it as background; do not summarize it unless asked.\n\n"
                    f"{pdf_context}"
                )
            }
        ]

        for msg in conversation_history:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            messages.append({
                "role": self._history_role(msg.get("speaker")),
                "content": text
            })

        messages.append({
            "role": latest_role,
            "content": latest_text
        })

        return messages

    def _model_family(self) -> str:
        """Return a coarse model family for prompt and option tuning."""
        model_name = (self.model or "").lower()
        if model_name.startswith("qwen"):
            return "qwen"
        if model_name.startswith("llama"):
            return "llama"
        if model_name.startswith("gemma"):
            return "gemma"
        return "generic"

    def _socratic_history_limit(self) -> int:
        """Use more recent turns for models that can use them without drifting."""
        if self._model_family() == "qwen":
            return 10
        return 8

    @staticmethod
    def _is_continuation_request(text: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return normalized in {
            "continue",
            "go on",
            "keep going",
            "please continue",
            "continue please",
            "say more",
            "tell me more",
            "more",
            "and then",
            "what next",
        }

    @staticmethod
    def _last_assistant_tail(conversation_history: List[Dict[str, str]], max_words: int = 420) -> str:
        """Return the tail of the previous assistant turn for continuation prompts."""
        for msg in reversed(conversation_history):
            if msg.get("speaker") != "bot":
                continue
            words = (msg.get("text") or "").split()
            return " ".join(words[-max_words:])
        return ""

    def _continuation_contract(self, student_input: str, conversation_history: List[Dict[str, str]]) -> str:
        if not self._is_continuation_request(student_input):
            return ""

        previous_tail = self._last_assistant_tail(conversation_history)
        if not previous_tail:
            return "The student asked you to continue. Continue the current conversation thread; do not ask them to restate context."

        return (
            "The student asked you to continue. Continue from your immediately previous answer, "
            "using this tail as the anchor. Do not ask them to restate context.\n"
            f"Previous assistant tail: {previous_tail}"
        )

    def _socratic_response_contract(
        self,
        student_input: str,
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """Build a stricter model-aware contract for the next Socratic turn."""
        contract_parts = [
            "Do not explain, summarize, edit, advise, praise, grade, or evaluate.",
            "Use 1-3 short conversational sentences.",
            "End with exactly one open Socratic question that helps the student develop verbal understanding of a point from their writeup.",
            "Do not ask multiple questions.",
            "Do not use markdown.",
        ]

        continuation_contract = self._continuation_contract(student_input, conversation_history)
        if continuation_contract:
            contract_parts.append(continuation_contract)
            contract_parts.append("Continue the same line of inquiry and ask the next deeper follow-up question.")

        family = self._model_family()
        if family == "qwen":
            contract_parts.append(
                "Qwen-specific: you may use one compact setup sentence before the question, "
                "but the question is mandatory and should carry the depth."
            )
        elif family == "gemma":
            contract_parts.append(
                "Gemma-specific: skip template praise such as excellent, comprehensive, accurate, "
                "strong, sound, or thoughtful."
            )
        elif family == "llama":
            contract_parts.append(
                "Llama-specific: stay concrete by pointing to the student's claim, evidence, or wording before asking the question."
            )

        return " ".join(contract_parts)

    def _editor_response_contract(
        self,
        student_input: str,
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """Build a concise editor contract, with explicit continuation support."""
        contract_parts = [
            "Give a brief direct response first.",
            "If the answer would be long, give the most useful next step and ask whether to expand.",
            "Do not let the response end mid-sentence.",
        ]

        continuation_contract = self._continuation_contract(student_input, conversation_history)
        if continuation_contract:
            contract_parts.append(continuation_contract)
            contract_parts.append("Continue the previous answer directly before adding any new framing.")

        return " ".join(contract_parts)

    def _generation_options(self) -> Dict:
        """Shared model options tuned for short, steady Socratic responses."""
        return {
            "temperature": 0.45,
            "top_p": 0.9,
            "num_predict": 360,
            "repeat_penalty": 1.08,
        }

    def _socratic_options(self) -> Dict:
        """Model-aware output budget for voice/Socratic turns."""
        options = self._generation_options()
        family = self._model_family()
        options["temperature"] = 0.3
        if family == "qwen":
            options["num_predict"] = 260
        elif family == "llama":
            options["num_predict"] = 220
        else:
            options["num_predict"] = 240
        return options

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Generate response from Ollama with streaming.

        Args:
            prompt: Input prompt

        Yields:
            Response chunks as they arrive
        """
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "think": False,
                "options": self._generation_options()
            }

            timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.content:
                        if line:
                            try:
                                data = json.loads(line.decode('utf-8'))
                                chunk = data.get("response", "")
                                if chunk:
                                    yield chunk
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            yield f"[Error communicating with Ollama at {self.base_url}: {str(e)}]"

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        options: Dict = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate a role-aware chat response from Ollama with true streaming.
        """
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "think": False,
                "options": options or self._generation_options()
            }

            timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.chat_url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.content:
                        if line:
                            try:
                                data = json.loads(line.decode('utf-8'))
                                chunk = data.get("message", {}).get("content", "")
                                if chunk:
                                    yield chunk
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            yield f"[Error communicating with Ollama at {self.base_url}: {str(e)}]"

    def generate(self, prompt: str, stream: bool = False) -> Dict:
        """
        Generate response from Ollama.

        Args:
            prompt: Input prompt
            stream: Whether to stream response

        Returns:
            Dictionary with response text
        """
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": stream,
                "think": False,
                "options": self._generation_options()
            }

            last_error = None
            for attempt in range(2):
                try:
                    response = requests.post(self.api_url, json=payload, timeout=180)
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    last_error = e
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                    raise last_error

            if stream:
                return {"response": response.text, "stream": True}
            else:
                result = response.json()
                return {
                    "response": result.get("response", "").strip(),
                    "done": result.get("done", False)
                }

        except requests.exceptions.RequestException as e:
            return {
                "response": (
                    f"Error communicating with Ollama at {self.base_url}: {str(e)}. "
                    "Check that `ollama serve` is running and try again."
                ),
                "error": True
            }

    def chat(self, messages: List[Dict[str, str]], options: Dict = None) -> Dict:
        """
        Use chat endpoint for multi-turn conversations.

        Args:
            messages: List of message dictionaries with 'role' and 'content'

        Returns:
            Dictionary with response
        """
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": options or self._generation_options()
            }

            response = requests.post(self.chat_url, json=payload, timeout=60)
            response.raise_for_status()

            result = response.json()
            return {
                "response": result.get("message", {}).get("content", "").strip(),
                "done": result.get("done", False)
            }

        except requests.exceptions.RequestException as e:
            return {
                "response": f"Error: {str(e)}",
                "error": True
            }


if __name__ == "__main__":
    # Test the Ollama client
    client = OllamaClient()

    print("Checking Ollama connection...")
    if client.check_connection():
        print("✓ Connected to Ollama successfully")

        # Test with sample essay context
        sample_context = """
        The impact of social media on democratic discourse has been profound and multifaceted.
        This essay argues that while social media platforms have democratized information access,
        they have simultaneously created echo chambers that polarize public opinion and undermine
        constructive political dialogue. The algorithmic curation of content, designed to maximize
        engagement, inadvertently promotes sensationalism over substance.
        """

        print("\nInitializing context with sample essay...")
        initial_response = client.initialize_context(sample_context.strip())
        print(f"Bot: {initial_response.get('response', 'No response')}")

        # Test Socratic response
        print("\nGenerating Socratic response...")
        student_statement = "I think social media algorithms are the main problem because they show people what they want to see."

        socratic_response = client.generate_socratic_response(
            student_input=student_statement,
            pdf_context=sample_context.strip(),
            conversation_history=[]
        )
        print(f"Bot: {socratic_response.get('response', 'No response')}")

    else:
        print("✗ Failed to connect to Ollama. Is it running?")
        print("  Try: ollama serve")
