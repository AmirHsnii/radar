import { motion } from "motion/react";
import {
  CloudDownloadOutlined,
  FilterOutlined,
  RobotOutlined,
  TagsOutlined,
  SendOutlined,
} from "@ant-design/icons";

const steps = [
  { key: "crawl", label: "Crawl", icon: <CloudDownloadOutlined />, count: 142, avg: "320ms" },
  { key: "dedup", label: "Dedup", icon: <FilterOutlined />, count: 128, avg: "45ms" },
  { key: "ai", label: "AI Process", icon: <RobotOutlined />, count: 124, avg: "1.2s" },
  { key: "classify", label: "Classify", icon: <TagsOutlined />, count: 124, avg: "540ms" },
  { key: "publish", label: "Publish", icon: <SendOutlined />, count: 121, avg: "210ms" },
];

export function PipelineFlow() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 0" }}>
      {steps.map((s, i) => (
        <div key={s.key} style={{ display: "contents" }}>
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.08 }}
            style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 80 }}
          >
            <div style={{ fontSize: 11, color: "#8B949E" }}>{s.count}</div>
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: "50%",
                background: "#1C2128",
                border: `2px solid ${s.count > 200 ? "#D29922" : "#177DDC"}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#177DDC",
                fontSize: 20,
              }}
            >
              {s.icon}
            </div>
            <div style={{ fontSize: 12, color: "#E6EDF3", fontWeight: 500 }}>{s.label}</div>
            <div style={{ fontSize: 10, color: "#8B949E" }}>{s.avg}</div>
          </motion.div>
          {i < steps.length - 1 && <div className="pipeline-line" />}
        </div>
      ))}
    </div>
  );
}