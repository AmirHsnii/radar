import { createFileRoute } from "@tanstack/react-router";
import {
  Tabs, Card, Input, InputNumber, Select, Slider, Button, Space,
  Skeleton, Tooltip, Alert, Switch, Typography, Row, Col, Tag, Menu,
} from "antd";
import type { MenuProps } from "antd";
import {
  SaveOutlined, UndoOutlined, EyeOutlined, SendOutlined, RobotOutlined,
  GlobalOutlined, ApiOutlined, DollarOutlined, FilterOutlined,
  CloudUploadOutlined, SettingOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { useSettings, useUpdateSetting, useResetSetting, usePromptDefaults } from "../lib/api/hooks";
import type { AppSetting } from "../lib/api/types";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "تنظیمات · Bitpin Radar" }] }),
  component: SettingsPage,
});

// ── Labels ───────────────────────────────────────────────────────────────────

const LABELS: Record<string, string> = {
  "pipeline.manual_review_mode": "تایید دستی قبل از انتشار",
  "publisher.auto_publish": "انتشار خودکار در وردپرس",
  "publisher.wp_batch_size": "تعداد پست در هر batch",
  "crawler.poll_interval_minutes": "فاصله پیش‌فرض پولینگ (دقیقه)",
  "crawler.beat_tick_minutes": "بررسی Beat هر (دقیقه)",
  "crawler.request_timeout_seconds": "تایم‌اوت HTTP",
  "crawler.max_content_length": "حداکثر طول محتوا",
  "crawler.user_agent": "User-Agent",
  "dedup.window_hours": "پنجره dedup (ساعت)",
  "dedup.method": "روش dedup",
  "ai.fast_model": "مدل سریع (پیش‌فرض)",
  "ai.quality_model": "مدل باکیفیت",
  "ai.batch_size": "اندازه batch",
  "ai.max_retries": "حداکثر retry",
  "ai.timeout_seconds": "تایم‌اوت LLM",
  "ai.summary_max_tokens": "حداکثر توکن خلاصه",
  "ai.translation_max_tokens": "حداکثر توکن ترجمه",
  "ai.embedding_model": "مدل Embedding",
  "embedding.base_url": "Base URL",
  "embedding.api_key": "API Key",
  "embedding.cache_ttl_seconds": "TTL کش (ثانیه)",
  "wp.url": "آدرس سایت",
  "wp.username": "نام کاربری",
  "wp.app_password": "Application Password",
  "wp.request_timeout_seconds": "تایم‌اوت HTTP",
  "wp.max_retries": "حداکثر retry",
  "classifier.category_threshold": "آستانه دسته‌بندی",
  "classifier.coin_threshold": "آستانه کوین",
  "classifier.default_category": "دسته پیش‌فرض",
  "classifier.keyword_match_enabled": "تشخیص کوین با کلمه کلیدی",
  "classifier.semantic_enabled": "تشخیص معنایی (Embedding)",
  "classifier.max_classify_chars": "حداکثر کاراکتر طبقه‌بندی",
  "classifier.content_snippet_chars": "طول excerpt محتوا",
  "crawler.bootstrap_on_create_count": "تعداد خبر bootstrap سورس جدید",
  "cost.monthly_budget_usd": "بودجه ماهانه ($)",
  "cost.alert_threshold_pct": "آستانه هشدار (%)",
};

const AGENTS = [
  { name: "translator", label: "ترجمه‌کننده", color: "#177DDC" },
  { name: "summarizer", label: "خلاصه‌ساز", color: "#3FB950" },
  { name: "summarizer_fa", label: "خلاصه‌ساز فارسی (منابع داخلی)", color: "#2EA043" },
  { name: "sentiment", label: "احساسات", color: "#D29922" },
  { name: "router", label: "تشخیص زبان", color: "#A371F7" },
] as const;

const TAB_KEYS = ["publish", "crawler", "ai", "agents", "embedding", "wordpress", "classifier", "cost"] as const;
type TabKey = (typeof TAB_KEYS)[number];

function labelFor(key: string) {
  return LABELS[key] ?? key.split(".").pop() ?? key;
}

function inferControl(setting: AppSetting) {
  const { value_type, key } = setting;
  if (value_type === "bool") return "bool";
  if (value_type === "secret") return "secret";
  if (value_type === "text") return "textarea";
  if (value_type === "float" && key.includes("threshold")) return "slider";
  if (value_type === "int") return "number";
  return "text";
}

