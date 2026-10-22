import { useEffect, useState } from "react";
import { api, type CostEstimate } from "../lib/api";

type EstimateRow = CostEstimate["models"][number];

/** Estimate row of one provider model; undefined while loading, null if the price is unknown. */
function useModelEstimate(bookId: number, providerId: number | null, model: string) {
  const [result, setResult] = useState<{ key: string; row: EstimateRow | null } | null>(null);
  const key = `${providerId}/${model}`;

  useEffect(() => {
    if (!model || providerId === null) return;
    let current = true;
    const timer = setTimeout(() => {
      api
        .getEstimate(bookId, { providerId, model })
        .then((estimate) => current && setResult({ key, row: estimate.models[0] ?? null }))
        .catch(() => current && setResult({ key, row: null }));
    }, 300); // typed model ids: wait for a pause
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [bookId, providerId, model, key]);

  return result?.key === key ? result.row : undefined;
}

/**
 * Estimated cost of translating the whole book with these settings; undefined while
 * loading, null if a price is unknown. The review share is priced with the reviewer model.
 */
export function useRunCost(
  bookId: number,
  providerId: number | null,
  model: string,
  withReview: boolean,
  reviewModel: string,
): number | null | undefined {
  const reviewer = withReview && reviewModel && reviewModel !== model ? reviewModel : "";
  const row = useModelEstimate(bookId, providerId, model);
  const reviewRow = useModelEstimate(bookId, providerId, reviewer);

  if (!model || row === undefined || (reviewer && reviewRow === undefined)) return undefined;
  if (!row || (reviewer && !reviewRow)) return null;
  if (!withReview) return row.without_review.cost;
  // shortcut: retranslations of rejected chunks are priced at the reviewer's rate; the
  // backend would need a split translator/reviewer usage to be exact.
  return reviewRow
    ? row.without_review.cost + reviewRow.with_review.cost - reviewRow.without_review.cost
    : row.with_review.cost;
}
