import { createFileRoute, useRouter } from "@tanstack/react-router";
import { Card, Form, Input, Button, Alert, Typography } from "antd";
import { LockOutlined, UserOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useState } from "react";
import { publicApi } from "../lib/api/client";
import { setToken, isAuthenticated } from "../lib/auth";
import { motion } from "motion/react";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "ورود · Bitpin Radar" }] }),
  beforeLoad: () => {
    if (isAuthenticated()) {
      throw new Error("already-authenticated");
    }
  },
  component: LoginPage,
});

function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFinish = async (vals: { username: string; password: string }) => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await publicApi.post<{ access_token: string }>("/auth/login", vals);
      setToken(data.access_token);
      router.navigate({ to: "/" });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "خطا در ورود");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#161616",
        padding: 24,
      }}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
        style={{ width: "100%", maxWidth: 380 }}
      >
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <ThunderboltOutlined style={{ fontSize: 40, color: "#00cc85" }} />
          <Typography.Title level={3} style={{ color: "#ffffff", marginTop: 12 }}>
            Bitpin Radar
          </Typography.Title>
          <Typography.Text style={{ color: "#a0a0a0" }}>پنل مدیریت اخبار کریپتو</Typography.Text>
        </div>

        <Card style={{ background: "#1e1e1e", border: "1px solid #2e2e2e" }}>
          {error && (
            <Alert
              type="error"
              message={error}
              style={{ marginBottom: 20 }}
              closable
              onClose={() => setError(null)}
            />
          )}
          <Form layout="vertical" onFinish={onFinish} autoComplete="off">
            <Form.Item
              name="username"
              rules={[{ required: true, message: "نام کاربری الزامی است" }]}
            >
              <Input
                prefix={<UserOutlined style={{ color: "#a0a0a0" }} />}
                placeholder="نام کاربری"
                size="large"
                autoFocus
              />
            </Form.Item>
            <Form.Item
              name="password"
              rules={[{ required: true, message: "رمز عبور الزامی است" }]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: "#a0a0a0" }} />}
                placeholder="رمز عبور"
                size="large"
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={loading}
              >
                ورود به پنل
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </motion.div>
    </div>
  );
}
