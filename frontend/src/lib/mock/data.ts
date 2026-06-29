import dayjs from "dayjs";

export type NewsStatus = "pending" | "processing" | "processed" | "published" | "failed";
export type Sentiment = "positive" | "negative" | "neutral";

export interface NewsItem {
  id: string;
  title: string;
  titleFa: string;
  summaryFa: string;
  source: string;
  coins: string[];
  categories: string[];
  sentiment: Sentiment;
  cost: number;
  status: NewsStatus;
  createdAt: string;
  trace: { stage: string; model?: string; tokensIn?: number; tokensOut?: number; cost?: number; duration: number }[];
}

const titles = [
  "Bitcoin breaks $80K as ETF inflows surge",
  "Ethereum Dencun upgrade goes live on mainnet",
  "SEC approves spot Solana ETF filings",
  "Binance launches new launchpool for AI tokens",
  "Ripple wins partial victory in SEC lawsuit",
  "Toncoin overtakes Cardano in market cap",
  "Arbitrum DAO approves $200M ecosystem fund",
  "Coinbase reports record Q3 revenue",
  "Polygon zkEVM hits new TVL milestone",
  "Avalanche partners with major bank for tokenization",
];
const sources = ["CoinDesk", "Cointelegraph", "The Block", "Decrypt", "Bitcoin Magazine"];
const coinPool = ["BTC", "ETH", "SOL", "BNB", "XRP", "TON", "ARB", "MATIC", "AVAX", "ADA"];
const catPool = ["regulation", "defi", "nft", "layer2", "exchange", "macro"];
const statuses: NewsStatus[] = ["published", "processed", "processing", "pending", "failed"];
const sentiments: Sentiment[] = ["positive", "negative", "neutral"];

function pick<T>(arr: T[], n = 1): T[] {
  return [...arr].sort(() => Math.random() - 0.5).slice(0, n);
}

export const mockNews: NewsItem[] = Array.from({ length: 60 }).map((_, i) => {
  const t = titles[i % titles.length];
  return {
    id: `n_${i + 1}`,
    title: t,
    titleFa: "ترجمه فارسی: " + t,
    summaryFa: "این یک خلاصه‌ی نمونه از خبر است که توسط مدل هوش مصنوعی به فارسی ترجمه و تلخیص شده است. شامل اطلاعات کلیدی و تأثیر بازار.",
    source: sources[i % sources.length],
    coins: pick(coinPool, 1 + (i % 3)),
    categories: pick(catPool, 1 + (i % 2)),
    sentiment: sentiments[i % 3],
    cost: +(0.002 + Math.random() * 0.02).toFixed(4),
    status: statuses[i % statuses.length],
    createdAt: dayjs().subtract(i * 17, "minute").toISOString(),
    trace: [
      { stage: "crawl", duration: 320 },
      { stage: "dedup", duration: 45 },
      { stage: "translate", model: "gpt-4o-mini", tokensIn: 850, tokensOut: 420, cost: 0.0034, duration: 1240 },
      { stage: "classify", model: "gpt-4o-mini", tokensIn: 320, tokensOut: 60, cost: 0.0008, duration: 540 },
      { stage: "publish", duration: 210 },
    ],
  };
});

export const mockSources = [
  { id: "s1", name: "CoinDesk", url: "https://www.coindesk.com/arc/outboundfeeds/rss/", lang: "EN", priority: 5, active: true, lastPoll: dayjs().subtract(2, "minute").toISOString(), todayCount: 24 },
  { id: "s2", name: "Cointelegraph", url: "https://cointelegraph.com/rss", lang: "EN", priority: 5, active: true, lastPoll: dayjs().subtract(3, "minute").toISOString(), todayCount: 18 },
  { id: "s3", name: "The Block", url: "https://www.theblock.co/rss.xml", lang: "EN", priority: 4, active: true, lastPoll: dayjs().subtract(5, "minute").toISOString(), todayCount: 12 },
  { id: "s4", name: "ارز دیجیتال", url: "https://arzdigital.com/feed/", lang: "FA", priority: 3, active: true, lastPoll: dayjs().subtract(8, "minute").toISOString(), todayCount: 9 },
  { id: "s5", name: "Decrypt", url: "https://decrypt.co/feed", lang: "EN", priority: 3, active: false, lastPoll: dayjs().subtract(2, "hour").toISOString(), todayCount: 0 },
];

export const mockCostDaily = Array.from({ length: 30 }).map((_, i) => {
  const day = dayjs().subtract(29 - i, "day");
  const daily = +(2 + Math.random() * 4).toFixed(2);
  return { date: day.format("MM-DD"), daily, budget: 5 };
});

export const mockCostByModel = [
  { name: "gpt-4o-mini", value: 42.3 },
  { name: "gpt-4o", value: 28.6 },
  { name: "claude-haiku", value: 15.2 },
  { name: "claude-sonnet", value: 9.8 },
  { name: "gemini-flash", value: 4.1 },
];

