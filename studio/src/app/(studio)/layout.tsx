import { Sidebar } from "@/components/layout/Sidebar";

export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 px-4 pb-10 pt-16 lg:px-8 lg:pt-8">{children}</main>
    </div>
  );
}
