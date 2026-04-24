"""
Ollama Client Module
Handles communication with local Ollama instance running llama3.1.
"""

import json
from typing import List, Dict, AsyncGenerator
import aiohttp
import requests


class OllamaClient:
    """Client for interacting with Ollama API."""

    SOCRATIC_SYSTEM_PROMPT = """You are a supportive Socratic tutor helping a student defend their essay through critical questioning.

Your role:
- Ask probing questions to challenge assumptions and claims
- Request specific evidence and reasoning
- Highlight potential logical inconsistencies or gaps
- Guide the student to think deeper without giving direct answers
- Be warm, encouraging, and intellectually rigorous without sounding adversarial
- Acknowledge the student's effort before pressing on a weakness when appropriate
- Keep responses conversational and usually under 60 words
- Focus on one question or challenge at a time

Remember: Your goal is to help the student feel capable while strengthening their argument through careful defense."""

    ESSAY_EDITOR_SYSTEM_PROMPT = """You are a supportive, practical essay editing assistant.

Your role:
- Follow the student's editing command directly
- Help with thesis clarity, structure, evidence, transitions, style, and revision
- When useful, provide concrete rewritten text the student can adapt
- Preserve the student's intended argument and voice
- Do not invent sources, quotes, page numbers, or facts
- Ask a clarifying question only when the request cannot be answered responsibly
- Be encouraging, collaborative, concise, specific, and action-oriented
- Point out problems as fixable revision opportunities, not failures"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:latest"):
        """
        Initialize Ollama client.

        Args:
            base_url: Ollama server URL
            model: Model name to use
        """
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/api/generate"
        self.chat_url = f"{base_url}/api/chat"

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
        initial_prompt = f"""The student has submitted an essay. Here is the essay context:

---
{pdf_context}
---

Generate a brief welcoming message (under 40 words) that:
1. Acknowledges you've reviewed their essay
2. Asks them to explain their main thesis or central argument in their own words

Be supportive and intellectually rigorous. Return only the message to the student."""

        return self.generate(initial_prompt)

    def initialize_editor_context(self, pdf_context: str) -> Dict:
        """Generate the opening message for text/editor mode."""
        initial_prompt = f"""{self.ESSAY_EDITOR_SYSTEM_PROMPT}

The student has uploaded an essay. Here is the essay context:

---
{pdf_context}
---

Generate a brief opening message (under 45 words) that:
1. Says you have reviewed the essay
2. Asks how they would like to improve it today
3. Gives 2-3 example requests such as thesis, structure, clarity, or rewriting a paragraph

Do not use Socratic questioning here. Return only the message to the student."""

        return self.generate(initial_prompt)

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
        # Format conversation history
        history_text = "\n".join([
            f"{msg['speaker'].upper()}: {msg['text']}"
            for msg in conversation_history[-6:]  # Last 6 exchanges for context
        ])

        prompt = f"""{self.SOCRATIC_SYSTEM_PROMPT}

Essay Context:
{pdf_context}

Recent Conversation:
{history_text if history_text else "(No prior conversation)"}

Student's latest statement:
"{student_input}"

Your Socratic response:"""

        return self.generate(prompt)

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
        # Format conversation history
        history_text = "\n".join([
            f"{msg['speaker'].upper()}: {msg['text']}"
            for msg in conversation_history[-6:]  # Last 6 exchanges for context
        ])

        prompt = f"""{self.SOCRATIC_SYSTEM_PROMPT}

Essay Context:
{pdf_context}

Recent Conversation:
{history_text if history_text else "(No prior conversation)"}

Student's latest statement:
"{student_input}"

Your Socratic response:"""

        async for chunk in self.generate_stream(prompt):
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
        history_text = "\n".join([
            f"{msg['speaker'].upper()}: {msg['text']}"
            for msg in conversation_history[-8:]
        ])

        prompt = f"""{self.ESSAY_EDITOR_SYSTEM_PROMPT}

Essay Context:
{pdf_context}

Recent Conversation:
{history_text if history_text else "(No prior conversation)"}

Student's latest request:
"{student_input}"

Your direct editing response:"""

        async for chunk in self.generate_stream(prompt):
            yield chunk

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
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload) as response:
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
            yield f"[Error: {str(e)}]"

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
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            }

            response = requests.post(self.api_url, json=payload, timeout=60)
            response.raise_for_status()

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
                "response": f"Error communicating with Ollama: {str(e)}",
                "error": True
            }

    def chat(self, messages: List[Dict[str, str]]) -> Dict:
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
                "stream": False
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