function settingsForTab(tab: TabKey, all: AppSetting[]): AppSetting[] {
  const pick = (prefixes: string[]) =>
    all.filter((s) => prefixes.some((p) => s.key.startsWith(p)));

  switch (tab) {
    case "publish":
      return all.filter((s) => s.key.startsWith("pipeline.") || s.key.startsWith("publisher."));
    case "crawler":
      return all.filter((s) =>
        (s.key.startsWith("crawler.") &&
          !s.key.startsWith("crawler.whitelist_keywords")) ||
        s.key.startsWith("dedup."),
      );
    case "ai":
      return all.filter((s) => s.key.startsWith("ai.") && s.key !== "ai.embedding_model");
    case "agents":
      return [];
    case "embedding":
      return all.filter((s) => s.key === "ai.embedding_model" || s.key.startsWith("embedding."));
    case "wordpress":
      return all.filter((s) => s.key.startsWith("wp."));
    case "classifier":
      return all.filter((s) => s.key.startsWith("classifier."));
    case "cost":
      return all.filter((s) => s.key.startsWith("cost."));
    default:
      return [];
  }
}

// ── Shared components ────────────────────────────────────────────────────────

function SettingRow({ item }: { item: AppSetting }) {
  const [val, setVal] = useState(item.value);
  const updateMut = useUpdateSetting();
  const resetMut = useResetSetting();
  const control = inferControl(item);
  const isDirty = val !== item.value;

  useEffect(() => setVal(item.value), [item.value]);

  return (
    <div className="flex items-start gap-4 py-3 border-b border-[#21262D] last:border-0">
      <div className="flex-1 min-w-0">
        <div className="text-[#E6EDF3] font-medium">{labelFor(item.key)}</div>
        {item.description && (
          <div className="text-[#8B949E] text-xs mt-0.5">{item.description}</div>
        )}
      </div>
      <div className="w-56 shrink-0">
        {control === "number" && (
          <InputNumber value={Number(val)} onChange={(v) => setVal(String(v ?? 0))} className="w-full" />
        )}
        {control === "text" && <Input value={val} onChange={(e) => setVal(e.target.value)} />}
        {control === "secret" && (
          <Input.Password value={val} onChange={(e) => setVal(e.target.value)} visibilityToggle />
        )}
        {control === "bool" && (
          <Select
            value={val}
            onChange={setVal}
            className="w-full"
            options={[
              { value: "true", label: "فعال" },
              { value: "false", label: "غیرفعال" },
            ]}
          />
        )}
        {control === "slider" && (
          <Slider value={parseFloat(val)} min={0} max={1} step={0.05} onChange={(v) => setVal(String(v))} />
        )}
      </div>
      <Space size={4}>
        <Button
          size="small"
          icon={<SaveOutlined />}
          type={isDirty ? "primary" : "default"}
          loading={updateMut.isPending}
          onClick={() => updateMut.mutate({ key: item.key, value: String(val) })}
        />
        <Tooltip title="بازنشانی پیش‌فرض">
          <Button size="small" icon={<UndoOutlined />} loading={resetMut.isPending} onClick={() => resetMut.mutate(item.key)} />
        </Tooltip>
      </Space>
    </div>
  );
}

function SettingsGroup({ title, desc, items }: { title: string; desc?: string; items: AppSetting[] }) {
  if (!items.length) return null;
  return (
    <Card size="small" title={title} className="mb-4">
      {desc && <Typography.Text className="text-[#8B949E] text-xs block mb-3">{desc}</Typography.Text>}
      {items.map((it) => <SettingRow key={it.key} item={it} />)}
    </Card>
  );
}

function PromptEditor({
  agent,
  allSettings,
  defaultPrompt,
}: {
  agent: typeof AGENTS[number];
  allSettings: AppSetting[];
  defaultPrompt: string;
}) {
  const key = `agent.${agent.name}.prompt`;
  const setting = allSettings.find((s) => s.key === key);
  const stored = (setting?.value ?? "").trim();
  const isUsingDefault = !stored;
  const [val, setVal] = useState(stored || defaultPrompt);
  const updateMut = useUpdateSetting();
  const resetMut = useResetSetting();
  const isDirty = isUsingDefault ? val !== defaultPrompt : val !== stored;

  useEffect(() => {
    const s = (setting?.value ?? "").trim();
    setVal(s || defaultPrompt);
  }, [setting?.value, defaultPrompt]);

  const handleSave = () => {
    const trimmed = val.trim();
    const toSave = trimmed === defaultPrompt.trim() ? "" : trimmed;
    updateMut.mutate({ key, value: toSave });
  };

  const handleReset = () => {
    resetMut.mutate(key);
    setVal(defaultPrompt);
  };

  return (
    <Card
      size="small"
      className="mb-4"
      style={{ borderLeft: `3px solid ${agent.color}` }}
      title={
        <Space>
          <strong>{agent.label}</strong>
          <Tag>{key}</Tag>
          {isUsingDefault && <Tag color="blue">پیش‌فرض سیستم</Tag>}
        </Space>
      }
      extra={
        <Space>
          <Button size="small" icon={<UndoOutlined />} onClick={handleReset} loading={resetMut.isPending}>
            پیش‌فرض
          </Button>
          <Button
            size="small"
            type={isDirty ? "primary" : "default"}
            icon={<SaveOutlined />}
            loading={updateMut.isPending}
            onClick={handleSave}
          >
            ذخیره
          </Button>
        </Space>
      }
    >
      <Typography.Text className="text-[#8B949E] text-xs block mb-2">
        متن زیر پرامپت فعال است. با «پیش‌فرض» یا ذخیرهٔ همان متن پیش‌فرض، از template سیستم استفاده می‌شود.
      </Typography.Text>
      <Input.TextArea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        rows={12}
        style={{ fontFamily: "monospace", fontSize: 13 }}
      />
    </Card>
  );
}

