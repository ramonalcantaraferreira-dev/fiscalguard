import type { Metadata } from "next";
import { AppProvider } from "@/components/AppContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "FiscalGuard",
  description: "Compliance de fornecedores e inteligência fiscal para escritórios contábeis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
