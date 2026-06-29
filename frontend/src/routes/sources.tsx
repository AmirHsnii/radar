import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Card, Table, Button, Switch, Tag, Modal, Form, Input, InputNumber,
  Select, Slider, Space, Skeleton, Popconfirm, Typography, List, Alert,
  Divider, Timeline,
} from "antd";
import { PlusOutlined, ExperimentOutlined, EditOutlined, DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useState } from "react";
import { motion } from "motion/react";
import {
  useSources, useCreateSource, useUpdateSource, useDeleteSource,
  useToggleSource, useTestSource, useTestSourcePipeline,
} from "../lib/api/hooks";
import type { Source, SourceCreate, SourceTestOut, SourceTestPipelineOut, PipelineStage } from "../lib/api/types";
import { StatusBadge, SentimentBadge } from "../components/StatusBadge";
import { relativeFa } from "../lib/mock/data";

export const Route = createFileRoute("/sources")({
  head: () => ({ meta: [{ title: "منابع · Bitpin Radar" }] }),
  component: SourcesPage,
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

function stageColor(status: PipelineStage["status"]) {
  if (status === "ran" || status === "queued") return "green";
  if (status === "skipped") return "default";
  return "red";
}

function PipelineStagesTimeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <Timeline
      items={stages.map((s) => ({
        color: stageColor(s.status),
        children: (
          <div>
            <strong>{STAGE_LABELS[s.stage] ?? s.stage}</strong>
            <Tag className="mr-2" color={stageColor(s.status)}>{s.status}</Tag>
            {s.reason && (
              <Typography.Text className="text-[#8B949E] text-xs block">
                دلیل: {s.reason}
              </Typography.Text>
            )}
            {s.duration_ms != null && (
              <Typography.Text className="text-[#8B949E] text-xs block">
                {s.duration_ms}ms
              </Typography.Text>
            )}
          </div>
        ),
      }))}
    />
  );
}

