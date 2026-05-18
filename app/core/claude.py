"""
JARVIS Cloud — Claude AI Integration

Implements the 3-layer routing system:
  L1: Local regex patterns (free, instant)
  L2: Claude Haiku (fast, cheap — default)
  L3: Claude Sonnet (powerful — complex queries)

Usage:
    from app.core.claude import JarvisAI
    
    ai = JarvisAI()
    response = await ai.respond("What's on my calendar today?")
"""

import re
import logging
from datetime import datetime
import pytz
from typing import Optional
import anthropic

from app.config import get_config

logger = logging.getLogger("jarvis.claude")


# ====== LAYER 1: LOCAL PATTERNS ======
# These queries never reach the API. Instant, free, reliable.

L1_PATTERNS = [
    # Time queries
    (
        re.compile(r"\b(what(?:'s| is) the time|current time|time (is it|now))\b", re.I),
        lambda cfg: f"It's {datetime.now(pytz.timezone(self.cfg.timezone if hasattr(self, "cfg") else "America/Chicago")).strftime('%I:%M %p')} {cfg.timezone.split('/')[-1]} time."
    ),
    # Date queries
    (
        re.compile(r"\b(what(?:'s| is) (today|the date)|today'?s? date)\b", re.I),
        lambda cfg: f"Today is {datetime.now(pytz.timezone(self.cfg.timezone if hasattr(self, "cfg") else "America/Chicago")).strftime('%A, %B %d, %Y')}."
    ),
    # Greeting responses
    (
        re.compile(r"^\s*(hello|hi|hey|good (morning|afternoon|evening))\s*[!.]?\s*$", re.I),
        lambda cfg: f"Good {_time_of_day()}, {cfg.owner_title}. How can I assist?"
    ),
    # Thanks
    (
        re.compile(r"^\s*(thank(s| you)|cheers|appreciated)\s*[!.]?\s*$", re.I),
        lambda cfg: f"Anytime, {cfg.owner_title}."
    ),
    # Status check
    (
        re.compile(r"\b(are you (there|online|running|active)|status check)\b", re.I),
        lambda cfg: f"Online and fully operational, {cfg.owner_title}."
    ),
]


def _time_of_day() -> str:
    """Returns morning/afternoon/evening based on current hour."""
    hour = datetime.now(pytz.timezone(self.cfg.timezone if hasattr(self, "cfg") else "America/Chicago")).hour
    if hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    return "evening"


def _is_complex_query(query: str) -> bool:
    """
    Heuristic to decide if a query needs Sonnet (L3) vs Haiku (L2).
    Upgrade to Sonnet for: planning, analysis, strategy, writing, comparison.
    """
    complex_indicators = [
        r"\b(plan|strategy|analyze|analyse|compare|draft|write|compose)\b",
        r"\b(pros and cons|trade.?off|recommend|advise|suggest)\b",
        r"\b(explain|breakdown|deep.?dive|walk me through)\b",
        r"\b(meeting prep|prepare for|brief me on)\b",
        r"\b(weekly|monthly|quarterly|annual) (review|report|summary)\b",
    ]
    for pattern in complex_indicators:
        if re.search(pattern, query, re.I):
            return True
    # Long queries are often complex
    if len(query.split()) > 30:
        return True
    return False


