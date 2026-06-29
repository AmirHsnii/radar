import { createFileRoute } from "@tanstack/react-router";
import {
  Card, Row, Col, Statistic, Table, Tag, Button, Space, Drawer,
  Timeline, Popconfirm, Select, Skeleton,
} from "antd";
import { ReloadOutlined, DeleteOutlined } from "@ant-design/icons";
import { useState } from "react";
import { motion } from "motion/react";
import {
  useDlqList, useDlqStats, useRetryDlq, useDiscardDlq, useRetryAllDlq,
} from "../lib/api/hooks";
import type { DlqItem } from "../lib/api/types";
import { relativeFa } from "../lib/mock/data";

export const Route = createFileRoute("/dlq")({
  head: () => ({ meta: [{ title: "صف خطا · Bitpin Radar" }] }),
  component: DlqPage,
});

const STATUS_COLOR: Record<string, string> = {
  pending: "orange",
  retrying: "blue",
  exhausted: "red",
  discarded: "default",
  resolved: "green",
};

function DlqPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [drawer, setDrawer] = useState<DlqItem | null>(null);
  const [selected, setSelected] = useState<number[]>([]);

  const { data, isLoading } = useDlqList(page, statusFilter);
  const { data: stats } = useDlqStats();
  const retryMut = useRetryDlq();
  const discardMut = useDiscardDlq();
  const retryAllMut = useRetryAllDlq();

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} lg={6}>
          <Card><Statistic title="در انتظار" value={stats?.pending ?? 0} valueStyle={{ color: "#D29922" }} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="در حال retry" value={stats?.retrying ?? 0} valueStyle={{ color: "#177DDC" }} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="خطاهای تمام‌شده" value={stats?.exhausted ?? 0} valueStyle={{ color: "#F85149" }} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="دور انداخته" value={stats?.discarded ?? 0} valueStyle={{ color: "#8B949E" }} /></Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="موارد خطا"
        extra={
          <Space>
            <Select
              placeholder="فیلتر وضعیت"
              allowClear
              style={{ width: 140 }}
              onChange={(v) => { setStatusFilter(v); setPage(1); }}
              options={[
                { value: "pending", label: "در انتظار" },
                { value: "retrying", label: "در حال retry" },
                { value: "exhausted", label: "حداکثر تلاش" },
                { value: "discarded", label: "دور انداخته" },
              ]}
            />
            <Button
              icon={<ReloadOutlined />}
              loading={retryAllMut.isPending}
              onClick={() => retryAllMut.mutate()}
            >
              retry همه pending
            </Button>
          </Space>
        }
      >
        {isLoading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : (
          <Table
            size="small"
            dataSource={data?.items ?? []}
            rowKey="id"
            rowSelection={{
              selectedRowKeys: selected,
              onChange: (k) => setSelected(k as number[]),
            }}
            pagination={{
              current: page,
              pageSize: 20,
              total: data?.total ?? 0,
              onChange: setPage,
              showTotal: (t) => `مجموع: ${t}`,
            }}
            columns={[
              {
                title: "خبر #",
                dataIndex: "news_id",
                width: 80,
                render: (v) => v ? <span style={{ color: "#8B949E" }}>#{v}</span> : "—",
              },
              {
                title: "مرحله",
                dataIndex: "stage",
                width: 120,
                render: (s) => <Tag color="blue">{s}</Tag>,
              },
              {
                title: "پیام خطا",
                dataIndex: "error_message",
                ellipsis: true,
                render: (m) => <span style={{ color: "#8B949E", fontSize: 12 }}>{m}</span>,
              },
              {
                title: "تلاش‌ها",
                width: 90,
                render: (_, r) => `${r.retry_count}/${r.max_retries}`,
              },
              {
                title: "بعدی",
                dataIndex: "next_retry_at",
                width: 130,
                render: (v, r) =>
                  r.retry_count >= r.max_retries
                    ? <Tag color="red">حداکثر</Tag>
                    : v
                    ? <span style={{ fontSize: 12, color: "#8B949E" }}>{relativeFa(v)}</span>
                    : "—",
              },
              {
                title: "وضعیت",
                dataIndex: "status",
                width: 110,
                render: (s) => <Tag color={STATUS_COLOR[s] ?? "default"}>{s}</Tag>,
              },
              {
                title: "عملیات",
                width: 200,
                render: (_, r) => (
                  <Space>
                    <Button size="small" onClick={() => setDrawer(r)}>جزئیات</Button>
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      loading={retryMut.isPending}
                      onClick={() => retryMut.mutate(r.id)}
                    />
                    <Popconfirm title="حذف؟" onConfirm={() => discardMut.mutate({ id: r.id })}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Drawer
        open={!!drawer}
        onClose={() => setDrawer(null)}
        width={600}
        title={`DLQ #${drawer?.id} — خبر #${drawer?.news_id ?? "—"}`}
        placement="left"
      >
        {drawer && (
          <>
            <p>
              <strong>مرحله:</strong> <Tag color="blue">{drawer.stage}</Tag>
              <strong style={{ marginRight: 16 }}>وضعیت:</strong>{" "}
              <Tag color={STATUS_COLOR[drawer.status]}>{drawer.status}</Tag>
            </p>
            <h4>پیام خطا</h4>
            <pre
              style={{
                background: "#0D1117",
                padding: 12,
                borderRadius: 6,
                color: "#F85149",
                whiteSpace: "pre-wrap",
                border: "1px solid #30363D",
                fontSize: 12,
              }}
            >
              {drawer.error_message}
            </pre>
            <h4 style={{ marginTop: 24 }}>تاریخچه retry</h4>
            <Timeline
              items={Array.from({ length: drawer.retry_count }).map((_, i) => ({
                children: `تلاش ${i + 1} — ناموفق`,
                color: "red",
              }))}
            />
            {drawer.next_retry_at && (
              <p style={{ color: "#8B949E" }}>
                بعدی: {new Date(drawer.next_retry_at).toLocaleString("fa-IR")}
              </p>
            )}
            <Space style={{ marginTop: 16 }}>
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                loading={retryMut.isPending}
                onClick={() => retryMut.mutate(drawer.id)}
              >
                retry دستی
              </Button>
              <Popconfirm
                title="مطمئنید؟"
                onConfirm={() => { discardMut.mutate({ id: drawer.id }); setDrawer(null); }}
              >
                <Button danger icon={<DeleteOutlined />}>حذف دائم</Button>
              </Popconfirm>
            </Space>
          </>
        )}
      </Drawer>
    </motion.div>
  );
}
