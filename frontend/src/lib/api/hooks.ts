/**
 * React Query hooks for all backend resources.
 *
 * Naming convention:
 *   useXxx   → useQuery (read)
 *   useXxxMutation → useMutation (write)
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { message } from "antd";
import { api } from "./client";
import type {
  AppSetting,
  Category,
  Coin,
  CostLog,
  CostPeriod,
  CostsByModelOut,
  CostSummary,
  GroupedSettingsOut,
  DlqItem,
  DlqListOut,
  DlqStats,
  NewsFilters,
  NewsItem,
  NewsListOut,
  NewsStats,
  Source,
  SourceCreate,
  SourceUpdate,
  SourceTestOut,
  SourceTestPipelineOut,
  WpPreview,
  DualWhitelistOut,
} from "./types";

// ── News ─────────────────────────────────────────────────────────────────────

export const newsKeys = {
  all: ["news"] as const,
  list: (f: NewsFilters) => ["news", "list", f] as const,
  one: (id: number) => ["news", id] as const,
  stats: (date?: string) => ["news", "stats", date] as const,
};

export function useNewsList(filters: NewsFilters = {}) {
  return useQuery({
    queryKey: newsKeys.list(filters),
    queryFn: () =>
      api
        .get<NewsListOut>("/news/", { params: filters })
        .then((r) => r.data),
    placeholderData: (prev) => prev,
  });
}

export function useNewsItem(id: number) {
  return useQuery({
    queryKey: newsKeys.one(id),
    queryFn: () => api.get<NewsItem>(`/news/${id}`).then((r) => r.data),
    enabled: id > 0,
  });
}

export function useNewsStats(dateStr?: string) {
  return useQuery({
    queryKey: newsKeys.stats(dateStr),
    queryFn: () =>
      api
        .get<NewsStats>("/news/stats", { params: dateStr ? { date_str: dateStr } : undefined })
        .then((r) => r.data),
    staleTime: 30_000,
  });
}

export function useCostLogsForNews(newsId: number) {
  return useQuery({
    queryKey: ["costs", "per-news", newsId],
    queryFn: () => api.get<CostLog[]>(`/costs/per-news/${newsId}`).then((r) => r.data),
    enabled: newsId > 0,
  });
}

export function useNewsWpPreview(newsId: number) {
  return useQuery({
    queryKey: ["news", "wp-preview", newsId],
    queryFn: () => api.get<WpPreview>(`/news/${newsId}/wp-preview`).then((r) => r.data),
    enabled: newsId > 0,
  });
}

export function useApproveNews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (newsId: number) =>
      api.post<{ queued: boolean }>(`/news/${newsId}/approve`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: newsKeys.all });
      message.success("تایید شد — در صف انتشار قرار گرفت");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useRejectNews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (newsId: number) =>
      api.post<{ rejected: boolean }>(`/news/${newsId}/reject`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: newsKeys.all });
      message.warning("خبر رد شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

// ── Sources ──────────────────────────────────────────────────────────────────

export const sourcesKeys = {
  all: ["sources"] as const,
};

export function useSources(options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: sourcesKeys.all,
    queryFn: () => api.get<Source[]>("/sources/").then((r) => r.data),
    refetchInterval: options?.refetchInterval,
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SourceCreate) =>
      api.post<Source>("/sources/", data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourcesKeys.all });
      message.success("منبع اضافه شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useUpdateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: SourceUpdate }) =>
      api.put<Source>(`/sources/${id}`, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourcesKeys.all });
      message.success("منبع بروز شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/sources/${id}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourcesKeys.all });
      message.success("منبع حذف شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useToggleSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api.post<Source>(`/sources/${id}/toggle`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: sourcesKeys.all }),
    onError: (e: Error) => message.error(e.message),
  });
}

export function useTestSource() {
  return useMutation({
    mutationFn: (id: number) =>
      api.post<SourceTestOut>(`/sources/${id}/test`).then((r) => r.data),
    onError: (e: Error) => message.error(e.message),
  });
}

export function useTestSourcePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api
        .post<SourceTestPipelineOut>(`/sources/${id}/test-pipeline`, null, {
          timeout: 300_000,
        })
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: newsKeys.all });
    },
    onError: (e: Error) => message.error(e.message),
  });
}

// ── Costs ─────────────────────────────────────────────────────────────────────

export function useCostsDaily(dateStr?: string) {
  return useQuery({
    queryKey: ["costs", "daily", dateStr],
    queryFn: () =>
      api.get<CostPeriod>("/costs/daily", { params: dateStr ? { date: dateStr } : undefined }).then((r) => r.data),
    staleTime: 60_000,
  });
}

export function useCostsMonthly(year?: number, month?: number) {
  return useQuery({
    queryKey: ["costs", "monthly", year, month],
    queryFn: () =>
      api.get<CostPeriod>("/costs/monthly", { params: year ? { year, month } : undefined }).then((r) => r.data),
    staleTime: 60_000,
  });
}

export function useCostsWeekly() {
  return useQuery({
    queryKey: ["costs", "weekly"],
    queryFn: () => api.get<CostPeriod>("/costs/weekly").then((r) => r.data),
    staleTime: 60_000,
  });
}

export function useCostsByModel() {
  return useQuery({
    queryKey: ["costs", "by-model"],
    queryFn: () =>
      api.get<CostsByModelOut>("/costs/by-model").then((r) => r.data.by_model),
    staleTime: 60_000,
  });
}

export function useCostsSummary() {
  return useQuery({
    queryKey: ["costs", "summary"],
    queryFn: () => api.get<CostSummary>("/costs/summary").then((r) => r.data),
    staleTime: 30_000,
  });
}

// ── DLQ ──────────────────────────────────────────────────────────────────────

export const dlqKeys = {
  list: (page: number, status?: string) => ["dlq", "list", page, status] as const,
  stats: ["dlq", "stats"] as const,
};

export function useDlqList(page = 1, status?: string) {
  return useQuery({
    queryKey: dlqKeys.list(page, status),
    queryFn: () =>
      api
        .get<DlqListOut>("/dlq/", { params: { page, size: 20, ...(status ? { status } : {}) } })
        .then((r) => r.data),
    placeholderData: (prev) => prev,
  });
}

export function useDlqStats() {
  return useQuery({
    queryKey: dlqKeys.stats,
    queryFn: () => api.get<DlqStats>("/dlq/stats").then((r) => r.data),
    staleTime: 10_000,
  });
}

export function useRetryDlq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ success: boolean }>(`/dlq/${id}/retry`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dlq"] });
      message.success("retry انجام شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useDiscardDlq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      api.post<{ success: boolean }>(`/dlq/${id}/discard`, { reason }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dlq"] });
      message.success("حذف شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useRetryAllDlq() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ queued_count: number; dlq_ids: number[] }>("/dlq/retry-all").then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["dlq"] });
      message.success(`${data.queued_count} مورد retry شد`);
    },
    onError: (e: Error) => message.error(e.message),
  });
}

// ── Settings ─────────────────────────────────────────────────────────────────

export const settingsKeys = {
  all: ["settings"] as const,
  promptDefaults: ["settings", "prompt-defaults"] as const,
};

export function usePromptDefaults() {
  return useQuery({
    queryKey: settingsKeys.promptDefaults,
    queryFn: () =>
      api.get<{ agents: Record<string, string> }>("/settings/prompt-defaults").then((r) => r.data.agents),
    staleTime: 300_000,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: settingsKeys.all,
    queryFn: () =>
      api
        .get<GroupedSettingsOut[]>("/settings/")
        .then((r) => r.data.flatMap((group) => group.settings)),
    staleTime: 30_000,
  });
}

export function useUpdateSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      api.put<AppSetting>(`/settings/${encodeURIComponent(key)}`, { value }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.all });
      message.success("ذخیره شد ✓");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useResetSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      api.post(`/settings/reset/${encodeURIComponent(key)}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.all });
      message.success("بازنشانی شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

// ── Admin / Data ──────────────────────────────────────────────────────────────

export const adminKeys = {
  coins: ["admin", "coins"] as const,
  categories: ["admin", "categories"] as const,
  whitelist: ["admin", "whitelist"] as const,
};

export function useCoins() {
  return useQuery({
    queryKey: adminKeys.coins,
    queryFn: () => api.get<Coin[]>("/admin/coins").then((r) => r.data),
  });
}

export function useCategories() {
  return useQuery({
    queryKey: adminKeys.categories,
    queryFn: () => api.get<Category[]>("/admin/categories").then((r) => r.data),
  });
}

export function useWhitelist() {
  return useQuery({
    queryKey: adminKeys.whitelist,
    queryFn: () =>
      api.get<DualWhitelistOut>("/admin/whitelist").then((r) => r.data),
  });
}

export function useUpdateWhitelist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { fa_keywords: string[]; en_keywords: string[] }) =>
      api.put("/admin/whitelist", data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.whitelist });
      message.success("وایت‌لیست ذخیره شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useReEmbedCoins() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/admin/coins/re-embed").then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.coins });
      message.success("re-embed در پس‌زمینه شروع شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useImportCoins() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api
        .post<{ imported: number; created: number; updated: number }>(
          "/admin/coins/import",
          fd,
        )
        .then((r) => r.data);
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: adminKeys.coins });
      message.success(`${data.imported} کوین import شد (${data.created} جدید، ${data.updated} بروز)`);
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useReEmbedCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/admin/categories/re-embed").then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: adminKeys.categories });
      message.success("re-embed در پس‌زمینه شروع شد");
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useImportCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api
        .post<{ imported: number; created: number; updated: number }>(
          "/admin/categories/import",
          fd,
        )
        .then((r) => r.data);
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: adminKeys.categories });
      message.success(`${data.imported} دسته import شد (${data.created} جدید، ${data.updated} بروز)`);
    },
    onError: (e: Error) => message.error(e.message),
  });
}

export function useImportWhitelist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      mode,
      language = "fa",
    }: {
      file: File;
      mode: "merge" | "replace";
      language?: "fa" | "en";
    }) => {
      const fd = new FormData();
      fd.append("file", file);
      return api
        .post<{ imported: number; total: number }>(
          `/admin/whitelist/import?mode=${mode}&language=${language}`,
          fd,
        )
        .then((r) => r.data);
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: adminKeys.whitelist });
      message.success(`${data.imported} کلمه import شد — مجموع: ${data.total}`);
    },
    onError: (e: Error) => message.error(e.message),
  });
}