class JarvisAI:
    """
    Main AI interface for JARVIS Cloud.
    
    Handles 3-layer routing, conversation history, and
    system prompt construction per customer config.
    """

    def __init__(self):
        self.cfg = get_config()
        self.client = anthropic.Anthropic(api_key=self.cfg.anthropic_api_key)
        self._conversation_history: list[dict] = []
        logger.info("JarvisAI initialized — 3-layer routing active")

    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        """
        Constructs the JARVIS system prompt.
        Personalised per customer config. Context (calendar, email, etc.)
        is injected here when available.
        """
        now = datetime.now(pytz.timezone(self.cfg.timezone if hasattr(self, "cfg") else "America/Chicago"))
        base = f"""You are JARVIS — Just A Rather Very Intelligent System. You are a personal AI assistant modeled after Tony Stark's JARVIS from Iron Man.

You are serving: {self.cfg.owner_name} ({self.cfg.owner_title})
Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')} ({self.cfg.timezone})
Location: {self.cfg.location_city}

PERSONALITY:
- Calm, precise, witty, and quietly confident
- Refined British-influenced tone — professional but never stiff
- Address the owner as '{self.cfg.owner_title}' occasionally but don't overdo it
- Anticipate needs, think ahead, give the most efficient answer
- Never say 'Certainly!', 'Of course!', or 'Great question!'
- Get straight to the point
- You are not a chatbot. You are infrastructure.
- Keep responses concise unless a detailed breakdown is requested
- Never end a reply with the word 'Go'

CAPABILITIES:
- Calendar management and scheduling
- Email triage and drafting
- Task management
- Morning and evening briefings
- Weather and general intelligence
- Meeting preparation and planning

VOICE RESPONSE STYLE:
- Keep spoken responses under 3 sentences unless asked for detail
- No markdown, no bullet points, no headers — pure spoken prose
- Numbers written as words (e.g. "three" not "3") for natural TTS
- Prioritize the most important information first

TASK COMPLETION RULES:
- When asked to schedule or create a calendar event, you MUST emit an <action> tag — never say you cannot do it
- Confirm the action in one natural sentence after the tag (e.g. "Done — I've added that to your calendar.")
- Never claim you "can't" do something that falls within your capabilities

CALENDAR CREATION:
To schedule an event, include an action tag anywhere in your response:
<action>{{"type": "create_calendar_event", "title": "Event Name", "date": "YYYY-MM-DD", "time": "HH:MM", "duration_minutes": 60, "description": ""}}</action>
Use 24-hour time (e.g. "14:30"). Infer the date from context — today's date is in the current time above.
Omit "time" for all-day events."""

        if context:
            base += f"\n\nCONTEXT FOR THIS REQUEST:\n{context}"

        return base

    def _try_layer1(self, query: str) -> Optional[str]:
        """
        Attempt Layer 1 (local) response.
        Returns a string if matched, None if no pattern matches.
        """
        for pattern, responder in L1_PATTERNS:
            if pattern.search(query):
                response = responder(self.cfg)
                logger.debug(f"L1 match — query: '{query[:50]}' → local response")
                return response
        return None

    def respond(
        self,
        query: str,
        context: Optional[str] = None,
        force_layer: Optional[int] = None,
    ) -> dict:
        """
        Main entry point. Routes query through L1 → L2 → L3.

        Args:
            query: The user's message/question.
            context: Optional injected context (calendar events, emails, etc.)
            force_layer: Override routing — pass 2 or 3 to force a specific layer.

        Returns:
            dict with keys: response (str), layer (int), model (str), tokens (dict)
        """
        cfg = self.cfg

        # ---- LAYER 1: Local regex ----
        if force_layer is None or force_layer == 1:
            l1_response = self._try_layer1(query)
            if l1_response:
                return {
                    "response": l1_response,
                    "layer": 1,
                    "model": "local",
                    "tokens": {"input": 0, "output": 0},
                }

        # ---- LAYER 2 or 3: Claude API ----
        if force_layer == 3 or (force_layer is None and _is_complex_query(query)):
            model = cfg.claude_model_complex
            layer = 3
        else:
            model = cfg.claude_model_default
            layer = 2

        logger.info(f"L{layer} routing — model: {model} — query: '{query[:60]}'")

        # Build message history for this request
        messages = self._conversation_history.copy()
        messages.append({"role": "user", "content": query})

        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=1000,
                system=self._build_system_prompt(context=context),
                messages=messages,
            )

            reply_text = response.content[0].text
            token_info = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            }

            # Update conversation history (keep last 5 turns = 10 messages)
            self._conversation_history.append(
                {"role": "user", "content": query}
            )
            self._conversation_history.append(
                {"role": "assistant", "content": reply_text}
            )
            if len(self._conversation_history) > 10:
                self._conversation_history = self._conversation_history[-10:]

            logger.info(
                f"L{layer} response — tokens in:{token_info['input']} "
                f"out:{token_info['output']} — model:{model}"
            )

            return {
                "response": reply_text,
                "layer": layer,
                "model": model,
                "tokens": token_info,
            }

        except anthropic.AuthenticationError:
            logger.error("Anthropic authentication failed — check ANTHROPIC_API_KEY")
            return {
                "response": f"Authentication error, {cfg.owner_title}. The Anthropic API key needs updating.",
                "layer": layer,
                "model": model,
                "tokens": {"input": 0, "output": 0},
                "error": "auth_failed",
            }

        except anthropic.RateLimitError:
            logger.error("Anthropic rate limit hit")
            return {
                "response": f"Rate limit reached, {cfg.owner_title}. Throttling back.",
                "layer": layer,
                "model": model,
                "tokens": {"input": 0, "output": 0},
                "error": "rate_limited",
            }

        except Exception as e:
            logger.exception(f"Unexpected Claude error: {e}")
            return {
                "response": f"Something went wrong on my end, {cfg.owner_title}. Check the logs.",
                "layer": layer,
                "model": model,
                "tokens": {"input": 0, "output": 0},
                "error": str(e),
            }

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation_history = []
        logger.info("Conversation history cleared")
