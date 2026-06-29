import { createFileRoute } from "@tanstack/react-router";
import {
  Tabs, Card, Table, Button, Tag, Input, Space, Skeleton, Upload, Alert, Radio,
} from "antd";
import { PlusOutlined, ReloadOutlined, CloseOutlined, UploadOutlined, InboxOutlined } from "@ant-design/icons";
import { useState } from "react";
import { motion } from "motion/react";
import {
  useCoins, useCategories, useWhitelist,
  useUpdateWhitelist, useReEmbedCoins, useReEmbedCategories,
  useImportCategories, useImportWhitelist, useImportCoins,
} from "../lib/api/hooks";
import { relativeFa } from "../lib/mock/data";

export const Route = createFileRoute("/data")({
  head: () => ({ meta: [{ title: "مدیریت داده‌ها · Bitpin Radar" }] }),
  component: DataPage,
});

const { Dragger } = Upload;

function CoinsTab() {
  const { data: coins, isLoading } = useCoins();
  const reEmbed = useReEmbedCoins();
  const importMut = useImportCoins();

  return (
    <Card size="small" title="کوین‌ها">
      <Alert
        className="mb-4"
        type="info"
        showIcon
        message="فرمت CSV: symbol, name, aliases"
        description={
          <>
            ستون <strong>aliases</strong> نام‌های جایگزین است (با کاما جدا): مثلاً «بیت‌کوین, Bitcoin, digital gold».
            این نام‌ها در embedding ذخیره می‌شوند تا AI از روی معنا تشخیص دهد خبر درباره کدام کوین است — حتی بدون ذکر نماد.
            از اکسل: Save As → CSV UTF-8.
          </>
        }
      />
      <Dragger
        accept=".csv,.txt"
        showUploadList={false}
        disabled={importMut.isPending}
        beforeUpload={(file) => {
          importMut.mutate(file);
          return false;
        }}
        className="mb-4"
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">فایل CSV کوین‌ها را اینجا رها کنید</p>
        <p className="ant-upload-hint">symbol, name, aliases — هدر اختیاری</p>
      </Dragger>
      <div className="flex justify-end mb-3">
        <Button icon={<ReloadOutlined />} loading={reEmbed.isPending} onClick={() => reEmbed.mutate()}>
          re-embed همه
        </Button>
      </div>
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : (
        <Table
          size="small"
          dataSource={coins ?? []}
          rowKey="id"
          pagination={{ pageSize: 20 }}
          columns={[
            { title: "Symbol", dataIndex: "symbol", width: 90, render: (s) => <Tag color="gold">{s}</Tag> },
            { title: "نام", dataIndex: "name", width: 140 },
            {
              title: "Aliases",
              dataIndex: "aliases",
              ellipsis: true,
              render: (aliases: string[]) =>
                aliases?.length ? (
                  <Space size={4} wrap>
                    {aliases.slice(0, 4).map((a) => (
                      <Tag key={a} color="blue" style={{ margin: 0 }}>{a}</Tag>
                    ))}
                    {aliases.length > 4 && <Tag>+{aliases.length - 4}</Tag>}
                  </Space>
                ) : (
                  <span className="text-[#6E7681] text-xs">—</span>
                ),
            },
            {
              title: "Embedding",
              dataIndex: "has_embedding",
              width: 100,
              render: (e) => (e ? <Tag color="green">✓</Tag> : <Tag color="red">×</Tag>),
            },
            {
              title: "آخرین آپدیت",
              dataIndex: "updated_at",
              width: 120,
              render: (v: string) => <span className="text-[#8B949E] text-xs">{relativeFa(v)}</span>,
            },
          ]}
        />
      )}
    </Card>
  );
}

function CategoriesTab() {
  const { data: categories, isLoading } = useCategories();
  const reEmbed = useReEmbedCategories();
  const importMut = useImportCategories();

  return (
    <Card size="small" title="دسته‌بندی‌ها">
      <Alert
        className="mb-4"
        type="info"
        showIcon
        message="فرمت CSV: name, name_fa, description"
        description="از اکسل: File → Save As → CSV UTF-8. سطر اول می‌تواند هدر باشد. پس از import، embedding خودکار ساخته می‌شود."
      />
      <Dragger
        accept=".csv,.txt"
        showUploadList={false}
        disabled={importMut.isPending}
        beforeUpload={(file) => {
          importMut.mutate(file);
          return false;
        }}
        className="mb-4"
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">فایل CSV دسته‌بندی‌ها را اینجا رها کنید</p>
        <p className="ant-upload-hint">ستون‌ها: name, name_fa, description</p>
      </Dragger>
      <div className="flex justify-end mb-3">
        <Button icon={<ReloadOutlined />} loading={reEmbed.isPending} onClick={() => reEmbed.mutate()}>
          re-embed همه
        </Button>
      </div>
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : (
        <Table
          size="small"
          dataSource={categories ?? []}
          rowKey="id"
          pagination={false}
          columns={[
            { title: "نام", dataIndex: "name" },
            { title: "نام فارسی", dataIndex: "name_fa" },
            { title: "توضیحات", dataIndex: "description", ellipsis: true },
            {
              title: "Embedding",
              dataIndex: "has_embedding",
              width: 110,
              render: (e) => (e ? <Tag color="green">✓</Tag> : <Tag color="red">×</Tag>),
            },
          ]}
        />
      )}
    </Card>
  );
}

