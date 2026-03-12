"""
gemini_ai.py — Gemini 2.5 Flash integration for AI-powered analysis.

Uses the google.genai SDK with Google Search grounding for web search
and direct generation for analysis/report tasks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from log_config import get_logger

_log = get_logger("gemini")
_HERE = Path(__file__).parent

_client = None


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        env_path = _HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set. Add it to .env or environment.")
    return key


def _load_config() -> dict:
    cfg_path = _HERE / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=_get_api_key())
    return _client


def _get_model_name() -> str:
    return _load_config().get("gemini", {}).get("model", "gemini-2.5-flash")


def _get_gen_config():
    from google.genai import types
    cfg = _load_config().get("gemini", {})
    return types.GenerateContentConfig(
        temperature=cfg.get("temperature", 0.7),
        max_output_tokens=cfg.get("max_output_tokens", 8192),
    )


def _parse_json_response(text: str) -> dict:
    """Extract JSON from a response that may be wrapped in markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Some responses embed a JSON string inside a top-level field — try to find the
    # outermost { ... } and parse it
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {"raw_text": text}


def search_web(query: str, num_results: int = 10) -> dict[str, Any]:
    """Search the web using Gemini with Google Search grounding."""
    from google.genai import types

    _log.info("Web search: %s", query)
    client = _get_client()
    model = _get_model_name()

    prompt = f"""Search the web for the following topic and provide a comprehensive summary.
Include specific data points, statistics, trends, and expert opinions where available.

Topic: {query}

Respond in JSON format:
{{
  "summary": "comprehensive summary of findings (2-3 paragraphs)",
  "key_findings": ["finding 1", "finding 2", ...],
  "trends": ["trend 1", "trend 2", ...],
  "statistics": ["stat 1", "stat 2", ...],
  "sources": [{{"title": "...", "url": "...", "snippet": "..."}}],
  "related_topics": ["topic 1", "topic 2", ...]
}}"""

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        text = response.text
        if text is None:
            # Gemini sometimes returns None text with grounding — extract from parts
            parts = []
            for candidate in getattr(response, "candidates", []):
                for part in getattr(candidate.content, "parts", []):
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
            text = "\n".join(parts) if parts else ""

        if not text:
            return {"status": "error", "source": "web", "query": query, "error": "Empty response from Gemini"}

        result = _parse_json_response(text)
        # If the top-level is {"summary": "{json...}"}, try to parse the nested JSON
        if isinstance(result.get("summary"), str) and result["summary"].lstrip().startswith("{"):
            try:
                nested = json.loads(result["summary"])
                if isinstance(nested, dict) and "key_findings" in nested:
                    result = nested
            except json.JSONDecodeError:
                pass
        if "raw_text" in result:
            result = {
                "summary": result["raw_text"],
                "key_findings": [],
                "trends": [],
                "statistics": [],
                "sources": [],
                "related_topics": [],
            }

        _log.info("Web search complete: %d findings", len(result.get("key_findings", [])))
        return {"status": "ok", "source": "web", "query": query, "data": result}

    except Exception as e:
        _log.error("Web search failed: %s", e)
        return {"status": "error", "source": "web", "query": query, "error": str(e)}


def search_social_insights(topic: str, platform: str = "all") -> dict[str, Any]:
    """Search for social media insights about a topic using Gemini + Google Search.

    This is used as a fallback/supplement when direct scraping returns limited data.
    Gemini searches the web for social media discussions, reviews, and opinions.
    """
    from google.genai import types

    _log.info("Social media insight search: %s (platform: %s)", topic, platform)
    client = _get_client()
    model = _get_model_name()

    platform_hint = ""
    if platform == "tiktok":
        platform_hint = "Focus on TikTok trends, videos, hashtags, and creators."
    elif platform == "facebook":
        platform_hint = "Focus on Facebook group discussions, posts, and community opinions."
    elif platform == "instagram":
        platform_hint = "Focus on Instagram posts, reels, and influencer content."

    prompt = f"""Search for what people are saying about this topic on social media platforms.
{platform_hint}

Topic: {topic}

Find real discussions, reviews, opinions, trending content, popular creators/influencers,
and consumer sentiment from social media. Include specific examples and data.

Respond in JSON:
{{
  "platform_insights": [
    {{
      "platform": "tiktok/facebook/instagram/twitter/etc",
      "trending_content": ["description of trending posts/videos"],
      "popular_hashtags": ["#hashtag1", "#hashtag2"],
      "key_creators": ["creator1", "creator2"],
      "consumer_opinions": ["opinion/quote 1", "opinion/quote 2"],
      "engagement_level": "high/medium/low",
      "sentiment": "positive/neutral/negative/mixed"
    }}
  ],
  "overall_sentiment": "positive/neutral/negative/mixed",
  "viral_themes": ["theme 1", "theme 2"],
  "consumer_pain_points": ["pain 1", "pain 2"],
  "consumer_desires": ["desire 1", "desire 2"],
  "recommended_keywords": ["keyword 1", "keyword 2"]
}}"""

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        text = response.text
        if text is None:
            parts = []
            for candidate in getattr(response, "candidates", []):
                for part in getattr(candidate.content, "parts", []):
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
            text = "\n".join(parts) if parts else ""

        if not text:
            return {"status": "error", "source": f"social_insights_{platform}", "error": "Empty response"}

        result = _parse_json_response(text)
        if "raw_text" in result:
            result = {"summary": result["raw_text"], "platform_insights": []}

        _log.info("Social insight search complete")
        return {"status": "ok", "source": f"social_insights_{platform}", "topic": topic, "data": result}

    except Exception as e:
        _log.error("Social insight search failed: %s", e)
        return {"status": "error", "source": f"social_insights_{platform}", "error": str(e)}


