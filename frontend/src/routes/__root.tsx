import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouterState,
  redirect,
  useRouter,
} from "@tanstack/react-router";
import { useEffect } from "react";
import { isAuthenticated } from "../lib/auth";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { ConfigProvider, theme as antdTheme } from "antd";
import { AppShell } from "../components/AppShell";

const RadarTheme = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: "#00cc85",
    colorBgBase: "#161616",
    colorBgContainer: "#1e1e1e",
    colorBgElevated: "#262626",
    colorBorder: "#2e2e2e",
    colorText: "#ffffff",
    colorTextSecondary: "#a0a0a0",
    colorSuccess: "#00cc85",
    colorWarning: "#ff9800",
    colorError: "#f44336",
    colorInfo: "#2196f3",
    borderRadius: 6,
    fontFamily: "'Vazirmatn', sans-serif",
    fontSize: 14,
  },
  components: {
    Layout: { siderBg: "#161616", headerBg: "#1e1e1e", bodyBg: "#161616" },
    Menu: { darkItemBg: "#161616", darkSubMenuItemBg: "#161616" },
    Table: { headerBg: "#262626", rowHoverBg: "#262626" },
  },
};

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  beforeLoad: ({ location }) => {
    const onLoginPage = location.pathname === "/login";
    if (!onLoginPage && !isAuthenticated()) {
      throw redirect({ to: "/login" });
    }
  },
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isLoginPage = pathname === "/login";

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={RadarTheme} direction="rtl">
        {isLoginPage ? (
          <Outlet />
        ) : (
          <AppShell>
            <Outlet />
          </AppShell>
        )}
      </ConfigProvider>
    </QueryClientProvider>
  );
}
