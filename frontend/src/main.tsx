import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// Self-hosted fonts — Inter (body), Fraunces (display serif),
// JetBrains Mono (citations / agent labels). Replaces the Google
// Fonts CDN link in index.html so third-party requests don't carry
// PII to Google (German court ruling 2022 treats Google Fonts as
// GDPR-relevant; we ship our own bytes).
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/fraunces/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Server state changes when the user runs forward_job or
      // generates a pack — short stale time keeps the dashboard
      // fresh without hammering the backend.
      staleTime: 5_000,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
