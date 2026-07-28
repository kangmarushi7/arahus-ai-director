"use client";

import { AssetBrowser } from "@/components/assets/AssetBrowser";
import { useUiStore } from "@/stores/ui-store";

export default function AssetsPage() {
  const activeProjectId = useUiStore((state) => state.activeProjectId);
  return <AssetBrowser projectId={activeProjectId ?? undefined} />;
}
