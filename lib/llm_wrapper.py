"""
LLM Abstraction Wrapper — lib/llm_wrapper.py

All Claude API calls route through this class. This enables:
- Future model swap without touching agent code
- Centralized logging of all LLM calls
- Consistent error handling
- Phase-level model enforcement (claude-opus-4-8 required, no fallback)

Phase 6 introduces the full portability layer. The interface is established
here so all Phase 1+ agents can respect it.

Usage:
    from lib.llm_wrapper import LLMWrapper

    llm = LLMWrapper(agent_name="analyst", task_id="task-uuid")
    result = llm.generate(
        system_prompt="You are the Analyst Agent...",
        user_message="Investigate this API abuse pattern...",
        tools=None,
    )

══════════════════════════════════════════════════════════════════════════════
PORTABILITY LAYER — Phase 6 Documentation (deliverable 6.5)
══════════════════════════════════════════════════════════════════════════════

This wrapper implements the LLM interface layer described in
implementation_plan.md §6.5. It isolates all Claude-specific API calls
behind a single class with a provider-agnostic surface:

  generate(system_prompt, user_message, tools) → dict
  generate_streaming(system_prompt, user_message, tools, on_token) → dict

To migrate this orchestration layer to a different frontier model provider,
the following THREE integration points require attention:

── Integration Point 1: Tool Format Differences ─────────────────────────────
Current (Anthropic):
  tools=[{"name": "X", "description": "...", "input_schema": {...}}]
  Response: content blocks with type="tool_use", .name, .input (dict)

OpenAI-compatible (GPT-4, Gemini, Llama with OpenAI shim):
  tools=[{"type": "function", "function": {"name": "X", "description": "...",
          "parameters": {...}}}]
  Response: message.tool_calls[i].function.name + .arguments (JSON string —
  must parse, unlike Anthropic which returns a dict directly)

Migration action: replace `create_kwargs["tools"]` construction and the
tool_blocks extraction logic in generate() and generate_streaming().
Agent code that reads result["tool_calls"] must also adapt: Anthropic returns
the full block object; OpenAI returns a parsed ToolCall dataclass. The tool
DESCRIPTIONS in agents/*/system_prompt.md are provider-agnostic and do not
need to change — only the wire format into the API call changes.

── Integration Point 2: Context Window Limits ───────────────────────────────
Current (claude-opus-4-8): 200,000 token context window.

Key consumers of context in Maldros and their approximate budgets:
  Orchestrator: full CDI Layer 9-domain dump + system prompt ≈ 8,000–14,000 tokens
  Analyst:      full evidence bundle + investigation history ≈ 30,000–50,000 tokens
  Storyteller:  evidence bundle + chart spec + 18-asset schema ≈ 40,000–60,000 tokens
  Phase7Proposer: bottleneck report + reasoning frameworks ≈ 6,000–10,000 tokens

Migration risk: a target model with ≤ 32K context (e.g., GPT-3.5-turbo, early
Llama variants) would overflow on Analyst and Storyteller calls without chunking.
Mitigation: CDI selective domain loading (BOTTLENECK_001 proposal) reduces
Orchestrator to ≈ 3,000–5,000 tokens; Analyst + Storyteller need evidence bundle
chunking with multi-call synthesis for sub-32K providers.

Migration action: add a `context_limit` parameter to LLMWrapper.__init__() and
validate the total token budget (system + user) before the API call. If total
exceeds context_limit × 0.90, raise a TokenBudgetExceededError before the API
call rather than receiving a truncated mid-response error. Each agent's system
prompt character count is already logged to AIMS Mode A for budget monitoring.

── Integration Point 3: Extended Thinking Availability ──────────────────────
Current: Anthropic extended thinking is available on claude-opus-4-8.
Enable via: create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": N}

The primary candidate in Maldros is the Forge Agent (agents/forge/forge.py):
its 11-step invention pipeline and Pre-Screen Gate benefit from extended
reasoning depth to distinguish genuine novelty from incremental refinement.
Extended thinking is not currently invoked — the Forge uses standard prompting.

Migration risk: no other major frontier provider exposes an equivalent mechanism
at the API level as of 2026. Google Gemini 2.0 Flash Thinking is a separate
model variant; OpenAI o-series uses internal chain-of-thought but does not
expose a budget_tokens-style parameter.

Migration action: add a `supports_extended_thinking: bool` flag to
LLMWrapper.__init__() (default: True for claude-opus-4-8). When True, Forge
calls may inject {"thinking": {"type": "enabled", "budget_tokens": 8192}}.
When False, no-op — the Forge falls back to the step-by-step chain-of-thought
prompting already present in FORGE_SYSTEM_PROMPT (agents/forge/system_prompt.md).
Agent code should check `llm.supports_extended_thinking` before requesting
extended reasoning so the Forge degrades gracefully on non-Anthropic providers.
══════════════════════════════════════════════════════════════════════════════
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

AIMS_MODE_A_DIR = Path(__file__).resolve().parents[1] / "aims" / "mode_a"

# Non-negotiable. No fallback to lighter models per CLAUDE.md spec.
# Updated Session 19: claude-opus-4-6 → claude-opus-4-8 (strongest available Opus; per spec clause "or strongest available").
REQUIRED_MODEL = "claude-opus-4-8"


class LLMWrapper:
    """
    Wraps Claude API calls for all Maldros agents.

    All LLM calls must:
    - Use REQUIRED_MODEL (claude-opus-4-6) — enforced on every call
    - Be logged to AIMS Mode A with token counts and latency
    - Include the task_id in all calls for traceability

    Phase 1 activation: requires ANTHROPIC_API_KEY env variable.
    Phase 0: wrapper class exists but generate() raises NotImplementedError
    with clear instructions for activation.
    """

    def __init__(
        self,
        agent_name: str,
        task_id: str,
        model: Optional[str] = None,
        supports_extended_thinking: bool = True,
    ):
        self.agent_name = agent_name
        self.task_id = task_id
        self.model = model or REQUIRED_MODEL
        if self.model != REQUIRED_MODEL:
            raise ValueError(
                f"Model '{self.model}' is not permitted. "
                f"Only '{REQUIRED_MODEL}' is authorized per CLAUDE.md spec. "
                "No fallback to lighter models."
            )
        # Portability flag — see Integration Point 3 in module docstring.
        # False on non-Anthropic providers; Forge degrades gracefully.
        self.supports_extended_thinking = supports_extended_thinking
        AIMS_MODE_A_DIR.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[list] = None,
        max_tokens: int = 8192,
    ) -> dict:
        """
        Generate a response from the LLM.

        Returns:
            {
                "content": str,        # Model text response
                "tool_calls": list,    # Tool use blocks, if any
                "input_tokens": int,
                "output_tokens": int,
                "model": str,
                "call_id": str,        # UUID for this specific call
            }

        Phase 1 active: requires ANTHROPIC_API_KEY env variable.
        """
        import time
        import anthropic

        call_id = str(uuid.uuid4())
        t_start = time.time()

        self._log_call(
            call_id=call_id,
            system_prompt_len=len(system_prompt),
            user_message_len=len(user_message),
            tools=tools,
            status="STARTED",
        )

        client = anthropic.Anthropic()

        # Build create kwargs — tools only if non-empty (Anthropic API rejects empty list)
        create_kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        if tools:
            create_kwargs["tools"] = tools

        response = client.messages.create(**create_kwargs)

        # Extract text content — handle both text and tool_use blocks
        text_blocks = [b for b in response.content if b.type == "text"]
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        content_text = text_blocks[0].text if text_blocks else ""

        elapsed = round(time.time() - t_start, 2)

        self._log_call_completed(
            call_id=call_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            elapsed_sec=elapsed,
        )

        return {
            "content": content_text,
            "tool_calls": tool_blocks,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "model": response.model,
            "call_id": call_id,
        }

    def generate_streaming(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[list] = None,
        max_tokens: int = 8192,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        Alternative invocation pattern: streaming response.

        Uses the Anthropic streaming API (client.messages.stream) instead of
        the blocking client.messages.create. Tokens are delivered incrementally
        via the on_token callback as they arrive from the API.

        Portability notes (see Integration Points 1–3 in the module docstring):
        - Integration Point 1: tool extraction from stream.get_final_message()
          uses the same Anthropic block format as generate() — same migration
          action applies.
        - Integration Point 2: context budget validation applies identically
          before the stream is opened.
        - Integration Point 3: extended thinking is not available in streaming
          mode on the Anthropic API as of 2026 (thinking blocks are not streamed).
          If the Forge requests extended thinking, it should use generate(), not
          generate_streaming().

        Primary use case in Maldros: Storyteller Agent on long dual-layer
        outputs — streaming provides real-time terminal output for the operator
        during the 60–120s Storyteller calls.

        Args:
            system_prompt: Agent system prompt.
            user_message: User message (investigation question or artifact JSON).
            tools: Tool definitions (or None). See Integration Point 1.
            max_tokens: Maximum output tokens.
            on_token: Optional callback called with each text delta as it arrives.
                      Signature: on_token(delta: str) → None.
                      If None, tokens are accumulated silently and returned in
                      the result dict (same interface as generate()).

        Returns same structure as generate():
            {
                "content": str,        # Full accumulated text response
                "tool_calls": list,    # Tool use blocks from final message
                "input_tokens": int,
                "output_tokens": int,
                "model": str,
                "call_id": str,
            }
        """
        import time
        import anthropic

        call_id = str(uuid.uuid4())
        t_start = time.time()

        self._log_call(
            call_id=call_id,
            system_prompt_len=len(system_prompt),
            user_message_len=len(user_message),
            tools=tools,
            status="STARTED_STREAMING",
        )

        client = anthropic.Anthropic()

        create_kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        if tools:
            create_kwargs["tools"] = tools

        content_parts: list[str] = []
        tool_blocks: list = []
        input_tokens = 0
        output_tokens = 0

        with client.messages.stream(**create_kwargs) as stream:
            for text_delta in stream.text_stream:
                content_parts.append(text_delta)
                if on_token is not None:
                    on_token(text_delta)

            final_msg = stream.get_final_message()
            input_tokens = final_msg.usage.input_tokens
            output_tokens = final_msg.usage.output_tokens
            tool_blocks = [b for b in final_msg.content if b.type == "tool_use"]

        elapsed = round(time.time() - t_start, 2)

        self._log_call_completed(
            call_id=call_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_sec=elapsed,
        )

        return {
            "content": "".join(content_parts),
            "tool_calls": tool_blocks,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": self.model,
            "call_id": call_id,
        }

    def _log_call(self, call_id: str, system_prompt_len: int,
                  user_message_len: int, tools, status: str) -> None:
        """Log every LLM call attempt to AIMS Mode A for traceability."""
        entry = {
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LLM_CALL_STARTED",
            "call_id": call_id,
            "agent": self.agent_name,
            "task_id": self.task_id,
            "model": self.model,
            "system_prompt_chars": system_prompt_len,
            "user_message_chars": user_message_len,
            "tools_count": len(tools) if tools else 0,
            "status": status,
        }
        log_file = AIMS_MODE_A_DIR / "llm_call_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _log_call_completed(self, call_id: str, input_tokens: int,
                            output_tokens: int, elapsed_sec: float) -> None:
        """Log completion of an LLM call with token counts and latency."""
        entry = {
            "aims_entry_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "LLM_CALL_COMPLETED",
            "call_id": call_id,
            "agent": self.agent_name,
            "task_id": self.task_id,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "elapsed_sec": elapsed_sec,
            "status": "COMPLETED",
        }
        log_file = AIMS_MODE_A_DIR / "llm_call_log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
