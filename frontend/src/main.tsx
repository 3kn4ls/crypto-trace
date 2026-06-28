import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { TaxpayerProvider } from "./TaxpayerContext";
import "./styles.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <TaxpayerProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </TaxpayerProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
