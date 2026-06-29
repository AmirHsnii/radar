// ── News ─────────────────────────────────────────────────────────────────────

export interface NewsItem {
  id: number;
  url: string;
  title: string | null;
  title_fa: string | null;
  summary_fa: string | null;
  content: string | null;
  language: string | null;
  source_id: number | null;
  status: string;
  retry_count: number;
  sentiment: string | null;
  coins_json: string | null;
  categories_json: string | null;
  wp_post_id: number | null;
  processing_cost_usd: number | null;
  pipeline_stages_json: string | null;
  generation_mode: string | null;
  created_at: string;
  processed_at: string | null;
  published_at: string | null;
}

export interface NewsListOut {
  items: NewsItem[];
  total: number;
  page: number;
  size: number;
}

export interface NewsStats {
  total: number;
  by_status: Record<string, number>;
  by_language: Record<string, number>;
}

export interface NewsFilters {
  status?: string;
  source_id?: number;
  language?: string;
  coin?: string;
  category?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  size?: number;
}

// ── Sources ──────────────────────────────────────────────────────────────────

export interface Source {
  id: number;
  name: string;
  rss_url: string;
  site_url: string;
  language: string;
  is_active: boolean;
  priority: number;
  poll_interval_minutes: number | null;
  last_polled_at: string | null;
  last_poll_status: string | null;
  last_poll_new_items: number | null;
  last_poll_message: string | null;
  created_at: string;
}

export interface SourceCreate {
  name: string;
  rss_url: string;
  site_url?: string;
  language?: string;
  is_active?: boolean;
  priority?: number;
  poll_interval_minutes?: number | null;
}

export interface SourceUpdate extends Partial<SourceCreate> {}

// ── Costs ─────────────────────────────────────────────────────────────────────

export interface CostByModelEntry {
  model: string;
  cost_usd: number;
  calls: number;
}

export interface CostPeriod {
  period: string;
  total_cost_usd: number;
  tokens_in?: number;
  tokens_out?: number;
  calls: number;
  by_model?: CostByModelEntry[];
}

export interface CostSummary {
  budget_alert: {
    alert: boolean;
    budget_usd: number;
    spent_usd: number;
    spent_pct: number;
    threshold_pct: number;
    period: string;
  } | null;
  today: Pick<CostPeriod, "period" | "total_cost_usd" | "calls"> | null;
  this_month: Pick<CostPeriod, "period" | "total_cost_usd" | "calls"> | null;
}

export interface CostsByModelOut {
  period: string;
  by_model: CostByModelEntry[];
}

export interface CostLog {
  id: number;
  news_id: number | null;
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  task_name: string;
  created_at: string;
}

// ── DLQ ──────────────────────────────────────────────────────────────────────

export interface DlqItem {
  id: number;
  news_id: number | null;
  stage: string;
  error_message: string;
  retry_count: number;
  max_retries: number;
  next_retry_at: string | null;
  status: string;
  created_at: string;
}

export interface DlqListOut {
  items: DlqItem[];
  total: number;
  page: number;
  size: number;
}

export interface DlqStats {
  total: number;
  pending: number;
  retrying: number;
  exhausted: number;
  discarded: number;
  resolved?: number;
}

// ── Settings ─────────────────────────────────────────────────────────────────

export interface AppSetting {
  key: string;
  value: string;
  value_type: string;
  description: string;
  updated_by?: string | null;
  updated_at: string;
}

export interface GroupedSettingsOut {
  category: string;
  settings: AppSetting[];
}

// ── WordPress Preview ─────────────────────────────────────────────────────────

export interface WpPreviewUi {
  source_name: string | null;
  source_url: string;
  source_title: string | null;
  language: string | null;
  processing_cost_usd: number | null;
  current_status: string;
}

export interface WpPreview {
  payload?: Record<string, unknown>;
  _ui?: WpPreviewUi;
  // legacy flat format (pre-refactor backend)
  title?: string | null;
  content?: string;
  status?: string;
  categories?: string[];
  tags?: string[];
  meta?: Record<string, unknown>;
  _source_url?: string;
  _source_title?: string | null;
  _language?: string | null;
  _processing_cost_usd?: number | null;
  _current_status?: string;
}

export interface PipelineStage {
  stage: string;
  status: "ran" | "skipped" | "failed" | "queued";
  reason?: string | null;
  duration_ms?: number | null;
  detail?: Record<string, unknown>;
}

// ── Admin / Data ──────────────────────────────────────────────────────────────

export interface Coin {
  id: number;
  symbol: string;
  name: string;
  aliases: string[];
  has_embedding: boolean;
  updated_at: string;
}

export interface Category {
  id: number;
  name: string;
  name_fa: string;
  description: string;
  has_embedding: boolean;
  updated_at: string;
}

export interface DualWhitelistOut {
  fa_keywords: string[];
  en_keywords: string[];
  fa_count: number;
  en_count: number;
}

export interface WhitelistOut {
  keywords: string[];
  count: number;
}

export interface SourceFeedPreviewItem {
  url: string;
  title: string;
  summary: string | null;
  published_at: string | null;
  passes_whitelist: boolean;
}

export interface SourceTestOut {
  source_id: number;
  source_name: string;
  feed_entries: number;
  latest: SourceFeedPreviewItem | null;
  preview: SourceFeedPreviewItem[];
  new_items_count: number;
  new_items: Array<{ url: string; title: string; language: string }>;
  /** @deprecated use new_items_count */
  items_discovered: number;
  /** @deprecated use new_items */
  items: Array<{ url: string; title: string; language: string }>;
}

export interface SourceTestPipelineOut {
  source_id: number;
  source_name: string;
  picked: SourceFeedPreviewItem;
  news_id: number;
  success: boolean;
  error: string | null;
  news: NewsItem | null;
  pipeline_stages: PipelineStage[] | null;
}