function SourceTestModal({
  open,
  result,
  loading,
  sourceId,
  pipelineResult,
  pipelineLoading,
  onRunPipeline,
  onClose,
}: {
  open: boolean;
  result: SourceTestOut | null;
  loading: boolean;
  sourceId: number | null;
  pipelineResult: SourceTestPipelineOut | null;
  pipelineLoading: boolean;
  onRunPipeline: () => void;
  onClose: () => void;
}) {
  const parseJsonArray = (raw: string | null) => {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const canRunPipeline = result?.latest?.passes_whitelist ?? false;

  return (
    <Modal
      open={open}
      title={result ? `تست منبع: ${result.source_name}` : "تست منبع RSS"}
      onCancel={onClose}
      footer={<Button onClick={onClose}>بستن</Button>}
      width={720}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : !result ? null : result.feed_entries === 0 ? (
        <Alert type="warning" showIcon message="فید خالی است یا قابل parse نیست." />
      ) : (
        <>
          {result.latest && (
            <Alert
              className="mb-4"
              type="success"
              showIcon
              message="آخرین خبر فید"
              description={
                <div>
                  <Typography.Text strong className="block mb-1">
                    {result.latest.title}
                  </Typography.Text>
                  {result.latest.summary && (
                    <Typography.Paragraph className="text-[#8B949E] text-sm mb-2" ellipsis={{ rows: 3 }}>
                      {result.latest.summary}
                    </Typography.Paragraph>
                  )}
                  <Space wrap size={8}>
                    <a href={result.latest.url} target="_blank" rel="noopener noreferrer">
                      مشاهده لینک
                    </a>
                    {result.latest.published_at && (
                      <Tag>{relativeFa(result.latest.published_at)}</Tag>
                    )}
                    {result.latest.passes_whitelist ? (
                      <Tag color="green">وایت‌لیست ✓</Tag>
                    ) : (
                      <Tag color="red">وایت‌لیست ×</Tag>
                    )}
                  </Space>
                </div>
              }
            />
          )}

          {sourceId && result.latest && (
            <div className="mb-4">
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={pipelineLoading}
                disabled={!canRunPipeline}
                onClick={onRunPipeline}
                block
              >
                {pipelineLoading
                  ? "در حال پردازش AI (ممکن است ۱–۲ دقیقه طول بکشد)..."
                  : "اجرای pipeline روی آخرین خبر"}
              </Button>
              <Typography.Text className="text-[#8B949E] text-xs block mt-2">
                آخرین خبر را در دیتابیس ذخیره می‌کند، ترجمه/خلاصه/دسته‌بندی انجام می‌دهد و در صفحه اخبار نمایش می‌دهد.
              </Typography.Text>
            </div>
          )}

          {pipelineResult && (
            <>
              <Divider />
              {pipelineResult.success && pipelineResult.news ? (
                <Alert
                  type="success"
                  showIcon
                  message={`پردازش موفق — خبر #${pipelineResult.news_id}`}
                  description={
                    <div className="mt-2">
                      <Space className="mb-2">
                        <StatusBadge status={pipelineResult.news.status} />
                        {pipelineResult.news.sentiment && (
                          <SentimentBadge s={pipelineResult.news.sentiment} />
                        )}
                      </Space>
                      <Typography.Text strong className="block mb-1">
                        {pipelineResult.news.title_fa || pipelineResult.news.title}
                      </Typography.Text>
                      {pipelineResult.news.summary_fa && (
                        <Typography.Paragraph className="text-sm mb-2">
                          {pipelineResult.news.summary_fa}
                        </Typography.Paragraph>
                      )}
                      <Space wrap size={6} className="mb-2">
                        {parseJsonArray(pipelineResult.news.coins_json).map((c: string) => (
                          <Tag key={c} color="gold">{c}</Tag>
                        ))}
                        {parseJsonArray(pipelineResult.news.categories_json).map((c: string) => (
                          <Tag key={c}>{c}</Tag>
                        ))}
                      </Space>
                      {pipelineResult.pipeline_stages && pipelineResult.pipeline_stages.length > 0 && (
                        <div className="mt-3">
                          <Typography.Text className="text-[#8B949E] text-xs block mb-2">
                            مراحل pipeline:
                          </Typography.Text>
                          <PipelineStagesTimeline stages={pipelineResult.pipeline_stages} />
                        </div>
                      )}
                      <Link to="/news">
                        <Button type="link" size="small" className="p-0">
                          مشاهده در صفحه اخبار →
                        </Button>
                      </Link>
                    </div>
                  }
                />
              ) : (
                <Alert
                  type="error"
                  showIcon
                  message="پردازش ناموفق"
                  description={pipelineResult.error || "خطای نامشخص"}
                />
              )}
            </>
          )}

          <Typography.Text className="text-[#8B949E] text-sm block mb-2 mt-4">
            {result.new_items_count} خبر جدید (بدون تکرار) · {result.feed_entries} خبر در پیش‌نمایش فید
          </Typography.Text>
          <List
            size="small"
            bordered
            dataSource={result.preview}
            renderItem={(item, idx) => (
              <List.Item>
                <div className="w-full">
                  <Space className="mb-1">
                    <Tag>{idx === 0 ? "آخرین" : `#${idx + 1}`}</Tag>
                    {!item.passes_whitelist && <Tag color="red">فیلتر وایت‌لیست</Tag>}
                  </Space>
                  <Typography.Text strong className="block">{item.title}</Typography.Text>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[#8B949E]"
                  >
                    {item.url}
                  </a>
                </div>
              </List.Item>
            )}
          />
        </>
      )}
    </Modal>
  );
}

function pollStatusTag(status: string | null) {
  if (!status) return null;
  const map: Record<string, { color: string; label: string }> = {
    success: { color: "green", label: "موفق" },
    empty: { color: "default", label: "بدون خبر جدید" },
    error: { color: "red", label: "خطا" },
  };
  const info = map[status] ?? { color: "default", label: status };
  return <Tag color={info.color} style={{ margin: 0 }}>{info.label}</Tag>;
}

function pollIntervalMinutes(source: Source, defaultMin = 2) {
  return source.poll_interval_minutes ?? defaultMin;
}

function isPollStale(source: Source, defaultMin = 2) {
  if (!source.is_active || !source.last_polled_at) return !source.last_polled_at;
  const ageMs = Date.now() - new Date(source.last_polled_at).getTime();
  return ageMs > pollIntervalMinutes(source, defaultMin) * 60_000 * 2;
}

function PollSummary({ source }: { source: Source }) {
  const stale = isPollStale(source);
  return (
    <div className="leading-snug">
      <div className="flex items-center gap-1 flex-wrap">
        <Typography.Text style={{ fontSize: 12, color: stale ? "#faad14" : "#8B949E" }}>
          {source.last_polled_at ? relativeFa(source.last_polled_at) : "هرگز"}
        </Typography.Text>
        {stale && (
          <Tooltip title="آخرین پول از فاصله تنظیم‌شده گذشته — احتمالاً Celery Beat متوقف است">
            <Tag color="warning" style={{ margin: 0, fontSize: 11 }}>تأخیر</Tag>
          </Tooltip>
        )}
      </div>
      {source.last_poll_status && (
        <div className="mt-1 flex items-center gap-1 flex-wrap">
          {pollStatusTag(source.last_poll_status)}
          {source.last_poll_new_items != null && source.last_poll_new_items > 0 && (
            <Tag color="cyan" style={{ margin: 0 }}>+{source.last_poll_new_items}</Tag>
          )}
        </div>
      )}
      {source.last_poll_message && (
        <Tooltip title={source.last_poll_message}>
          <Typography.Text
            ellipsis
            className="block mt-0.5"
            style={{ fontSize: 11, color: "#6e7681", maxWidth: 160 }}
          >
            {source.last_poll_message}
          </Typography.Text>
        </Tooltip>
      )}
    </div>
  );
}

function SourcesPage() {
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<Source | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [testResult, setTestResult] = useState<SourceTestOut | null>(null);
  const [testSourceId, setTestSourceId] = useState<number | null>(null);
  const [pipelineResult, setPipelineResult] = useState<SourceTestPipelineOut | null>(null);
  const [form] = Form.useForm();

  const { data: sources, isLoading } = useSources({ refetchInterval: 15_000 });
  const createMut = useCreateSource();
  const updateMut = useUpdateSource();
  const deleteMut = useDeleteSource();
  const toggleMut = useToggleSource();
  const testMut = useTestSource();
  const pipelineMut = useTestSourcePipeline();

  const openEdit = (s: Source) => {
    setEditItem(s);
    form.setFieldsValue({
      name: s.name,
      rss_url: s.rss_url,
      site_url: s.site_url,
      language: s.language,
      priority: s.priority,
      is_active: s.is_active,
      poll_interval_minutes: s.poll_interval_minutes,
    });
    setAddOpen(true);
  };

  const handleSave = async () => {
    const vals = await form.validateFields();
    if (editItem) {
      await updateMut.mutateAsync({ id: editItem.id, data: vals });
    } else {
      await createMut.mutateAsync(vals as SourceCreate);
    }
    setAddOpen(false);
    setEditItem(null);
    form.resetFields();
  };

  const handleTest = async (source: Source) => {
    setTestOpen(true);
    setTestResult(null);
    setPipelineResult(null);
    setTestSourceId(source.id);
    try {
      const data = await testMut.mutateAsync(source.id);
      setTestResult(data);
    } catch {
      setTestOpen(false);
      setTestSourceId(null);
    }
  };

  const handleRunPipeline = async () => {
    if (!testSourceId) return;
    setPipelineResult(null);
    try {
      const data = await pipelineMut.mutateAsync(testSourceId);
      setPipelineResult(data);
    } catch {
      // error toast handled by hook
    }
  };

  const staleCount = (sources ?? []).filter((s) => s.is_active && isPollStale(s)).length;

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      {staleCount > 0 && (
        <Alert
          className="mb-3"
          type="warning"
          showIcon
          message={`${staleCount} منبع فعال مدتی پول نشده‌اند`}
          description="سرویس celery_beat را بررسی کنید: sudo docker compose ps celery_beat && sudo docker compose logs celery_beat --tail 30"
        />
      )}
      <Card
        size="small"
        title="مدیریت منابع RSS"
        extra={
          <Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {(sources ?? []).filter((s) => s.is_active).length} منبع فعال
            </Typography.Text>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => { setEditItem(null); form.resetFields(); setAddOpen(true); }}
            >
              افزودن منبع
            </Button>
          </Space>
        }
      >
        {isLoading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : (
          <Table
            size="small"
            dataSource={sources ?? []}
            rowKey="id"
            pagination={false}
            scroll={{ x: 980 }}
            columns={[
              {
                title: "منبع",
                key: "name",
                fixed: "left",
                width: 220,
                render: (_, r) => (
                  <div>
                    <Typography.Text strong>{r.name}</Typography.Text>
                    <div>
                      <a
                        href={r.rss_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: 11, color: "#6e7681" }}
                      >
                        {r.rss_url.replace(/^https?:\/\//, "").slice(0, 42)}…
                      </a>
                    </div>
                  </div>
                ),
              },
              {
                title: "تنظیمات",
                key: "meta",
                width: 120,
                render: (_, r) => (
                  <Space direction="vertical" size={2}>
                    <Tag color={r.language?.toLowerCase() === "fa" ? "magenta" : "blue"} style={{ margin: 0 }}>
                      {r.language?.toUpperCase()}
                    </Tag>
                    <Typography.Text style={{ fontSize: 11, color: "#8B949E" }}>
                      هر {pollIntervalMinutes(r)} دقیقه
                    </Typography.Text>
                    <Tag style={{ margin: 0 }}>اولویت {r.priority}</Tag>
                  </Space>
                ),
              },
              {
                title: "آخرین پول",
                key: "poll",
                width: 200,
                render: (_, r) => <PollSummary source={r} />,
              },
              {
                title: "فعال",
                dataIndex: "is_active",
                width: 70,
                align: "center",
                render: (a, r) => (
                  <Switch
                    checked={a}
                    size="small"
                    loading={toggleMut.isPending}
                    onChange={() => toggleMut.mutate(r.id)}
                  />
                ),
              },
              {
                title: "عملیات",
                key: "actions",
                width: 120,
                fixed: "right",
                align: "center",
                render: (_, r) => (
                  <Space size={4}>
                    <Tooltip title="ویرایش">
                      <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
                    </Tooltip>
                    <Tooltip title="تست فید">
                      <Button size="small" icon={<ExperimentOutlined />} onClick={() => handleTest(r)} />
                    </Tooltip>
                    <Popconfirm title="حذف منبع؟" onConfirm={() => deleteMut.mutate(r.id)}>
                      <Tooltip title="حذف">
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Tooltip>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal
        open={addOpen}
        title={editItem ? "ویرایش منبع" : "افزودن منبع"}
        onCancel={() => { setAddOpen(false); setEditItem(null); form.resetFields(); }}
        onOk={handleSave}
        confirmLoading={createMut.isPending || updateMut.isPending}
        okText="ذخیره"
        cancelText="انصراف"
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item name="name" label="نام" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="rss_url" label="RSS URL" rules={[{ required: true, type: "url" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="site_url" label="Site URL">
            <Input />
          </Form.Item>
          <Form.Item name="language" label="زبان" initialValue="en">
            <Select options={[{ value: "en", label: "English" }, { value: "fa", label: "فارسی" }]} />
          </Form.Item>
          <Form.Item name="priority" label="اولویت (۱–۱۰)" initialValue={5}>
            <Slider min={1} max={10} marks={{ 1: "۱", 5: "۵", 10: "۱۰" }} />
          </Form.Item>
          <Form.Item name="poll_interval_minutes" label="فاصله پولینگ (دقیقه)">
            <InputNumber min={1} max={1440} placeholder="پیش‌فرض سیستم" style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="is_active" label="فعال" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <SourceTestModal
        open={testOpen}
        result={testResult}
        loading={testMut.isPending}
        sourceId={testSourceId}
        pipelineResult={pipelineResult}
        pipelineLoading={pipelineMut.isPending}
        onRunPipeline={handleRunPipeline}
        onClose={() => { setTestOpen(false); setTestResult(null); setPipelineResult(null); setTestSourceId(null); }}
      />
    </motion.div>
  );
}
