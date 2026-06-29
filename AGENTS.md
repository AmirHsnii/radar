# AGENTS.md — Multi-Agent Pipeline Specification

## Overall architecture

```
Orchestrator
    ├── RouterAgent         (language detection)
    ├── TranslationAgent    (EN → FA)
    ├── SummaryAgent        (FA summarization)
    └── ClassifierAgent
            ├── CategoryTagger
            ├── CoinTagger
            └── SentimentAnalyzer
```

---

## Orchestrator

**Role:** Manage the full pipeline, coordinate agents, handle errors.

```python
class PipelineOrchestrator:
    """
    Responsibilities:
    - Receive a NewsItem from the Celery queue
    - Run agents in order (fetch → route → translate|summarize → classify)
    - Collect results and persist
    - Queue publish or send to DLQ on failure
    """

    async def process(self, item: NewsItem) -> ProcessedNews:
        try:
            # Step 1: Fetch full page content (fallback to title-only → summary_only)
            text, generation_mode = await resolve_article_content(item)

            # Step 2: Route (source language drives translate vs summarize)
            lang_result = await router_agent.detect(title=item.title, content_preview=text[:300])

            # Step 3: Text processing (sequential)
            if source_language == "en":
                text_result = await translation_agent.process(item)
            else:
                text_result = await summary_agent.process(item)

            # Step 4: Classification
            classify_text = await build_classify_text(
                title_fa=item.title_fa,
                summary_fa=item.summary_fa,
                content=item.content,
                raw_title=item.title,
            )
            clf = await classifier_agent.classify(classify_text, news_id=item.id)

            return ProcessedNews(...)

        except Exception as e:
            await send_to_dlq(item.id, stage="pipeline", error=str(e))
            raise
```

---

## Agent 1 — RouterAgent

**Identity:** News language detector

**Input:**
```python
{
    "title": str,
    "content_preview": str  # first 300 characters
}
```

**Output:**
```python
{
    "language": "fa" | "en",
    "method": "rule" | "langdetect" | "llm",  # for debugging
    "confidence": float
}
```

**Strategy (in order):**
1. **Rule-based:** count Persian/Arabic script characters in the title
   - If > 30%: `fa` with confidence 0.99
2. **langdetect:** automatic detection
   - If confidence > 0.90: return result
3. **LLM fallback:** only for ambiguous cases (e.g. mixed-language titles)

**LLM model:** `ai.fast_model` (cheapest)

**System prompt:**
```
Detect the primary language of this news article title and content.
Respond only with JSON: {"language": "fa" or "en"}
Consider: if title has Arabic/Persian script characters, it's "fa".
```

**Note:** Pipeline routing for translate vs summarize uses **source language** (`source.language`), not only router output.

---

## Agent 2A — TranslationAgent

**Identity:** Translator and summarizer for English crypto news

**Input:**
```python
{
    "title": str,           # English title
    "content": str,         # body (up to max_content_length chars)
    "source_name": str      # for better context
}
```

**Output:**
```python
{
    "title_fa": str,        # translated title
    "summary_fa": str       # 2–3 sentence summary
}
```

**Model:** `agent.translator.model` or `ai.fast_model`

**System prompt:**
```
You are a professional crypto news translator and summarizer.
Your task:
1. Translate the English title to natural Persian (Farsi)
2. Write a concise Persian summary (2-3 sentences max)

Rules:
- Keep crypto technical terms in English (Bitcoin, DeFi, NFT, ETH, etc.)
- Use formal Persian writing style
- Summary must capture the key news point
- Response must be valid JSON only, no extra text

Output format:
{
  "title_fa": "...",
  "summary_fa": "..."
}
```

**Batch mode** (cost optimization):
```python
# When batch_size > 1, process multiple articles in one call
user_prompt = f"""
Translate and summarize these {len(items)} news articles:

{formatted_items}

Return JSON array: [
  {{"id": 1, "title_fa": "...", "summary_fa": "..."}},
  ...
]
"""
```

**Validation:**
- Output title must not be empty
- Summary must contain Persian characters
- Invalid JSON → retry with a simpler prompt

---

## Agent 2B — SummaryAgent

**Identity:** Summarizer for Persian news

**Input:**
```python
{
    "title": str,     # Persian title
    "content": str    # Persian body
}
```

**Output:**
```python
{
    "summary_fa": str  # 2–3 sentence summary
}
```

**Model:** `agent.summarizer.model` or `agent.summarizer_fa` for FA sources

**System prompt (FA sources use `summarizer_fa`):**
```
You are a professional Persian crypto and economic news summarizer.
This article is from a domestic Persian news source.
Write a clear, useful 2–3 sentence summary.
Keep crypto technical terms in English (Bitcoin, DeFi, NFT, etc.).
Return JSON only: {"summary_fa": "..."}
```

**Notes for Persian-source articles:**
- Translation is skipped (`translate` stage skipped, reason: `persian_source`)
- Sentiment runs only when coins are tagged
- Categories and coins use the same classifier as EN articles

