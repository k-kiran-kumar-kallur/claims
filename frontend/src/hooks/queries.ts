import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { Claim, DocumentItem, Fact, Flag, Report, Review, Summary } from "../api/types";

export const useClaim = (id?: string) =>
  useQuery({ queryKey: ["claim", id], queryFn: () => api.get<Claim>(`/claims/${id}`), enabled: !!id });

export const useDashboard = (id?: string) =>
  useQuery({ queryKey: ["dashboard", id], queryFn: () => api.get<any>(`/claims/${id}/dashboard`), enabled: !!id });

export const useRuns = (claimId?: string) =>
  useQuery({ queryKey: ["runs", claimId], queryFn: () => api.get<any[]>(`/claims/${claimId}/runs`), enabled: !!claimId });

export const useDocuments = (claimId?: string, filters: Record<string, string> = {}) =>
  useQuery({
    queryKey: ["documents", claimId, filters],
    queryFn: () => api.get<DocumentItem[]>(`/claims/${claimId}/documents${qs(filters)}`),
    enabled: !!claimId,
  });

export const useFacts = (claimId?: string, filters: Record<string, string> = {}) =>
  useQuery({ queryKey: ["facts", claimId, filters], queryFn: () => api.get<Fact[]>(`/claims/${claimId}/facts${qs(filters)}`), enabled: !!claimId });

export const useFlags = (claimId?: string) =>
  useQuery({ queryKey: ["flags", claimId], queryFn: () => api.get<Flag[]>(`/claims/${claimId}/flags`), enabled: !!claimId });

export const useSummaries = (claimId?: string) =>
  useQuery({ queryKey: ["summaries", claimId], queryFn: () => api.get<Summary[]>(`/claims/${claimId}/summaries`), enabled: !!claimId });

export const useReports = (claimId?: string) =>
  useQuery({ queryKey: ["reports", claimId], queryFn: () => api.get<Report[]>(`/claims/${claimId}/reports`), enabled: !!claimId, refetchInterval: 5000 });

export const useClaimReviews = (claimId?: string, status = "open") =>
  useQuery({
    queryKey: ["reviews", claimId, status],
    queryFn: () => api.get<Review[]>(`/reviews${qs({ claim_id: claimId, status })}`),
    enabled: !!claimId,
  });

export const useReview = (reviewId?: string | null) =>
  useQuery({ queryKey: ["review", reviewId], queryFn: () => api.get<Review>(`/reviews/${reviewId}`), enabled: !!reviewId });

export function usePendingReview(claimId: string | undefined, checkpoint: string) {
  const reviews = useClaimReviews(claimId);
  const item = reviews.data?.find((r) => r.checkpoint === checkpoint);
  const review = useReview(item?.id);
  return { review: review.data, isLoading: reviews.isLoading || review.isLoading, refetch: review.refetch };
}

export function useSubmitReview(claimId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) => api.post(`/reviews/${id}/submit`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reviews"] });
      qc.invalidateQueries({ queryKey: ["claim", claimId] });
      qc.invalidateQueries({ queryKey: ["runs", claimId] });
    },
  });
}

export const useUsers = (role?: string) =>
  useQuery({ queryKey: ["users", role], queryFn: () => api.get<{ id: string; full_name: string; roles: string[] }[]>(`/users${qs({ role })}`) });
