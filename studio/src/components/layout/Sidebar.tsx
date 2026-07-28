"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Clapperboard,
  FolderKanban,
  Images,
  LayoutDashboard,
  ListVideo,
  Menu,
  Mic2,
  Settings,
  Upload,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export function Sidebar() {
  const pathname = usePathname();
  const { sidebarOpen, toggleSidebar, setSidebarOpen, activeProjectId } =
    useUiStore();
  const mocks = api.usingMocks();

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });

  const fallbackId =
    activeProjectId ??
    projectsQuery.data?.find((project) => project.has_storyboard)?.id ??
    projectsQuery.data?.[0]?.id ??
    "napoleon_alps_a1b2c3d4e5";

  const nav = [
    {
      href: "/",
      label: "Dashboard",
      icon: LayoutDashboard,
      match: (path: string) => path === "/",
    },
    {
      href: `/projects/${fallbackId}`,
      label: "Project",
      icon: FolderKanban,
      match: (path: string) =>
        path.startsWith("/projects/") &&
        !path.includes("/storyboard") &&
        !path.includes("/timeline") &&
        !path.includes("/audio") &&
        !path.includes("/export"),
    },
    {
      href: `/projects/${fallbackId}/storyboard`,
      label: "Storyboard",
      icon: Clapperboard,
      match: (path: string) => path.includes("/storyboard"),
    },
    {
      href: `/projects/${fallbackId}/timeline`,
      label: "Timeline",
      icon: ListVideo,
      match: (path: string) => path.includes("/timeline"),
    },
    {
      href: `/projects/${fallbackId}/audio`,
      label: "Audio",
      icon: Mic2,
      match: (path: string) => path.includes("/audio"),
    },
    {
      href: `/projects/${fallbackId}/export`,
      label: "Export",
      icon: Upload,
      match: (path: string) => path.includes("/export"),
    },
    {
      href: "/assets",
      label: "Assets",
      icon: Images,
      match: (path: string) => path.startsWith("/assets"),
    },
    {
      href: "/settings",
      label: "Settings",
      icon: Settings,
      match: (path: string) => path.startsWith("/settings"),
    },
  ];

  return (
    <>
      <Button
        variant="secondary"
        size="icon"
        className="fixed left-3 top-3 z-40 lg:hidden"
        onClick={toggleSidebar}
        aria-label="Toggle navigation"
      >
        {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
      </Button>

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-border bg-sidebar text-sidebar-foreground transition-transform lg:static lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="border-b border-border px-5 py-6">
          <Link href="/" className="block" onClick={() => setSidebarOpen(false)}>
            <p className="font-display text-3xl tracking-tight text-foreground">
              Arahus
            </p>
            <p className="mt-1 text-sm text-muted-foreground">Studio</p>
          </Link>
          {mocks ? (
            <p className="mt-3 rounded-md bg-accent-soft px-2 py-1 text-xs text-accent">
              Mock data mode
            </p>
          ) : null}
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-3">
          {nav.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <Link
                key={item.label}
                href={item.href}
                onClick={() => setSidebarOpen(false)}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-sidebar-foreground hover:bg-muted/70",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-4 text-xs text-muted-foreground">
          Sprint 6.6 · Export & Publish
        </div>
      </aside>
    </>
  );
}
