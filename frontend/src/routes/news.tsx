import { createFileRoute } from "@tanstack/react-router";
import {
  Card, Table, Tag, Input, Select, DatePicker, Button, Space,
  Drawer, Timeline, Tooltip, Skeleton, Modal, Descriptions, Badge,
  Popconfirm, Typography, Alert,
} from "antd";
import {
  SearchOutlined, EyeOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from "@ant-design/icons";
import { useState } from "react";
import { motion } from "motion/react";
import type { Dayjs } from "dayjs";
import {
  useNewsList, useSources, useCostLogsForNews,
  useNewsWpPreview, useApproveNews, useRejectNews,
} from "../lib/api/hooks";
import type { NewsItem, NewsFilters, PipelineStage, WpPreview, WpPreviewUi } from "../lib/api/types";
import { StatusBadge, CostBadge, SentimentBadge } from "../components/StatusBadge";
import { relativeFa } from "../lib/mock/data";

export const Route = createFileRoute("/news")({
  head: () => ({ meta: [{ title: "اخبار · Bitpin Radar" }] }),
  component: NewsPage,
});

const STAGE_LABELS: Record<string, string> = {
  fetch: "دریافت محتوا",
  route: "تشخیص زبان",
  translate: "ترجمه",
  summarize: "خلاصه‌سازی",
  classify_categories: "دسته‌بندی",
  classify_coins: "تگ کوین",
  sentiment: "سنتیمنت",
  publish: "انتشار وردپرس",
};

function SummaryOnlyTag({ mode }: { mode: string | null | undefined }) {
  if (mode !== "summary_only") return null;
  return (
    <Tooltip title="محتوای صفحه منبع در دسترس نبود — این خبر به‌صورت خودکار و فقط به‌صورت خلاصه تولید شده">
      <Tag color="warning">خلاصه خودکار</Tag>
    </Tooltip>
  );
}

function parsePipelineStages(raw: string | null): PipelineStage[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function normalizeWpPreview(raw: WpPreview | undefined): {
  ui: WpPreviewUi;
  payloadJson: string;
} | null {
  if (!raw) return null;

  if (raw.payload != null) {
    const ui: WpPreviewUi = raw._ui ?? {
      source_name: null,
      source_url: "",
      source_title: null,
      language: null,
      processing_cost_usd: null,
      current_status: "",
    };
    return { ui, payloadJson: JSON.stringify(raw.payload, null, 2) };
  }

  const ui: WpPreviewUi = {
    source_name: null,
    source_url: raw._source_url ?? "",
    source_title: raw._source_title ?? null,
    language: raw._language ?? null,
    processing_cost_usd: raw._processing_cost_usd ?? null,
    current_status: raw._current_status ?? "",
  };
  return { ui, payloadJson: JSON.stringify(raw, null, 2) };
}

function WpPreviewModal({
  newsId,
  open,
  onClose,
}: {
  newsId: number;
  open: boolean;
  onClose: () => void;
}) {
  const { data: preview, isLoading, isError, error } = useNewsWpPreview(open ? newsId : 0);
  const approveMut = useApproveNews();
  const rejectMut = useRejectNews();

  const normalized = normalizeWpPreview(preview);
  const ui = normalized?.ui;
  const payloadJson = normalized?.payloadJson ?? "";

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={760}
      title={
        <Space>
          <Badge color="#00cc85" />
          <span>پیش‌نمایش WordPress — خبر #{newsId}</span>
        </Space>
      }
      footer={
        ui?.current_status === "pending_review" ? (
          <Space>
            <Popconfirm
              title="رد خبر؟ این خبر منتشر نخواهد شد."
              onConfirm={() => { rejectMut.mutate(newsId); onClose(); }}
            >
              <Button danger icon={<CloseCircleOutlined />} loading={rejectMut.isPending}>
                رد خبر
              </Button>
            </Popconfirm>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={approveMut.isPending}
              onClick={() => { approveMut.mutate(newsId); onClose(); }}
            >
              تایید و انتشار در وردپرس
            </Button>
          </Space>
        ) : (
          <Button onClick={onClose}>بستن</Button>
        )
      }
    >
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : isError ? (
        <Alert
          type="error"
          showIcon
          message="خطا در دریافت پیش‌نمایش"
          description={(error as Error)?.message ?? "خطای نامشخص — backend را restart کنید"}
        />
      ) : normalized && ui ? (
        <Space direction="vertical" style={{ width: "100%" }} size="large">
          <Descriptions bordered size="small" column={1} labelStyle={{ width: 140 }}>
            <Descriptions.Item label="منبع">
              <span style={{ color: "#E6EDF3" }}>{ui.source_name ?? "—"}</span>
            </Descriptions.Item>
            <Descriptions.Item label="عنوان اصلی">
              <span style={{ color: "#8B949E" }}>{ui.source_title ?? "—"}</span>
            </Descriptions.Item>
            <Descriptions.Item label="وضعیت">
              <StatusBadge status={ui.current_status} />
            </Descriptions.Item>
            <Descriptions.Item label="هزینه پردازش">
              {ui.processing_cost_usd != null
                ? <CostBadge value={ui.processing_cost_usd} />
                : <span style={{ color: "#8B949E" }}>—</span>}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Text style={{ color: "#8B949E", fontSize: 12 }}>
              JSON خام ارسالی به WordPress (POST /wp-json/wp/v2/posts):
            </Typography.Text>
            <pre
              style={{
                background: "#0D1117",
                border: "1px solid #30363D",
                borderRadius: 6,
                padding: 16,
                marginTop: 8,
                color: "#3FB950",
                fontSize: 12,
                fontFamily: "monospace",
                whiteSpace: "pre-wrap",
                overflowWrap: "break-word",
                direction: "ltr",
                textAlign: "left",
              }}
            >
              {payloadJson}
            </pre>
          </div>
        </Space>
      ) : (
        <span style={{ color: "#8B949E" }}>اطلاعاتی یافت نشد</span>
      )}
    </Modal>
  );
}