def analyze_data(topic: str, collected_data: list[dict], language: str = "vi") -> dict[str, Any]:
    """Analyze collected data from multiple sources using Gemini."""
    _log.info("Analyzing data for topic: %s (%d sources)", topic, len(collected_data))
    client = _get_client()
    model = _get_model_name()

    data_summary = json.dumps(collected_data, ensure_ascii=False, indent=2)
    if len(data_summary) > 100_000:
        data_summary = data_summary[:100_000] + "\n... [truncated]"

    lang_instruction = "Trả lời bằng tiếng Việt." if language == "vi" else "Respond in English."

    prompt = f"""You are a senior market research analyst. Analyze the following data collected from multiple sources about this topic:

**Topic**: {topic}

**Collected Data**:
{data_summary}

{lang_instruction}

Provide a comprehensive market research analysis in JSON format:
{{
  "executive_summary": "2-3 paragraph executive summary",
  "market_overview": {{
    "description": "Current market state",
    "size_and_growth": "Market size and growth data if available",
    "key_players": ["player 1", "player 2"]
  }},
  "consumer_insights": {{
    "sentiment": {{"positive_pct": 0, "neutral_pct": 0, "negative_pct": 0}},
    "pain_points": ["pain 1", "pain 2"],
    "desires": ["desire 1", "desire 2"],
    "common_questions": ["question 1", "question 2"]
  }},
  "trends": {{
    "current": ["trend 1", "trend 2"],
    "emerging": ["trend 1", "trend 2"],
    "declining": ["trend 1", "trend 2"]
  }},
  "competitive_landscape": {{
    "top_brands": [{{"name": "...", "strengths": "...", "weaknesses": "..."}}],
    "market_gaps": ["gap 1", "gap 2"]
  }},
  "social_media_analysis": {{
    "platforms_summary": {{"facebook": "...", "tiktok": "...", "web": "..."}},
    "viral_content_themes": ["theme 1", "theme 2"],
    "influencer_topics": ["topic 1", "topic 2"]
  }},
  "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"],
  "data_quality": {{
    "total_sources": 0,
    "coverage": "description of data coverage",
    "limitations": ["limitation 1"]
  }}
}}"""

    try:
        config = _get_gen_config()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        result = _parse_json_response(response.text)
        if "raw_text" in result:
            result = {"executive_summary": result["raw_text"]}

        _log.info("Analysis complete")
        return {"status": "ok", "topic": topic, "analysis": result}

    except Exception as e:
        _log.error("Analysis failed: %s", e)
        return {"status": "error", "topic": topic, "error": str(e)}


def generate_report_text(topic: str, analysis: dict, language: str = "vi") -> str:
    """Convert analysis JSON into a human-readable markdown report."""
    client = _get_client()
    model = _get_model_name()

    lang_instruction = "Viết bằng tiếng Việt, rõ ràng, dễ hiểu cho mọi người." if language == "vi" else "Write in English, clear and accessible."

    prompt = f"""Convert this market research analysis into a clear, well-formatted report.
Use markdown formatting. Include headers, bullet points, and emphasis where appropriate.
{lang_instruction}

Topic: {topic}

Analysis data:
{json.dumps(analysis, ensure_ascii=False, indent=2)}

Write the report now. Make it professional but easy to understand.
Include an executive summary at the top, then detailed sections.
End with actionable recommendations."""

    try:
        config = _get_gen_config()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response.text.strip()
    except Exception as e:
        _log.error("Report generation failed: %s", e)
        return f"# {topic}\n\nReport generation failed: {e}"
