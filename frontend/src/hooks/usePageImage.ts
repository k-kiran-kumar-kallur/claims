import { useEffect, useState } from "react";
import { api } from "../api/client";

/** Page images require the bearer token, so they are fetched as blobs and shown via object URLs (never cached to disk). */
export function usePageImage(docId?: string | null, page?: number | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!docId || !page) return;
    let revoked = false;
    let objectUrl: string | null = null;
    setUrl(null);
    setError(null);
    api
      .blob(`/documents/${docId}/pages/${page}/image`)
      .then((b) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(b);
        setUrl(objectUrl);
      })
      .catch((e) => setError(e.message));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId, page]);
  return { url, error };
}