function NewsPage() {
  const [filters, setFilters] = useState<NewsFilters>({ page: 1, size: 15 });
  const [draft, setDraft] = useState<NewsFilters>({});
  const [selected, setSelected] = useState<NewsItem | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);

  const { data, isLoading } = useNewsList(filters);
  const { data: sources } = useSources();
  const { data: costLogs } = useCostLogsForNews(selected?.id ?? 0);
  const approveMut = useApproveNews();
  const rejectMut = useRejectNews();

  const applyFilters = () => setFilters({ ...draft, page: 1, size: 15 });

  const handleDates = (_: [Dayjs | null, Dayjs | null] | null, strs: [string, string]) => {
    setDraft((d) => ({ ...d, date_from: strs[0] || undefined, date_to: strs[1] || undefined }));
  };

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card size="small" style={{ marginBottom: 16, position: "sticky", top: 56, zIndex: 5 }}>
        <Space wrap>
          <Input
            placeholder="جستجوی عنوان..."
            prefix={<SearchOutlined />}
            onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value } as NewsFilters))}
            style={{ width: 240 }}
            allowClear
          />
          <Select
            placeholder="وضعیت"
            allowClear
            style={{ width: 160 }}
            onChange={(v) => setDraft((d) => ({ ...d, status: v }))}
            options={[
              { value: "pending", label: "در انتظار" },
              { value: "fetched", label: "محتوا دریافت شده" },
              { value: "translated", label: "ترجمه‌شده" },
              { value: "summarized", label: "خلاصه‌شده" },
              { value: "classified", label: "دسته‌بندی‌شده" },
              { value: "pending_review", label: "⏳ منتظر تایید" },
              { value: "published", label: "منتشرشده" },
              { value: "rejected", label: "رد شده" },
              { value: "failed", label: "ناموفق" },
            ]}
          />
          <Select
            placeholder="منبع"
            allowClear
            style={{ width: 140 }}
            onChange={(v) => setDraft((d) => ({ ...d, source_id: v }))}
            options={(sources ?? []).map((s) => ({ value: s.id, label: s.name }))}
          />
          <Select
            placeholder="زبان"
            allowClear
            style={{ width: 100 }}
            onChange={(v) => setDraft((d) => ({ ...d, language: v }))}
            options={[{ value: "en", label: "EN" }, { value: "fa", label: "FA" }]}
          />
          <DatePicker.RangePicker onChange={handleDates} />
          <Button type="primary" onClick={applyFilters}>اعمال فیلتر</Button>
        </Space>
      </Card>

      <Card size="small">
        {isLoading ? (
          <Skeleton active paragraph={{ rows: 10 }} />
        ) : (
          <Table
            size="small"
            dataSource={data?.items ?? []}
            rowKey="id"
            pagination={{
              current: filters.page,
              pageSize: filters.size ?? 15,
              total: data?.total ?? 0,
              onChange: (page) => setFilters((f) => ({ ...f, page })),
              showTotal: (t) => `مجموع: ${t}`,
            }}
            rowClassName={(r) => r.status === "pending_review" ? "row-pending-review" : ""}
            columns={[
              {
                title: "عنوان",
                ellipsis: true,
                render: (_, r) => <Tooltip title={r.title}>{r.title_fa || r.title}</Tooltip>,
              },
              {
                title: "کوین‌ها",
                dataIndex: "coins_json",
                width: 140,
                render: (v: string | null) => {
                  try {
                    return (JSON.parse(v ?? "[]") as string[]).slice(0, 3).map((c) => (
                      <Tag color="gold" key={c}>{c}</Tag>
                    ));
                  } catch { return null; }
                },
              },
              {
                title: "سنتیمنت",
                dataIndex: "sentiment",
                width: 110,
                render: (s) => s ? <SentimentBadge s={s} /> : null,
              },
              {
                title: "هزینه",
                dataIndex: "processing_cost_usd",
                width: 100,
                render: (v) => v != null ? <CostBadge value={v} /> : <span style={{ color: "#8B949E" }}>—</span>,
              },
              {
                title: "زمان",
                dataIndex: "created_at",
                width: 110,
                render: (v: string) => <span style={{ color: "#8B949E", fontSize: 12 }}>{relativeFa(v)}</span>,
              },
              {
                title: "وضعیت",
                dataIndex: "status",
                width: 180,
                render: (s, r) => (
                  <Space size={4} wrap>
                    <StatusBadge status={s} />
                    <SummaryOnlyTag mode={r.generation_mode} />
                  </Space>
                ),
              },
              {
                title: "عملیات",
                width: 200,
                render: (_, r) => (
                  <Space size={4}>
                    <Button
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={() => setSelected(r)}
                    >
                      جزئیات
                    </Button>
                    <Tooltip title="پیش‌نمایش وردپرس">
                      <Button
                        size="small"
                        type={r.status === "pending_review" ? "primary" : "default"}
                        onClick={() => setPreviewId(r.id)}
                      >
                        {r.status === "pending_review" ? "بررسی" : "پریویو"}
                      </Button>
                    </Tooltip>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      {/* Detail drawer */}
      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        width={600}
        title={selected?.title_fa ?? selected?.title}
        placement="left"
        extra={
          selected?.status === "pending_review" && (
            <Space>
              <Popconfirm title="رد خبر؟" onConfirm={() => { rejectMut.mutate(selected.id); setSelected(null); }}>
                <Button size="small" danger icon={<CloseCircleOutlined />} loading={rejectMut.isPending}>رد</Button>
              </Popconfirm>
              <Button
                size="small"
                type="primary"
                icon={<CheckCircleOutlined />}
                loading={approveMut.isPending}
                onClick={() => { approveMut.mutate(selected.id); setSelected(null); }}
              >
                تایید و انتشار
              </Button>
            </Space>
          )
        }
      >
        {selected && (
          <>
            {selected.generation_mode === "summary_only" && (
              <Alert
                type="warning"
                showIcon
                className="mb-4"
                message="خلاصه خودکار"
                description="این خبر به‌صورت خودکار تولید شده و فقط خلاصه است — متن کامل صفحه منبع در دسترس نبود."
              />
            )}
            <p style={{ color: "#E6EDF3" }}>
              <strong>عنوان اصلی:</strong> {selected.title}
            </p>
            {selected.url && (
              <p>
                <a href={selected.url} target="_blank" rel="noopener" style={{ color: "#388BFD" }}>
                  منبع اصلی ↗
                </a>
              </p>
            )}
            <p style={{ color: "#8B949E", lineHeight: 1.8 }}>{selected.summary_fa}</p>
            <Button
              style={{ marginTop: 12 }}
              onClick={() => { setPreviewId(selected.id); setSelected(null); }}
            >
              مشاهده پیش‌نمایش وردپرس
            </Button>
            {selected.pipeline_stages_json ? (
              <>
                <h4 style={{ marginTop: 24 }}>مراحل Pipeline</h4>
                <Timeline
                  items={parsePipelineStages(selected.pipeline_stages_json).map((s) => ({
                    color: s.status === "ran" || s.status === "queued" ? "green"
                      : s.status === "skipped" ? "gray" : "red",
                    children: (
                      <div>
                        <strong>{STAGE_LABELS[s.stage] ?? s.stage}</strong>
                        <Tag className="mr-2">{s.status}</Tag>
                        {s.reason && (
                          <div style={{ fontSize: 12, color: "#8B949E" }}>دلیل: {s.reason}</div>
                        )}
                        {s.duration_ms != null && (
                          <div style={{ fontSize: 12, color: "#8B949E" }}>{s.duration_ms}ms</div>
                        )}
                      </div>
                    ),
                  }))}
                />
              </>
            ) : (
              <Alert
                className="mt-6"
                type="info"
                showIcon
                message="مراحل pipeline ثبت نشده"
                description="این خبر قبل از به‌روزرسانی پردازش شده. از «تست pipeline» روی منبع دوباره اجرا کنید."
              />
            )}
            {costLogs && costLogs.length > 0 && (
              <>
                <h4 style={{ marginTop: 24 }}>فراخوانی‌های LLM (هزینه)</h4>
                <Typography.Text className="text-[#8B949E] text-xs block mb-2">
                  دسته‌بندی و کوین از embedding هستند و اینجا نمایش داده نمی‌شوند.
                </Typography.Text>
                <Timeline
                  items={costLogs.map((log) => ({
                    children: (
                      <div>
                        <strong>{log.task_name}</strong>
                        <div style={{ fontSize: 12, color: "#8B949E" }}>
                          {log.model} · {log.tokens_in}→{log.tokens_out} tokens · ${log.cost_usd.toFixed(4)}
                        </div>
                      </div>
                    ),
                  }))}
                />
              </>
            )}
          </>
        )}
      </Drawer>

      {/* WP Preview modal */}
      {previewId && (
        <WpPreviewModal
          newsId={previewId}
          open={!!previewId}
          onClose={() => setPreviewId(null)}
        />
      )}
    </motion.div>
  );
}