export const mockDlq = Array.from({ length: 14 }).map((_, i) => ({
  id: `dlq_${i + 1}`,
  newsTitle: titles[i % titles.length],
  stage: ["crawl", "translate", "classify", "publish"][i % 4],
  errorCode: ["TIMEOUT", "RATE_LIMIT", "INVALID_RESPONSE", "NETWORK"][i % 4],
  message: "Request to upstream provider failed after 30s timeout. Backoff strategy engaged. Retry will occur in next window.",
  attempts: (i % 5) + 1,
  maxAttempts: 5,
  nextRetry: dayjs().add(i * 5, "minute").toISOString(),
  status: ["pending", "retrying", "resolved", "discarded"][i % 4],
}));

export const mockCoins = coinPool.map((c, i) => ({
  symbol: c,
  name: c === "BTC" ? "Bitcoin" : c === "ETH" ? "Ethereum" : c === "SOL" ? "Solana" : c,
  embedded: i < 8,
  updatedAt: dayjs().subtract(i, "day").toISOString(),
}));

export const mockCategories = catPool.map((c, i) => ({
  name: c,
  nameFa: ({ regulation: "قانون‌گذاری", defi: "دیفای", nft: "ان‌اف‌تی", layer2: "لایه ۲", exchange: "صرافی", macro: "ماکرو" } as Record<string, string>)[c],
  description: `Description for ${c}`,
  embedded: i < 5,
}));

export const mockWhitelist = ["بیت‌کوین", "اتریوم", "ارز دیجیتال", "بلاکچین", "صرافی", "کیف پول", "استیبل‌کوین", "توکن", "ماینینگ"];

export const mockSettings = {
  crawler: [
    { key: "poll_interval", label: "بازه polling (ثانیه)", desc: "فاصله زمانی بین هر بار polling منابع", type: "number", value: 60 },
    { key: "timeout", label: "Timeout (ثانیه)", desc: "حداکثر زمان انتظار برای دریافت فید", type: "number", value: 30 },
    { key: "max_content_length", label: "حداکثر طول محتوا", desc: "حداکثر تعداد کاراکتر محتوای خبر", type: "number", value: 10000 },
    { key: "concurrent_fetches", label: "تعداد همزمان", desc: "تعداد درخواست همزمان به منابع", type: "number", value: 5 },
  ],
  ai: [
    { key: "fast_model", label: "مدل سریع", desc: "مدل برای تسک‌های سبک و سریع", type: "select", value: "gpt-4o-mini", options: ["gpt-4o-mini", "claude-haiku", "gemini-flash"] },
    { key: "quality_model", label: "مدل کیفیت بالا", desc: "مدل برای تسک‌های پیچیده", type: "select", value: "gpt-4o", options: ["gpt-4o", "claude-sonnet", "gemini-pro"] },
    { key: "batch_size", label: "اندازه batch", desc: "تعداد خبر در هر batch پردازش", type: "number", value: 10 },
    { key: "summary_max_tokens", label: "حداکثر tokens خلاصه", desc: "محدودیت طول خلاصه تولیدی", type: "number", value: 500 },
  ],
  cost: [
    { key: "monthly_budget", label: "بودجه ماهانه ($)", desc: "سقف هزینه ماهانه", type: "number", value: 150 },
    { key: "alert_threshold", label: "آستانه هشدار (٪)", desc: "درصد بودجه که هشدار ارسال شود", type: "number", value: 80 },
  ],
  publisher: [
    { key: "batch_size", label: "اندازه batch انتشار", desc: "", type: "number", value: 5 },
    { key: "post_status", label: "وضعیت پست", desc: "publish | draft", type: "select", value: "publish", options: ["publish", "draft"] },
  ],
  classifier: [
    { key: "category_threshold", label: "آستانه دسته‌بندی", desc: "حداقل اطمینان برای دسته‌بندی", type: "slider", value: 0.7 },
    { key: "coin_threshold", label: "آستانه شناسایی کوین", desc: "", type: "slider", value: 0.75 },
  ],
  dedup: [
    { key: "window_hours", label: "پنجره زمانی (ساعت)", desc: "بازه بررسی تکراری بودن", type: "number", value: 24 },
    { key: "method", label: "روش", desc: "", type: "select", value: "embedding", options: ["hash", "embedding", "hybrid"] },
  ],
};

export function relativeFa(iso: string) {
  const diff = dayjs().diff(dayjs(iso), "minute");
  if (diff < 1) return "همین الان";
  if (diff < 60) return `${diff} دقیقه پیش`;
  const h = Math.floor(diff / 60);
  if (h < 24) return `${h} ساعت پیش`;
  return `${Math.floor(h / 24)} روز پیش`;
}