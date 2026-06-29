import { useState, type ReactNode } from "react";
import { Layout, Menu, Breadcrumb, Badge, Button, Tooltip } from "antd";
import {
  DashboardOutlined,
  FileTextOutlined,
  ApiOutlined,
  SettingOutlined,
  DollarOutlined,
  WarningOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import { Link, useRouter, useRouterState } from "@tanstack/react-router";
import { clearToken } from "../lib/auth";

const { Sider, Header, Content } = Layout;

const items = [
  { key: "/", icon: <DashboardOutlined />, label: <Link to="/">داشبورد</Link>, title: "داشبورد" },
  { key: "/news", icon: <FileTextOutlined />, label: <Link to="/news">اخبار</Link>, title: "اخبار" },
  { key: "/sources", icon: <ApiOutlined />, label: <Link to="/sources">منابع</Link>, title: "منابع" },
  { key: "/costs", icon: <DollarOutlined />, label: <Link to="/costs">هزینه‌ها</Link>, title: "هزینه‌ها" },
  { key: "/dlq", icon: <WarningOutlined />, label: <Link to="/dlq">صف خطا</Link>, title: "صف خطا" },
  { key: "/data", icon: <DatabaseOutlined />, label: <Link to="/data">مدیریت داده‌ها</Link>, title: "مدیریت داده‌ها" },
  { key: "/settings", icon: <SettingOutlined />, label: <Link to="/settings">تنظیمات</Link>, title: "تنظیمات" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const router = useRouter();

  const handleLogout = () => {
    clearToken();
    router.navigate({ to: "/login" });
  };
  const current = items.find((i) => i.key === pathname) ?? items[0];

  return (
    <Layout style={{ minHeight: "100vh" }} hasSider>
      <Sider
        width={220}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        style={{
          borderInlineStart: "1px solid #21262D",
          position: "sticky",
          insetInlineEnd: 0,
          top: 0,
          height: "100vh",
        }}
        reverseArrow
      >
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#E6EDF3",
            fontWeight: 700,
            fontSize: collapsed ? 14 : 18,
            gap: 8,
            borderBlockEnd: "1px solid #21262D",
          }}
        >
          <ThunderboltOutlined style={{ color: "#177DDC" }} />
          {!collapsed && <span>Bitpin Radar</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[current.key]}
          items={items.map(({ key, icon, label }) => ({ key, icon, label }))}
          style={{ borderInlineEnd: 0, marginTop: 8 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            height: 56,
            lineHeight: "56px",
            borderBlockEnd: "1px solid #21262D",
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <Breadcrumb
            items={[{ title: "Bitpin Radar" }, { title: current.title }]}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{ color: "#8B949E", fontSize: 12 }}>وضعیت صف:</span>
            <Badge status="success" text={<span style={{ color: "#E6EDF3" }}>سالم</span>} />
            <Tooltip title="خروج از پنل">
              <Button
                type="text"
                icon={<LogoutOutlined />}
                onClick={handleLogout}
                style={{ color: "#8B949E" }}
              />
            </Tooltip>
          </div>
        </Header>
        <Content style={{ padding: 24 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}