import { createFileRoute } from "@tanstack/react-router";
import { Row, Col, Card, Statistic, Table, Tag, Drawer, Timeline, Skeleton, Alert } from "antd";
import {
  ArrowUpOutlined,
  DollarOutlined,
  WarningOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { motion } from "motion/react";
import { useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { useNewsList, useNewsStats, useCostLogsForNews, useCostsWeekly } from "../lib/api/hooks";
import type { NewsItem } from "../lib/api/types";
import { StatusBadge } from "../components/StatusBadge";
import { PipelineFlow } from "../components/PipelineFlow";
import { relativeFa } from "../lib/mock/data";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "داشبورد · Bitpin Radar" }] }),
  component: Dashboard,
});

function Dashboard() {
  const [selected, setSelected] = useState<NewsItem | null>(null);

  const { data: stats } = useNewsStats();
  const { data: newsList, isLoading: newsLoading } = useNewsList({ page: 1, size: 12 });
  const { data: weekly } = useCostsWeekly();
  const { data: costLogs } = useCostLogsForNews(selected?.id ?? 0);

  const todayCount = stats?.total ?? 0;
  const queueCount = stats?.by_status?.["pending"] ?? 0;
  const failedCount = stats?.by_status?.["failed"] ?? 0;
  const todayCost = (weekly?.total_cost_usd ?? 0) / 7;

  const statCards = [
    { title: "اخبار امروز", value: todayCount, icon: <FileTextOutlined />, color: "#388BFD" },
    { title: "در صف پردازش", value: queueCount, pulse: true, icon: <ClockCircleOutlined />, color: "#D29922" },
    { title: "هزینه امروز ($)", value: +todayCost.toFixed(2), precision: 2, icon: <DollarOutlined />, color: "#177DDC" },
    { title: "خطاها", value: failedCount, icon: <WarningOutlined />, color: "#F85149" },
  ];

  // Build 7-day cost chart data from weekly breakdown (approximate with today / 7 per day)
  const chartData = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return {
      date: `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")}`,
      daily: +todayCost.toFixed(2),
      budget: 5,
    };
  });

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
      <Row gutter={[16, 16]}>
        {statCards.map((s, i) => (
          <Col xs={24} sm={12} lg={6} key={s.title}>
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.05 }}>
              <Card>
                <Statistic
                  title={
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ color: s.color }}>{s.icon}</span>
                      {s.title}
                      {s.pulse && <span className="pulse-dot" />}
                    </span>
                  }
                  value={s.value}
                  precision={s.precision}
                  valueStyle={{ color: s.color }}
                />
              </Card>
            </motion.div>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card title="آخرین اخبار پردازش‌شده" size="small">
            {newsLoading ? (
              <Skeleton active paragraph={{ rows: 6 }} />
            ) : (
              <Table
                size="small"
                dataSource={newsList?.items ?? []}
                rowKey="id"
                pagination={false}
                onRow={(r) => ({ onClick: () => setSelected(r), style: { cursor: "pointer" } })}
                columns={[
                  {
                    title: "عنوان",
                    dataIndex: "title_fa",
                    ellipsis: true,
                    render: (fa, r) => fa || r.title,
                  },
                  {
                    title: "کوین‌ها",
                    dataIndex: "coins_json",
                    width: 140,
                    render: (v: string | null) => {
                      const coins: string[] = v ? JSON.parse(v) : [];
                      return coins.slice(0, 3).map((c) => <Tag color="gold" key={c}>{c}</Tag>);
                    },
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
                    width: 120,
                    render: (s) => <StatusBadge status={s} />,
                  },
                ]}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="وضعیت Pipeline" size="small">
            <PipelineFlow />
            <div style={{ color: "#8B949E", fontSize: 12, textAlign: "center", marginTop: 8 }}>
              جریان real-time پردازش اخبار
            </div>
          </Card>
        </Col>
      </Row>

      <Card title="هزینه ۷ روز اخیر" size="small" style={{ marginTop: 16 }}>
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#177DDC" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#177DDC" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#21262D" />
              <XAxis dataKey="date" stroke="#8B949E" />
              <YAxis stroke="#8B949E" />
              <Tooltip contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} />
              <Legend />
              <Area type="monotone" dataKey="daily" name="هزینه روزانه" stroke="#177DDC" fill="url(#g1)" />
              <Area type="monotone" dataKey="budget" name="بودجه" stroke="#F85149" fill="none" strokeDasharray="5 5" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        width={600}
        title={selected?.title_fa ?? selected?.title}
        placement="left"
      >
        {selected && (
          <>
            <p style={{ color: "#8B949E" }}>{selected.summary_fa}</p>
            {costLogs && costLogs.length > 0 && (
              <>
                <h4 style={{ marginTop: 24 }}>Pipeline Trace</h4>
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
    </motion.div>
  );
}