---

## Agent 3 — ClassifierAgent

**Identity:** Crypto news categorizer and tagger

### 3.1 CategoryTagger

**Method:** Embedding cosine similarity (no LLM) + default category fallback

```python
class CategoryTagger:
    async def tag(self, text: str) -> list[CategoryMatch]:
        # text = title_fa + summary_fa + title + content excerpt
        news_emb = await embedding_cache.embed(text)
        categories = await embedding_cache.get_categories()

        matches = []
        threshold = await settings.get("classifier.category_threshold", 0.65)

        for cat in categories:
            score = cosine_similarity(news_emb, cat.vector)
            if score >= threshold:
                matches.append(CategoryMatch(id=cat.id, name=cat.name, score=score))

        if not matches:
            # fallback to classifier.default_category (e.g. "market-news")

        return sorted(matches, key=lambda m: m.score, reverse=True)
```

**Default categories** (seeded with descriptions for embedding):
```python
DEFAULT_CATEGORIES = [
    {"name": "market-news", "name_fa": "اخبار بازار", "description": "crypto market prices, volatility, statistics"},
    {"name": "defi", "name_fa": "دیفای", "description": "decentralized finance, yield farming, liquidity"},
    {"name": "nft", "name_fa": "NFT", "description": "non-fungible tokens, digital art, metaverse"},
    {"name": "regulation", "name_fa": "قوانین و مقررات", "description": "government rules, SEC, legislation"},
    # ... more categories in DB
]
```

### 3.2 CoinTagger

**Method:** Keyword match + embedding cosine similarity (hybrid)

```python
class CoinTagger:
    async def tag(self, text: str) -> list[str]:
        # 1. Keyword: symbol, English name, Persian aliases (e.g. BTC, Bitcoin, بیت کوین)
        # 2. Embedding: cosine similarity above classifier.coin_threshold
        # Returns up to 5 symbols, keywords first then semantic matches
```

**Coin embedding text:**
```python
# Per coin, embedding input is built via coin_embed_text():
# "BTC Bitcoin بیت کوین cryptocurrency blockchain digital asset"
```

### 3.3 SentimentAnalyzer

**Run condition:** only if `len(coins) > 0`  
**Model:** `ai.fast_model`

**System prompt:**
```
You are a crypto news sentiment analyzer.
Analyze the sentiment of this news specifically regarding cryptocurrencies mentioned.
Respond with JSON only: {"sentiment": "positive" | "negative" | "neutral"}

positive = bullish, price increase, adoption, good news
negative = bearish, price decrease, hack, ban, bad news
neutral = factual, informational, neither clearly positive nor negative
```

**Validation:** output must be one of the three values; otherwise → `neutral`

**Concurrency pattern:**
1. `CategoryTagger` and `CoinTagger` start in parallel as Tasks
2. After coins are known, `SentimentAnalyzer` runs only if coins were found
3. Category task result is gathered together with conditional sentiment

---

## Agent cost management

### Model tiers (cheap to expensive)

```python
MODEL_TIERS = {
    "ultra_fast": "google/gemini-flash-1.5",    # $0.075/1M tokens
    "fast": "openai/gpt-4o-mini",               # $0.15/1M tokens
    "quality": "anthropic/claude-3-haiku",      # $0.25/1M tokens
    "premium": "openai/gpt-4o",                 # $5/1M tokens
}

# Task assignment (from settings):
# router: ultra_fast
# translate/summarize: fast (per-agent override supported)
# sentiment: ultra_fast
# re-process errors: quality
```

### Batch strategy

```python
class BatchProcessor:
    """
    Group N articles into one LLM call.
    Savings: ~40% cost reduction (less prompt overhead).
    """

    async def process_batch(
        self,
        items: list[NewsItem],
        batch_size: int | None = None
    ) -> list[ProcessedNews]:
        size = batch_size or await settings.get("ai.batch_size", 5)

        results = []
        for chunk in chunks(items, size):
            batch_result = await self._process_chunk(chunk)
            results.extend(batch_result)

        return results
```

---

## Final output schema

```python
@dataclass
class ProcessedNews:
    # Core fields
    news_id: int
    title_fa: str
    summary_fa: str

    # Classification
    categories: list[str]           # category names (Persian)
    category_ids: list[int]         # IDs for WordPress

    # Coins
    coins: list[str]                # symbols: ["BTC", "ETH"]

    # Sentiment
    sentiment: Literal["positive", "negative", "neutral"] | None

    # Metadata
    language: str                   # "en" | "fa"
    processing_cost_usd: float
    models_used: list[str]
    processing_time_ms: int
    pipeline_version: str
    stages: list[PipelineStageResult]  # persisted as pipeline_stages_json
```

## Generation modes

| Mode | Meaning |
|------|---------|
| `full` | Article page fetched successfully; summary based on full content |
| `summary_only` | Page fetch failed; pipeline used title only; WordPress shows auto-generated notice |