function AgentSettingField({
  item,
  globalModel,
}: {
  item: AppSetting;
  globalModel: string;
}) {
  const [val, setVal] = useState(item.value);
  const updateMut = useUpdateSetting();
  const resetMut = useResetSetting();
  const isDirty = val !== item.value;
  const field = item.key.split(".").pop() ?? "";
  const isSecret = item.value_type === "secret";

  const labels: Record<string, string> = {
    model: "مدل",
    base_url: "Base URL",
    api_key: "API Key",
  };
  const placeholders: Record<string, string> = {
    model: `خالی = ${globalModel}`,
    base_url: "خالی = OpenRouter",
    api_key: "خالی = کلید سراسری",
  };

  useEffect(() => setVal(item.value), [item.value]);

  return (
    <div className="mb-4 last:mb-0">
      <Typography.Text className="text-[#8B949E] text-xs block mb-1.5">
        {labels[field] ?? field}
      </Typography.Text>
      <div className="flex gap-2">
        {isSecret ? (
          <Input.Password
            className="flex-1"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={placeholders[field]}
            visibilityToggle
          />
        ) : (
          <Input
            className="flex-1"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder={placeholders[field]}
          />
        )}
        <Button
          icon={<SaveOutlined />}
          type={isDirty ? "primary" : "default"}
          loading={updateMut.isPending}
          onClick={() => updateMut.mutate({ key: item.key, value: val })}
        />
        <Tooltip title="بازنشانی">
          <Button
            icon={<UndoOutlined />}
            loading={resetMut.isPending}
            onClick={() => resetMut.mutate(item.key)}
          />
        </Tooltip>
      </div>
    </div>
  );
}

function AgentModelsTab({ allSettings }: { allSettings: AppSetting[] }) {
  const globalModel = allSettings.find((s) => s.key === "ai.fast_model")?.value ?? "google/gemini-flash-1.5";

  return (
    <>
      <Typography.Paragraph className="text-[#8B949E] text-sm mb-4">
        هر ایجنت می‌تواند مدل و endpoint جدا داشته باشد. فیلدهای خالی از تنظیمات سراسری استفاده می‌کنند.
      </Typography.Paragraph>
      <Row gutter={[16, 16]}>
        {AGENTS.filter((a) => a.name !== "router").map((agent) => (
          <Col xs={24} xl={12} key={agent.name}>
            <Card
              size="small"
              styles={{ body: { paddingTop: 12 } }}
              title={
                <Space>
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: agent.color }}
                  />
                  <span className="font-semibold">{agent.label}</span>
                </Space>
              }
            >
              {(["model", "base_url", "api_key"] as const).map((field) => {
                const key = `agent.${agent.name}.${field}`;
                const s = allSettings.find((x) => x.key === key);
                if (!s) return null;
                return (
                  <AgentSettingField
                    key={key}
                    item={s}
                    globalModel={globalModel}
                  />
                );
              })}
            </Card>
          </Col>
        ))}
        <Col xs={24}>
          <Alert
            type="info"
            showIcon
            message="ایجنت Router (تشخیص زبان) از مدل سریع سراسری استفاده می‌کند. پرامپت آن در تب «پرامپت‌ها» قابل ویرایش است."
          />
        </Col>
      </Row>
    </>
  );
}

