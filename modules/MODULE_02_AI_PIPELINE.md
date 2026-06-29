# Module 2 — Multi-Agent AI Pipeline

## Responsibility

Intelligent article processing: translation, summarization, categorization, coin tagging, and sentiment.

## Provider

**OpenRouter** — OpenAI-compatible API  
Base URL: `https://openrouter.ai/api/v1`  
All models are accessed through this endpoint.

---

## Full flow

```
news_item (from Celery queue)
    │
    ▼
[Content resolve]
Fetch article URL → trafilatura / newspaper3k
On failure → title-only, generation_mode = summary_only
    │
    ▼
[Agent 0: Router]
Input: title + content preview (first 300 chars)
Output: { language: "en"|"fa", confidence: float }
    │
    ├─── source.language == "en" ──►  [Agent 1: Translation + Summary]
    │                                  Input: title + content (EN)
    │                                  Output: { title_fa, summary_fa }
    │
    └─── source.language == "fa" ──►  [Agent 2: Summary Only]
                                       Input: title + content (FA)
                                       Output: { summary_fa }  (title_fa = original title)
    │
    ▼ (both paths converge)
[Agent 3: Classifier + Tagger]
Input: build_classify_text(title_fa, summary_fa, content, raw_title)
Output: { categories[], coins[], sentiment }
    │
    ▼
[Schema Builder] → Publisher
```

**Routing note:** translate vs summarize is driven by **source language**, not only router output.

---

## OpenRouter Client

```python
# app/core/openrouter.py

import httpx
from openai import AsyncOpenAI

class OpenRouterClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "X-Title": "Radar"
            }
        )
    
    async def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 500,
        temperature: float = 0.3,
        task_name: str = "unknown",
        news_id: int | None = None,
        response_format: dict | None = None
    ) -> ChatResult:
        """
        Wrapper with retry, timeout, and automatic cost tracking.
        """
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format=response_format,
                    timeout=await settings.get("ai.timeout_seconds", 30)
                )
                
                # Automatic cost tracking
                await cost_tracker.log(
                    news_id=news_id,
                    model=model,
                    tokens_in=response.usage.prompt_tokens,
                    tokens_out=response.usage.completion_tokens,
                    task_name=task_name
                )
                
                return ChatResult(
                    content=response.choices[0].message.content,
                    usage=response.usage
                )
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # exponential backoff
```

Always use `OpenRouterClient` — never call OpenAI directly.

---

## Agent 0 — Router

**Model:** `ai.fast_model` (cheapest)  
**Purpose:** detect article language  
**Note:** if `langdetect` is confident (> 0.90), no LLM call is needed.

```python
# Optimal approach: rule-based first, then langdetect, then LLM
async def detect_language(title: str, content: str) -> str:
    # 1. Check Persian/Arabic script characters
    fa_chars = len(re.findall(r'[\u0600-\u06FF]', title))
    if fa_chars / max(len(title), 1) > 0.3:
        return "fa"
    
    # 2. langdetect
    try:
        lang = detect(title + " " + content[:200])
        if lang in ["en", "fa"] and detect_probability > 0.90:
            return lang
    except:
        pass
    
    # 3. LLM fallback
    return await llm_detect_language(title)
```

---

## Agent 1 — Translation + Summary (EN → FA)

**Model:** `agent.translator.model` or `ai.fast_model`  
**Input:** English title + content (up to N chars from settings)  
**Output:** JSON

### System prompt:
```
You are a professional crypto news translator and summarizer.
Translate the title accurately and write a clear Persian summary.
Keep crypto technical terms in English (e.g. Bitcoin, DeFi, NFT).
Return JSON only.
```

### User prompt:
```
Title: {title}
Content: {content[:max_content_length]}

JSON output:
{
  "title_fa": "Persian title",
  "summary_fa": "One-paragraph Persian summary (max 3 sentences)"
}
```

### Batch optimization:
For N articles at once, use one call:
```
Article list:
[1] title: ... content: ...
[2] title: ... content: ...

Response: [{"id": 1, "title_fa": ..., "summary_fa": ...}, ...]
```

