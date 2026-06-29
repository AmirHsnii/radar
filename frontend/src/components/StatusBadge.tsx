import { Badge, Tag } from "antd";

const STATUS_MAP: Record<string, { color: string; text: string; processing?: boolean }> = {
  pending:        { color: "default",  text: "در انتظار" },
  fetched:        { color: "cyan",     text: "محتوا دریافت شد" },
  translated:     { color: "geekblue", text: "ترجمه‌شده" },
  summarized:     { color: "blue",     text: "خلاصه‌شده" },
  classified:     { color: "purple",   text: "دسته‌بندی‌شده" },
  pending_review: { color: "orange",   text: "⏳ منتظر تایید" },
  published:      { color: "green",    text: "منتشرشده" },
  rejected:       { color: "red",      text: "رد شده" },
  failed:         { color: "red",      text: "ناموفق" },
  processing:     { color: "blue",     text: "در حال پردازش", processing: true },
};

export function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_MAP[status] ?? { color: "default", text: status };
  if (cfg.processing) return <Badge status="processing" text={cfg.text} />;
  return <Tag color={cfg.color}>{cfg.text}</Tag>;
}

export function CostBadge({ value }: { value: number }) {
  return <Tag color="blue">${value.toFixed(4)}</Tag>;
}

export function SentimentBadge({ s }: { s: string }) {
  if (s === "positive") return <Tag color="green">مثبت</Tag>;
  if (s === "negative") return <Tag color="red">منفی</Tag>;
  return <Tag color="default">خنثی</Tag>;
}