function PublishTab({ allSettings }: { allSettings: AppSetting[] }) {
  const updateMut = useUpdateSetting();
  const review = allSettings.find((s) => s.key === "pipeline.manual_review_mode");
  const autoPub = allSettings.find((s) => s.key === "publisher.auto_publish");
  const isManual = review?.value === "true";
  const isAuto = autoPub?.value === "true";

  return (
    <>
      <Alert
        className="mb-4"
        type={isManual ? "warning" : "success"}
        showIcon
        icon={isManual ? <EyeOutlined /> : <SendOutlined />}
        message={
          <div className="flex justify-between items-center w-full">
            <div>
              <div className="font-semibold">{isManual ? "حالت تست — تایید دستی" : "انتشار مستقیم"}</div>
              <div className="text-xs text-[#8B949E]">
                {isManual
                  ? "اخبار پس از پردازش منتظر تایید شما می‌مانند."
                  : "اخبار (در صورت فعال بودن auto_publish) مستقیم منتشر می‌شوند."}
              </div>
            </div>
            <Switch
              checked={isManual}
              onChange={(v) => {
                updateMut.mutate({ key: "pipeline.manual_review_mode", value: String(v) });
                if (v && isAuto) updateMut.mutate({ key: "publisher.auto_publish", value: "false" });
              }}
              checkedChildren="تست"
              unCheckedChildren="مستقیم"
            />
          </div>
        }
      />
      <SettingsGroup title="انتشار" items={settingsForTab("publish", allSettings)} />
    </>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

function SettingsPage() {
  const { data: settings, isLoading } = useSettings();
  const { data: promptDefaults, isLoading: promptsLoading } = usePromptDefaults();
  const [tab, setTab] = useState<TabKey>("publish");

  const allSettings = settings ?? [];

  const menuItems: MenuProps["items"] = useMemo(() => [
    { key: "publish", icon: <SendOutlined />, label: "انتشار" },
    { key: "crawler", icon: <GlobalOutlined />, label: "کراولر" },
    { key: "ai", icon: <ThunderboltOutlined />, label: "مدل‌های AI" },
    { key: "agents", icon: <RobotOutlined />, label: "ایجنت‌ها" },
    { key: "embedding", icon: <ApiOutlined />, label: "Embedding" },
    { key: "wordpress", icon: <CloudUploadOutlined />, label: "WordPress" },
    { key: "classifier", icon: <FilterOutlined />, label: "دسته‌بندی" },
    { key: "cost", icon: <DollarOutlined />, label: "هزینه" },
  ], []);

  if (isLoading || promptsLoading) {
    return (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <Skeleton active paragraph={{ rows: 12 }} />
      </motion.div>
    );
  }

  const tabContent: Record<TabKey, ReactNode> = {
    publish: <PublishTab allSettings={allSettings} />,
    crawler: (
      <SettingsGroup
        title="کراولر و Dedup"
        desc="فاصله پیش‌فرض پولینگ برای منابعی است که interval اختصاصی ندارند. interval هر منبع از صفحه «منابع» تنظیم می‌شود."
        items={settingsForTab("crawler", allSettings)}
      />
    ),
    ai: <SettingsGroup title="مدل‌های سراسری" items={settingsForTab("ai", allSettings)} />,
    agents: (
      <Tabs
        destroyInactiveTabPane={false}
        items={[
          {
            key: "models",
            label: "مدل و API",
            children: <AgentModelsTab allSettings={allSettings} />,
          },
          {
            key: "prompts",
            label: "پرامپت‌ها",
            children: (
              <>
                <Typography.Paragraph className="text-[#8B949E] text-sm mb-4">
                  پرامپت سیستم هر ایجنت را ویرایش کنید. خالی = استفاده از پرامپت پیش‌فرض.
                </Typography.Paragraph>
                {AGENTS.map((a) => (
                  <PromptEditor
                    key={a.name}
                    agent={a}
                    allSettings={allSettings}
                    defaultPrompt={promptDefaults?.[a.name] ?? ""}
                  />
                ))}
              </>
            ),
          },
        ]}
      />
    ),
    embedding: (
      <SettingsGroup
        title="پیکربندی Embedding"
        desc="پس از تغییر مدل یا endpoint، از صفحه «داده‌ها» re-embed کنید."
        items={settingsForTab("embedding", allSettings)}
      />
    ),
    wordpress: (
      <SettingsGroup
        title="اتصال WordPress"
        desc="خالی = استفاده از مقادیر .env"
        items={settingsForTab("wordpress", allSettings)}
      />
    ),
    classifier: (
      <SettingsGroup
        title="طبقه‌بندی و تگ کوین"
        desc="تشخیص کوین: ابتدا کلمه کلیدی (symbol/name/alias)، سپس embedding. متن طبقه‌بندی = عنوان فارسی + خلاصه + excerpt محتوا."
        items={settingsForTab("classifier", allSettings)}
      />
    ),
    cost: <SettingsGroup title="بودجه و هشدار هزینه" items={settingsForTab("cost", allSettings)} />,
  };

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex gap-4 items-start">
        <Card size="small" className="w-48 shrink-0 sticky top-4" styles={{ body: { padding: 8 } }}>
          <div className="flex items-center gap-2 px-2 py-2 mb-1">
            <SettingOutlined className="text-[#00cc85]" />
            <Typography.Text strong>تنظیمات</Typography.Text>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[tab]}
            items={menuItems}
            onClick={({ key }) => setTab(key as TabKey)}
            style={{ border: "none", background: "transparent" }}
          />
        </Card>
        <div className="flex-1 min-w-0">{tabContent[tab]}</div>
      </div>
    </motion.div>
  );
}
