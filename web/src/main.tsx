import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntdApp, ConfigProvider } from "antd";
import { BrowserRouter } from "react-router-dom";
import "antd/dist/reset.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 16,
          colorLink: "#e34a32",
          colorPrimary: "#171719",
          colorInfo: "#e34a32",
          colorSuccess: "#16835f",
          colorWarning: "#c67a00",
          colorText: "#2e3034",
          colorTextSecondary: "#55575c",
          colorBgBase: "#f4f5f5",
          colorBorder: "rgba(35, 36, 39, 0.1)",
          fontFamily:
            'Inter, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif',
        },
        components: {
          Button: {
            controlHeight: 42,
            fontWeight: 600,
          },
          Input: {
            controlHeight: 40,
          },
          Select: {
            controlHeight: 40,
          },
        },
      }}
    >
      <AntdApp>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);