---

## Agent 2 — Summary (FA only)

**Model:** `agent.summarizer_fa` or `ai.fast_model`  
**Input:** Persian title + Persian content  
**Output:** JSON

### System prompt:
```
You are a professional Persian crypto and economic news summarizer.
Write a clear, useful summary of the article.
Keep crypto technical terms in English (Bitcoin, DeFi, NFT, etc.).
Return JSON only.
```

### User prompt:
```
Title: {title}
Content: {content[:max_content_length]}

JSON output:
{
  "summary_fa": "One-paragraph summary (max 3 sentences)"
}
```

---

## Agent 3 — Classifier + Tagger

### Part 1: Hybrid category classification

```python
async def classify(text: str) -> ClassificationResult:
    # text = title_fa + summary_fa + raw_title + content excerpt
    news_embedding = await embed(text)
    
    # Compare against embedded categories (from cache)
    categories = await embedding_cache.get_categories()
    threshold = await settings.get("classifier.category_threshold", 0.65)
    
    matched = [
        cat for cat in categories
        if cosine_similarity(news_embedding, cat.vector) >= threshold
    ]
    
    # If no match → default category (classifier.default_category)
    if not matched:
        matched = [default_category]
    
    return matched
```

### Part 2: Hybrid coin tagging

```python
async def tag_coins(text: str) -> list[str]:
    # 1. Keyword match: symbol, English name, Persian aliases
    # 2. Embedding cosine similarity above classifier.coin_threshold
    threshold = await settings.get("classifier.coin_threshold", 0.65)
    
    matched_coins = keyword_matches + semantic_matches
    return matched_coins[:5]  # max 5 coins
```

Coin embedding text example:
```
BTC Bitcoin بیت کوین cryptocurrency blockchain digital asset
```

### Part 3: Sentiment (only when coins are detected)

**Model:** `ai.fast_model`  
**Runs only if** `len(coins) > 0`

```
Prompt:
Analyze the sentiment of this crypto news regarding the mentioned coins.
Respond with only one of: positive, negative, neutral

Title: {title_fa}
Summary: {summary_fa}
```

---

## Embedding cache

```python
class EmbeddingCache:
    """Redis-backed cache to avoid repeated re-embedding."""
    
    async def get_categories(self) -> list[CategoryEmbedding]:
        cached = await redis.get("embeddings:categories")
        if cached:
            return pickle.loads(cached)
        
        categories = await db.fetch_all_categories_with_embeddings()
        await redis.setex("embeddings:categories", 3600, pickle.dumps(categories))
        return categories
    
    async def invalidate(self, key: str):
        """Called when a category or coin is added/edited."""
        await redis.delete(f"embeddings:{key}")
```

---

## Cost management

### Model strategy

| Task | Suggested model | Approx. cost/article |
|------|-----------------|----------------------|
| Language detection | rule-based (free) | $0 |
| FA summary | `google/gemini-flash-1.5` | ~$0.001 |
| EN translation + summary | `google/gemini-flash-1.5` | ~$0.002 |
| Coin + category + sentiment | embedding (cheap) + mini LLM | ~$0.0005 |
| **Total per article** | | **~$0.003–0.005** |

### Daily cost estimate

- 500 articles × $0.004 = **~$2/day** = **~$60/month**
- Batching can reduce cost by up to ~40%

---

## Final pipeline output

```python
@dataclass
class ProcessedNews:
    news_id: int
    title_fa: str
    summary_fa: str
    categories: list[str]
    coins: list[str]
    sentiment: str | None       # only when coins is non-empty
    generation_mode: str        # "full" | "summary_only"
    processing_cost_usd: float
    models_used: list[str]
    processing_time_ms: int
    stages: list[PipelineStageResult]
```

## Celery async safety

Celery tasks use `run_async()` from `app.core.async_runner`, which resets the DB pool, Redis, embedder, and OpenRouter client between tasks to avoid `Event loop is closed` / `Future attached to a different loop` errors.
