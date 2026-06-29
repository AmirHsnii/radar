import { createFileRoute } from "@tanstack/react-router";
import { Card, Row, Col, Statistic, Table, Slider, Select, Progress, Space, Skeleton } from "antd";
import { useState } from "react";
import { motion } from "motion/react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
  PieChart, Pie, Cell,
} from "recharts";
import { useCostsDaily, useCostsWeekly, useCostsByModel, useCostsSummary } from "../lib/api/hooks";
import { CostBadge } from "../components/StatusBadge";

export const Route = createFileRoute("/costs")({
  head: () => ({ meta: [{ title: "هزینه‌ها · Bitpin Radar" }] }),
  component: CostsPage,
});

const COLORS = ["#177DDC", "#3FB950", "#D29922", "#F85149", "#a371f7"];

function CostsPage() {
  const [daily, setDaily] = useState(300);
  const [enPct, setEnPct] = useState(60);
  const [model, setModel] = useState<"fast" | "quality">("fast");

  const { data: weekly, isLoading: weeklyLoading } = useCostsWeekly();
  const { data: summary, isLoading: summaryLoading } = useCostsSummary();
  const { data: byModel } = useCostsByModel();
  const { data: dailyData } = useCostsDaily();

  const todayCost = summary?.today?.total_cost_usd ?? 0;
  const weeklyCost = weekly?.total_cost_usd ?? 0;
  const monthlyCost = summary?.this_month?.total_cost_usd ?? 0;
  const avgPerNews = summary?.today
    ? summary.today.calls > 0 ? summary.today.total_cost_usd / summary.today.calls : 0
    : 0;

  const monthlyBudget = summary?.budget_alert?.budget_usd ?? 150;
  const budgetPct = summary?.budget_alert?.spent_pct ?? Math.round((monthlyCost / monthlyBudget) * 100);

  const pieData = (byModel ?? []).map((m) => ({
    name: m.model,
    value: Number(m.cost_usd) || 0,
  }));

  const perNewsEn = model === "fast" ? 0.002 : 0.008;
  const perNewsFa = model === "fast" ? 0.001 : 0.004;
  const estDaily = daily * ((enPct / 100) * perNewsEn + ((100 - enPct) / 100) * perNewsFa);
  const estMonthly = estDaily * 30;

  const chartData = dailyData
    ? [{ date: dailyData.period, daily: Number(dailyData.total_cost_usd) || 0, budget: monthlyBudget / 30 }]
    : Array.from({ length: 7 }, (_, i) => {
        const d = new Date();
        d.setDate(d.getDate() - (6 - i));
        return {
          date: `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")}`,
          daily: +(todayCost + (Math.random() - 0.5) * 0.5).toFixed(4),
          budget: monthlyBudget / 30,
        };
      });

  const modelRows = (byModel ?? []).map((m, id) => ({
    id,
    model: m.model,
    cost: Number(m.cost_usd) || 0,
  }));

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      {summaryLoading ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={12} lg={6}>
            <Card><Statistic title="هزینه امروز" value={todayCost} precision={4} prefix="$" valueStyle={{ color: "#177DDC" }} /></Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card><Statistic title="هزینه این هفته" value={weeklyCost} precision={4} prefix="$" valueStyle={{ color: "#177DDC" }} /></Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card><Statistic title="هزینه این ماه" value={monthlyCost} precision={4} prefix="$" valueStyle={{ color: "#3FB950" }} /></Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card><Statistic title="میانگین هر خبر" value={avgPerNews} precision={6} prefix="$" valueStyle={{ color: "#D29922" }} /></Card>
          </Col>
        </Row>
      )}

      <Card title="روند هزینه" size="small" style={{ marginTop: 16 }}>
        <div style={{ width: "100%", height: 280 }}>
          <ResponsiveContainer>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#177DDC" stopOpacity={0.6} />
                  <stop offset="100%" stopColor="#177DDC" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#21262D" />
              <XAxis dataKey="date" stroke="#8B949E" />
              <YAxis stroke="#8B949E" />
              <Tooltip contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} formatter={(v: number) => [`$${v}`, ""]} />
              <Legend />
              <Area type="monotone" dataKey="daily" name="هزینه روزانه" stroke="#177DDC" fill="url(#cg)" />
              <Area type="monotone" dataKey="budget" name="بودجه روزانه" stroke="#F85149" fill="none" strokeDasharray="5 5" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="هزینه بر اساس مدل" size="small">
            {pieData.length === 0 ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : (
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={100} paddingAngle={2}>
                      {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} formatter={(v: number) => [`$${v}`, ""]} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="هزینه به تفکیک مدل" size="small">
            <Table
              size="small"
              dataSource={modelRows}
              rowKey="id"
              pagination={false}
              columns={[
                { title: "مدل", dataIndex: "model", ellipsis: true },
                { title: "هزینه ($)", dataIndex: "cost", width: 110, render: (v) => <CostBadge value={v} /> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card title="تخمین هزینه ماهانه" size="small" style={{ marginTop: 16 }}>
        <Row gutter={24}>
          <Col xs={24} lg={12}>
            <Space direction="vertical" style={{ width: "100%" }} size="large">
              <div>
                <div style={{ marginBottom: 8 }}>اخبار روزانه: <strong>{daily}</strong></div>
                <Slider min={100} max={1000} step={10} value={daily} onChange={setDaily} />
              </div>
              <div>
                <div style={{ marginBottom: 8 }}>درصد اخبار انگلیسی: <strong>{enPct}%</strong></div>
                <Slider min={0} max={100} value={enPct} onChange={setEnPct} />
              </div>
              <div>
                <div style={{ marginBottom: 8 }}>مدل اصلی</div>
                <Select value={model} onChange={setModel} style={{ width: 200 }} options={[{ value: "fast", label: "Fast ($0.002)" }, { value: "quality", label: "Quality ($0.008)" }]} />
              </div>
            </Space>
          </Col>
          <Col xs={24} lg={12}>
            <Row gutter={16}>
              <Col span={12}><Statistic title="تخمین روزانه" value={estDaily} precision={3} prefix="$" valueStyle={{ color: "#177DDC" }} /></Col>
              <Col span={12}><Statistic title="تخمین ماهانه" value={estMonthly} precision={2} prefix="$" valueStyle={{ color: "#D29922" }} /></Col>
            </Row>
            <div style={{ marginTop: 24 }}>
              <div style={{ marginBottom: 8, color: "#8B949E" }}>
                پیشرفت بودجه ماهانه ({monthlyCost.toFixed(2)} / {monthlyBudget})
              </div>
              <Progress
                percent={Math.min(budgetPct, 100)}
                strokeColor={budgetPct > 80 ? "#F85149" : "#177DDC"}
                status={budgetPct >= 100 ? "exception" : "active"}
              />
            </div>
          </Col>
        </Row>
      </Card>
    </motion.div>
  );
}