function WhitelistSection({
  title,
  description,
  keywords,
  onChange,
  onSave,
  isDirty,
  saving,
  language,
  onImport,
  importing,
}: {
  title: string;
  description: string;
  keywords: string[];
  onChange: (next: string[]) => void;
  onSave: () => void;
  isDirty: boolean;
  saving: boolean;
  language: "fa" | "en";
  onImport: (file: File, mode: "merge" | "replace") => void;
  importing: boolean;
}) {
  const [input, setInput] = useState("");
  const [importMode, setImportMode] = useState<"merge" | "replace">("merge");

  const add = () => {
    if (input && !keywords.includes(input)) {
      onChange([...keywords, input]);
      setInput("");
    }
  };

  const remove = (t: string) => onChange(keywords.filter((x) => x !== t));

  return (
    <Card size="small" title={title} className="mb-4">
      <Alert className="mb-4" type="info" showIcon message={description} />
      <Space className="mb-3">
        <span className="text-[#8B949E] text-sm">حالت import:</span>
        <Radio.Group value={importMode} onChange={(e) => setImportMode(e.target.value)}>
          <Radio.Button value="merge">ادغام</Radio.Button>
          <Radio.Button value="replace">جایگزین</Radio.Button>
        </Radio.Group>
      </Space>
      <Dragger
        accept=".csv,.txt"
        showUploadList={false}
        disabled={importing}
        beforeUpload={(file) => {
          onImport(file, importMode);
          return false;
        }}
        className="mb-4"
      >
        <p className="ant-upload-drag-icon"><UploadOutlined /></p>
        <p className="ant-upload-text">فایل CSV ({language.toUpperCase()}) را آپلود کنید</p>
      </Dragger>
      <div className="flex justify-end mb-3">
        <Button type={isDirty ? "primary" : "default"} loading={saving} onClick={onSave} disabled={!isDirty}>
          ذخیره تغییرات
        </Button>
      </div>
      <Space size={[8, 12]} wrap className="mb-4">
        {keywords.map((t) => (
          <Tag
            key={t}
            closable
            closeIcon={<CloseOutlined />}
            onClose={() => remove(t)}
            color="blue"
            style={{ padding: "4px 12px", fontSize: 14 }}
          >
            {t}
          </Tag>
        ))}
      </Space>
      <Space>
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={add}
          placeholder="کلمه کلیدی جدید + Enter"
          style={{ width: 240 }}
        />
        <Button onClick={add} icon={<PlusOutlined />}>افزودن</Button>
      </Space>
    </Card>
  );
}

function WhitelistTab() {
  const { data: whitelist, isLoading } = useWhitelist();
  const updateMut = useUpdateWhitelist();
  const importMut = useImportWhitelist();
  const [faTags, setFaTags] = useState<string[] | null>(null);
  const [enTags, setEnTags] = useState<string[] | null>(null);

  const faCurrent = faTags ?? whitelist?.fa_keywords ?? [];
  const enCurrent = enTags ?? whitelist?.en_keywords ?? [];
  const isDirty = faTags !== null || enTags !== null;

  const save = () => {
    updateMut.mutate(
      { fa_keywords: faCurrent, en_keywords: enCurrent },
      { onSuccess: () => { setFaTags(null); setEnTags(null); } },
    );
  };

  if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />;

  return (
    <>
      <WhitelistSection
        title="وایت‌لیست فارسی (اجباری)"
        description="اخبار منابع فارسی باید حداقل یکی از این کلمات را در عنوان داشته باشند."
        keywords={faCurrent}
        onChange={setFaTags}
        onSave={save}
        isDirty={isDirty}
        saving={updateMut.isPending}
        language="fa"
        onImport={(file, mode) => importMut.mutate({ file, mode, language: "fa" })}
        importing={importMut.isPending}
      />
      <WhitelistSection
        title="وایت‌لیست انگلیسی (اختیاری)"
        description="اگر خالی باشد، همه اخبار منابع انگلیسی عبور می‌کنند. در غیر این صورت عنوان باید یکی از کلمات را داشته باشد."
        keywords={enCurrent}
        onChange={setEnTags}
        onSave={save}
        isDirty={isDirty}
        saving={updateMut.isPending}
        language="en"
        onImport={(file, mode) => importMut.mutate({ file, mode, language: "en" })}
        importing={importMut.isPending}
      />
    </>
  );
}

function DataPage() {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Tabs
        items={[
          { key: "coins", label: "کوین‌ها", children: <CoinsTab /> },
          { key: "cats", label: "دسته‌بندی‌ها", children: <CategoriesTab /> },
          { key: "wl", label: "وایت‌لیست", children: <WhitelistTab /> },
        ]}
      />
    </motion.div>
  );
}
