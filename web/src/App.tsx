import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  App as AntdApp,
  Button,
  Col,
  Form,
  Image,
  Input,
  List,
  Modal,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import {
  AlertCircle,
  ArrowRight,
  Barcode,
  CreditCard,
  Download,
  Gauge,
  Home,
  Image as ImageIcon,
  LogOut,
  Play,
  Images,
  QrCode,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  UserRound,
  Wallet,
  Wand2,
  Workflow,
} from "lucide-react";
import { apiDownload, apiGet, apiPost, apiPutRaw } from "./api/client";
import { barcodeValidationMessage, suggestedBarcodeValue, type BarcodeValidationResponse } from "./barcodeValidation";
import { generationProgress, nextLiveGenerationProgress } from "./generationProgress";
import { buildProjectCreatePayload } from "./generationPayload";
import { accountDisplayName, transactionDetailText } from "./accountDisplay";
import { buildProductCreatePayload, type ProductPayloadValues } from "./productPayload";
import { generationErrorMessage } from "./generationErrors";
import { userFacingErrorMessage } from "./userFacingErrors";
import { pageForAuthState } from "./navigation";
import {
  createGalleryPreviews,
  createOutputPreviews,
  outputOriginalDownloadPath,
  outputPreviewDownloadPath,
  type OutputResponse,
  type PreviewImage,
} from "./outputPreviews";
import {
  authErrorMessage,
  restoreAuthFromRefresh,
  type AuthResponse,
  type RegistrationCodeResponse,
} from "./authFlow";
import { UpdateBadge } from "./update/UpdateBadge";
import { UpdateModal } from "./update/UpdateModal";
import { checkForAppUpdate, updateDownloadHref, type UpdateCheckResponse } from "./update/updateApi";
import { hasUpdateNotice, readDismissedUpdateVersion, rememberDismissedUpdateVersion, shouldOpenUpdateModal } from "./update/updateState";
import { APP_VERSION } from "./update/version";
import "./App.css";

const { Paragraph, Text, Title } = Typography;

type ProductResponse = {
  id: string;
  name: string;
  brand: string;
  model: string;
  category: string;
};

type ProjectResponse = {
  id: string;
  name: string;
  product_id: string;
  barcode_value: string;
  barcode_type: string;
  status: string;
};

type UploadPresignResponse = {
  upload_token: string;
  upload_url: string;
  method: "PUT";
  headers: Record<string, string>;
  object_key: string;
};

type AssetResponse = {
  id: string;
  asset_id: string;
  version_id: string;
  asset_type: string;
  filename: string;
  width: number;
  height: number;
  sha256: string;
};

type GenerationResponse = {
  id: string;
  status: string;
  provider_name: string;
  error_code?: string | null;
  error_message?: string | null;
  source_asset?: AssetResponse;
  outputs: OutputResponse[];
};

type ProjectOutputsResponse = {
  items: OutputResponse[];
  next_cursor?: string | null;
};

type AccountResponse = {
  user: {
    id: string;
    email: string;
    username: string;
  };
  username: string;
  balance_points: number;
  reserved_points: number;
  available_points: number;
  next_expiring_lot?: {
    id: string;
    remaining_points: number;
    expires_at: string;
  } | null;
};

type AccountTransaction = {
  id: string;
  type: string;
  points: number;
  balance_after: number;
  remark: string;
  created_at: string;
};

type AccountTransactionsResponse = {
  items: AccountTransaction[];
};

type LoginValues = {
  username: string;
  email: string;
  verificationCode: string;
  password: string;
  newPassword: string;
};

type ProductFormValues = ProductPayloadValues & {
  companyName: string;
  manufacturerName: string;
  manufacturerAddress: string;
  productionDate: string;
  inspector: string;
  barcodeType: "EAN_13" | "EAN_8" | "UPC_A" | "CODE_128";
  barcodeValue: string;
};

const loginInitialValues: LoginValues = {
  username: "",
  email: "",
  verificationCode: "",
  password: "",
  newPassword: "",
};

const productInitialValues: ProductFormValues = {
  name: "",
  brand: "",
  model: "",
  companyName: "",
  manufacturerName: "",
  manufacturerAddress: "",
  productionDate: new Date().toISOString().slice(0, 10),
  inspector: "QC-01",
  barcodeType: "EAN_13",
  barcodeValue: "",
};

const outputName: Record<string, string> = {
  main: "商品主图",
  certificate: "商品与合格证图",
  package: "商品与包装箱图",
  detail: "商品详情图",
  scene: "商品细节实拍图",
};
const galleryPageLimit = 30;

export function App() {
  usePointerGlow();
  const [token, setToken] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [username, setUsername] = useState("");
  const [authChecking, setAuthChecking] = useState(true);

  useEffect(() => {
    let active = true;
    restoreAuthFromRefresh(() => apiPost<AuthResponse>("/auth/refresh")).then((auth) => {
      if (!active) {
        return;
      }
      if (auth) {
        setToken(auth.access_token);
        setUserEmail(auth.user.email);
        setUsername(auth.user.username || "");
      }
      setAuthChecking(false);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!token) {
      return;
    }
    let active = true;
    async function refreshSession() {
      const auth = await restoreAuthFromRefresh(() => apiPost<AuthResponse>("/auth/refresh"));
      if (!active || !auth) {
        return;
      }
      setToken(auth.access_token);
      setUserEmail(auth.user.email);
      setUsername(auth.user.username || "");
    }
    const intervalId = window.setInterval(refreshSession, 6 * 60 * 60 * 1000);
    const refreshOnFocus = () => {
      void refreshSession();
    };
    const refreshOnVisible = () => {
      if (document.visibilityState === "visible") {
        void refreshSession();
      }
    };
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnVisible);
    return () => {
      active = false;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnVisible);
    };
  }, [token]);

  function handleAuthenticated(auth: AuthResponse) {
    setToken(auth.access_token);
    setUserEmail(auth.user.email);
    setUsername(auth.user.username || "");
  }

  function logout() {
    setToken("");
    setUserEmail("");
    setUsername("");
  }

  if (authChecking) {
    return null;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginRoute token={token} onAuthenticated={handleAuthenticated} />} />
      <Route
        path="/generate"
        element={
          <ProtectedRoute token={token}>
            <GeneratePage token={token} username={username} userEmail={userEmail} onLogout={logout} />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={token ? "/generate" : "/login"} replace />} />
    </Routes>
  );
}

function LoginRoute({ token, onAuthenticated }: { token: string; onAuthenticated: (auth: AuthResponse) => void }) {
  const location = useLocation();
  const navigate = useNavigate();

  if (pageForAuthState(token, location.pathname) === "/generate") {
    return <Navigate to="/generate" replace />;
  }

  function complete(auth: AuthResponse) {
    onAuthenticated(auth);
    navigate("/generate", { replace: true });
  }

  return <LoginPage onAuthenticated={complete} />;
}

function ProtectedRoute({ token, children }: { token: string; children: JSX.Element }) {
  const location = useLocation();
  if (pageForAuthState(token, location.pathname) === "/login") {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <img src="/brand/zf-logo.png" alt="" draggable={false} />
    </span>
  );
}

function AmbientLayer() {
  return (
    <div className="ambient-layer" aria-hidden="true">
      <span className="ambient-bloom ambient-bloom-red" />
      <span className="ambient-bloom ambient-bloom-dark" />
      <span className="ambient-bloom ambient-bloom-low" />
      <span className="mesh-plate mesh-plate-one" />
      <span className="mesh-plate mesh-plate-two" />
    </div>
  );
}

function usePointerGlow() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }

    function updatePointer(event: PointerEvent) {
      const x = (event.clientX / window.innerWidth - 0.5) * 28;
      const y = (event.clientY / window.innerHeight - 0.5) * 28;
      document.documentElement.style.setProperty("--pointer-x", `${x}px`);
      document.documentElement.style.setProperty("--pointer-y", `${y}px`);
    }

    window.addEventListener("pointermove", updatePointer, { passive: true });
    return () => window.removeEventListener("pointermove", updatePointer);
  }, []);
}

function LoginPage({ onAuthenticated }: { onAuthenticated: (auth: AuthResponse) => void }) {
  const { message } = AntdApp.useApp();
  const [form] = Form.useForm<LoginValues>();
  const [loading, setLoading] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register" | "reset">("login");
  const [hasSentRegistrationCode, setHasSentRegistrationCode] = useState(false);
  const [hasSentResetCode, setHasSentResetCode] = useState(false);
  const [resendCountdown, setResendCountdown] = useState(0);

  useEffect(() => {
    if (resendCountdown <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      setResendCountdown((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [resendCountdown]);

  async function submitLogin(values: LoginValues) {
    if (authMode === "reset") {
      await resetPasswordWithCode(values);
      return;
    }
    await authenticate(values, authMode);
  }

  async function authenticate(values: LoginValues, mode: "login" | "register") {
    setLoading(true);
    try {
      if (mode === "register") {
        const auth = await registerAccount(values.username, values.email, values.verificationCode, values.password);
        onAuthenticated(auth);
        message.success("注册成功，已进入生成台");
        return;
      }
      const auth = await apiPost<AuthResponse>("/auth/login", { email: values.email, password: values.password });
      onAuthenticated(auth);
      message.success("登录成功");
    } catch (error) {
      message.error(authErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  async function sendRegistrationCode() {
    if (resendCountdown > 0) {
      return;
    }
    const email = await form.validateFields(["email"]).then((values) => values.email);
    setSendingCode(true);
    try {
      await requestRegistrationCode(email);
      setHasSentRegistrationCode(true);
      setResendCountdown(60);
      message.success("验证码已发送，请注意查收");
    } catch (error) {
      message.error(authErrorMessage(error));
    } finally {
      setSendingCode(false);
    }
  }

  async function sendResetCode() {
    if (resendCountdown > 0) {
      return;
    }
    const email = await form.validateFields(["email"]).then((values) => values.email);
    setSendingCode(true);
    try {
      await requestPasswordResetCode(email);
      setHasSentResetCode(true);
      setResendCountdown(60);
      message.success("验证码已发送，请查看邮箱");
    } catch (error) {
      message.error(authErrorMessage(error));
    } finally {
      setSendingCode(false);
    }
  }

  async function resetPasswordWithCode(values: LoginValues) {
    setLoading(true);
    try {
      await resetPassword(values.email, values.verificationCode, values.newPassword);
      message.success("密码已重置，请使用新密码登录");
      setAuthMode("login");
      form.setFieldsValue({ password: "", newPassword: "", verificationCode: "" });
    } catch (error) {
      message.error(authErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="desktop-shell login-shell">
      <section className="source-stage login-stage" aria-label="智枫生图登录">
        <AmbientLayer />
        <div className="login-center-logo" aria-label="智枫生图">
          <BrandMark />
        </div>
        <div className="login-hero panel-dark">
          <div className="hero-brand-stack">
            <div className="hero-topline">
              <span className="hero-brand-logo">
                <BrandMark />
              </span>
              <span>Zhifeng Image</span>
            </div>
          </div>
          <div>
            <Tag className="soft-tag red-tag">V2.0 单账号基线</Tag>
            <Title className="hero-title">商品图生成工作台</Title>
            <Paragraph className="hero-copy">
              上传商品原图，输入商品资料与条码数字，系统生成符合下载门槛的五类电商图片。
            </Paragraph>
          </div>
          <div id="capabilities" className="hero-metrics" aria-label="核心能力">
            <div>
              <strong>5</strong>
              <span>输出图型</span>
            </div>
            <div>
              <strong>1</strong>
              <span>用户隔离</span>
            </div>
            <div>
              <strong>0</strong>
              <span>团队协作功能</span>
            </div>
          </div>
        </div>

        <div id="auth" className="login-card app-panel">
          <div className="section-heading">
            <span className="icon-chip">
              <UserRound size={18} />
            </span>
            <div>
              <Title level={2}>
                {authMode === "login" ? "登录账号" : authMode === "register" ? "注册账号" : "找回密码"}
              </Title>
            </div>
          </div>

          <Form form={form} layout="vertical" initialValues={loginInitialValues} onFinish={submitLogin} requiredMark={false}>
            <Segmented
              className="auth-mode-switch"
              block
              value={authMode}
              onChange={(value) => setAuthMode(value as "login" | "register" | "reset")}
              options={[
                { label: "登录", value: "login" },
                { label: "注册", value: "register" },
                { label: "找回密码", value: "reset" },
              ]}
            />
            {authMode === "register" ? (
              <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
                <Input size="large" autoComplete="username" />
              </Form.Item>
            ) : null}
            <Form.Item
              name="email"
              label="邮箱"
              rules={[
                { required: true, message: "请输入邮箱" },
                { type: "email", message: "请输入正确的邮箱地址" },
              ]}
            >
              <Input size="large" autoComplete="email" />
            </Form.Item>
            {authMode !== "login" ? (
              <Form.Item name="verificationCode" label="邮箱验证码" rules={[{ required: true, message: "请输入邮箱验证码" }]}>
                <Space.Compact className="full-width">
                  <Input size="large" maxLength={6} inputMode="numeric" autoComplete="one-time-code" />
                  <Button
                    htmlType="button"
                    size="large"
                    onClick={authMode === "reset" ? sendResetCode : sendRegistrationCode}
                    loading={sendingCode}
                    disabled={resendCountdown > 0}
                  >
                    {resendCountdown > 0
                      ? `${resendCountdown}秒`
                      : authMode === "reset"
                        ? hasSentResetCode
                          ? "重新发送验证码"
                          : "发送验证码"
                        : hasSentRegistrationCode
                          ? "重新发送验证码"
                          : "发送验证码"}
                  </Button>
                </Space.Compact>
              </Form.Item>
            ) : null}
            {authMode === "reset" ? (
              <Form.Item name="newPassword" label="新密码" rules={[{ required: true, min: 8, message: "新密码至少 8 位" }]}>
                <Input.Password size="large" autoComplete="new-password" />
              </Form.Item>
            ) : (
              <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
                <Input.Password size="large" autoComplete={authMode === "login" ? "current-password" : "new-password"} />
              </Form.Item>
            )}
            <Space direction="vertical" size={10} className="full-width">
              <Button type="primary" htmlType="submit" loading={loading} block size="large" icon={<ArrowRight size={17} />}>
                {authMode === "login" ? "登录进入生成台" : authMode === "register" ? "验证并注册" : "重置密码"}
              </Button>
              {authMode === "login" ? (
                <Space.Compact className="full-width">
                  <Button htmlType="button" onClick={() => setAuthMode("register")} block size="large" icon={<ShieldCheck size={17} />}>
                    切换到注册
                  </Button>
                  <Button htmlType="button" onClick={() => setAuthMode("reset")} block size="large">
                    找回密码
                  </Button>
                </Space.Compact>
              ) : (
                <Button htmlType="button" onClick={() => setAuthMode("login")} block size="large">
                  返回登录
                </Button>
              )}
            </Space>
          </Form>
        </div>
      </section>
    </main>
  );
}

function GeneratePage({
  token,
  username,
  userEmail,
  onLogout,
}: {
  token: string;
  username: string;
  userEmail: string;
  onLogout: () => void;
}) {
  const { message } = AntdApp.useApp();
  const [form] = Form.useForm<ProductFormValues>();
  const [activeWorkbenchPage, setActiveWorkbenchPage] = useState<"home" | "gallery" | "account">("home");
  const [productImage, setProductImage] = useState<File | null>(null);
  const [productImagePreviewUrl, setProductImagePreviewUrl] = useState("");
  const [certificateReferenceImage, setCertificateReferenceImage] = useState<File | null>(null);
  const [certificateReferencePreviewUrl, setCertificateReferencePreviewUrl] = useState("");
  const [packageReferenceImage, setPackageReferenceImage] = useState<File | null>(null);
  const [packageReferencePreviewUrl, setPackageReferencePreviewUrl] = useState("");
  const [product, setProduct] = useState<ProductResponse | null>(null);
  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [generation, setGeneration] = useState<GenerationResponse | null>(null);
  const [previews, setPreviews] = useState<PreviewImage[]>([]);
  const [galleryPreviews, setGalleryPreviews] = useState<PreviewImage[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [galleryLoaded, setGalleryLoaded] = useState(false);
  const [galleryCursor, setGalleryCursor] = useState<string | null>(null);
  const [galleryPageCursors, setGalleryPageCursors] = useState<(string | null)[]>([null]);
  const [galleryPageIndex, setGalleryPageIndex] = useState(0);
  const [account, setAccount] = useState<AccountResponse | null>(null);
  const [accountTransactions, setAccountTransactions] = useState<AccountTransaction[]>([]);
  const [accountLoading, setAccountLoading] = useState(false);
  const [rechargeOpen, setRechargeOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lastError, setLastError] = useState("");
  const [liveProgress, setLiveProgress] = useState(0);
  const [appVersion, setAppVersion] = useState(APP_VERSION);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResponse | null>(null);
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [installingUpdate, setInstallingUpdate] = useState(false);
  const [updateDownloadProgress, setUpdateDownloadProgress] = useState<number | null>(null);
  const updateCheckedRef = useRef(false);

  const progress = useMemo(() => {
    return generationProgress({
      outputCount: generation?.outputs.length ?? 0,
      workflowPercent: liveProgress,
      loading,
    });
  }, [generation, liveProgress, loading]);

  useEffect(() => {
    if (!loading) {
      return;
    }

    const intervalId = window.setInterval(() => {
      setLiveProgress((currentProgress) => nextLiveGenerationProgress(currentProgress, generation?.outputs.length ?? 0));
    }, 1200);

    return () => window.clearInterval(intervalId);
  }, [generation?.outputs.length, loading]);

  useEffect(() => {
    let active = true;
    window.zhifengUpdates
      ?.getAppVersion()
      .then((version) => {
        if (active && version) {
          setAppVersion(version);
        }
      })
      .catch(() => {
        // The browser dev server does not expose the Electron bridge.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (updateCheckedRef.current || !appVersion) {
      return;
    }
    updateCheckedRef.current = true;
    let active = true;

    async function checkForUpdates() {
      try {
        const update = await checkForAppUpdate({ currentVersion: appVersion });
        if (!active) {
          return;
        }
        setUpdateInfo(update);
        const dismissedVersion = readDismissedUpdateVersion(window.localStorage);
        if (shouldOpenUpdateModal(update, dismissedVersion)) {
          setUpdateModalOpen(true);
        }
      } catch (error) {
        if (!isNoReleaseAvailableError(error)) {
          console.warn("Update check failed", error);
        }
      }
    }

    void checkForUpdates();
    return () => {
      active = false;
    };
  }, [appVersion]);

  useEffect(() => {
    return () => previews.forEach((preview) => URL.revokeObjectURL(preview.url));
  }, [previews]);

  useEffect(() => {
    if (!productImagePreviewUrl) {
      return;
    }
    return () => URL.revokeObjectURL(productImagePreviewUrl);
  }, [productImagePreviewUrl]);

  useEffect(() => {
    if (!certificateReferencePreviewUrl) {
      return;
    }
    return () => URL.revokeObjectURL(certificateReferencePreviewUrl);
  }, [certificateReferencePreviewUrl]);

  useEffect(() => {
    if (!packageReferencePreviewUrl) {
      return;
    }
    return () => URL.revokeObjectURL(packageReferencePreviewUrl);
  }, [packageReferencePreviewUrl]);

  const uploadProps = createLocalImageUploadProps((file) => {
    setProductImage(file);
    setProductImagePreviewUrl(URL.createObjectURL(file));
  });
  const certificateReferenceUploadProps = createLocalImageUploadProps((file) => {
    setCertificateReferenceImage(file);
    setCertificateReferencePreviewUrl(URL.createObjectURL(file));
  });
  const packageReferenceUploadProps = createLocalImageUploadProps((file) => {
    setPackageReferenceImage(file);
    setPackageReferencePreviewUrl(URL.createObjectURL(file));
  });

  function createLocalImageUploadProps(onFile: (file: File) => void): UploadProps {
    return {
    accept: "image/png,image/jpeg,image/webp",
    maxCount: 1,
    showUploadList: false,
    beforeUpload(file) {
      onFile(file);
      return false;
    },
    };
  }

  function clearProductImage() {
    setProductImage(null);
    setProductImagePreviewUrl("");
  }

  function clearCertificateReferenceImage() {
    setCertificateReferenceImage(null);
    setCertificateReferencePreviewUrl("");
  }

  function clearPackageReferenceImage() {
    setPackageReferenceImage(null);
    setPackageReferencePreviewUrl("");
  }

  async function loadGalleryPage(cursor: string | null = null, pageIndex = 0) {
    setGalleryLoading(true);
    try {
      const galleryOutputsPath = `/gallery/outputs?limit=${galleryPageLimit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
      const galleryOutputs = await apiGet<ProjectOutputsResponse>(galleryOutputsPath, { token });
      const previewImages = createGalleryPreviews(galleryOutputs.items);
      setGalleryPreviews(previewImages);
      setGalleryCursor(galleryOutputs.next_cursor ?? null);
      setGalleryPageIndex(pageIndex);
      setGalleryLoaded(true);
    } catch (error) {
      message.error(userFacingErrorMessage(error, "gallery"));
    } finally {
      setGalleryLoading(false);
    }
  }

  async function openGallery() {
    setActiveWorkbenchPage("gallery");
    if (galleryLoaded) {
      return;
    }
    await loadGalleryPage(galleryPageCursors[galleryPageIndex] ?? null, galleryPageIndex);
  }

  async function loadNextGalleryPage() {
    if (!galleryCursor) {
      return;
    }
    const nextPageIndex = galleryPageIndex + 1;
    setGalleryPageCursors((current) => {
      const next = [...current];
      next[nextPageIndex] = galleryCursor;
      return next;
    });
    await loadGalleryPage(galleryCursor, nextPageIndex);
  }

  async function loadPreviousGalleryPage() {
    if (galleryPageIndex <= 0) {
      return;
    }
    const previousPageIndex = galleryPageIndex - 1;
    await loadGalleryPage(galleryPageCursors[previousPageIndex] ?? null, previousPageIndex);
  }

  function resetGalleryCache() {
    setGalleryPreviews([]);
    setGalleryCursor(null);
    setGalleryPageCursors([null]);
    setGalleryPageIndex(0);
    setGalleryLoaded(false);
  }

  async function downloadOriginalOutput(output: OutputResponse) {
    try {
      const blob = await apiDownload(outputOriginalDownloadPath(output), { token });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${output.output_type}.png`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      message.error(userFacingErrorMessage(error, "download"));
    }
  }

  async function loadAccount() {
    setAccountLoading(true);
    try {
      const [accountPayload, transactionsPayload] = await Promise.all([
        apiGet<AccountResponse>("/account/me", { token }),
        apiGet<AccountTransactionsResponse>("/account/transactions", { token }),
      ]);
      setAccount(accountPayload);
      setAccountTransactions(transactionsPayload.items);
    } catch (error) {
      message.error(userFacingErrorMessage(error, "account"));
    } finally {
      setAccountLoading(false);
    }
  }

  async function openAccount() {
    setActiveWorkbenchPage("account");
    await loadAccount();
  }

  function dismissUpdatePrompt() {
    if (updateInfo?.force_update) {
      return;
    }
    if (updateInfo?.latest_version) {
      rememberDismissedUpdateVersion(window.localStorage, updateInfo.latest_version);
    }
    setUpdateModalOpen(false);
  }

  async function installUpdate() {
    if (!updateInfo) {
      return;
    }
    setInstallingUpdate(true);
    setUpdateDownloadProgress(0);
    const unsubscribeProgress = window.zhifengUpdates?.onDownloadProgress?.((progress) => {
      setUpdateDownloadProgress(progress.percent);
    });
    try {
      if (window.zhifengUpdates?.install) {
        await window.zhifengUpdates.install(updateInfo);
        message.success("安装程序已启动");
        return;
      }
      triggerBrowserDownload(updateDownloadHref(updateInfo.download_url), `zhifeng-image-${updateInfo.latest_version}.exe`);
      setUpdateDownloadProgress(100);
      message.info("安装包已开始下载，请下载完成后运行安装。");
    } catch (error) {
      message.error(errorDisplayMessage(error));
    } finally {
      unsubscribeProgress?.();
      setInstallingUpdate(false);
      setUpdateDownloadProgress(null);
    }
  }

  async function runFlow(values: ProductFormValues) {
    if (!productImage) {
      message.error("请先上传商品图");
      return;
    }

    setLoading(true);
    setLiveProgress(0);
    let activeProject: ProjectResponse | null = null;
    try {
      previews.forEach((preview) => URL.revokeObjectURL(preview.url));
      setPreviews([]);
      setGeneration(null);
      setLastError("");
      setProject(null);
      setAsset(null);
      setProduct(null);
      setLiveProgress(3);

      const barcode = await apiPost<BarcodeValidationResponse>(
        "/barcodes/validate",
        { barcode_type: values.barcodeType, raw_value: values.barcodeValue },
        { token },
      );
      setLiveProgress(12);
      if (!barcode.can_confirm) {
        const suggested = suggestedBarcodeValue(barcode);
        if (suggested) {
          form.setFieldsValue({ barcodeValue: suggested });
        }
        throw new Error(barcodeValidationMessage(barcode));
      }

      const createdProduct = await apiPost<ProductResponse>(
        "/products",
        buildProductCreatePayload(values),
        { token },
      );
      setProduct(createdProduct);
      setLiveProgress(24);

      const uploadedAsset = await uploadProductOriginal(productImage, createdProduct.id, token);
      setAsset(uploadedAsset);
      if (certificateReferenceImage) {
        await uploadReferenceAsset(certificateReferenceImage, createdProduct.id, token, "certificate_reference");
      }
      if (packageReferenceImage) {
        await uploadReferenceAsset(packageReferenceImage, createdProduct.id, token, "package_reference");
      }
      setLiveProgress(38);

      const createdProject = await apiPost<ProjectResponse>(
        "/projects",
        buildProjectCreatePayload(values, createdProduct.id, barcode.normalized_value),
        { token },
      );
      activeProject = createdProject;
      setProject(createdProject);
      setLiveProgress(52);

      setLiveProgress(64);
      const queuedGeneration = await apiPost<GenerationResponse>(`/projects/${createdProject.id}/generate`, undefined, {
        token,
      });
      setGeneration(queuedGeneration);
      let workflowPercent = 64;
      const generated = await waitForGenerationCompletion(queuedGeneration.id, token, (job) => {
        workflowPercent = nextLiveGenerationProgress(workflowPercent, job.outputs.length);
        setGeneration(job);
        setLiveProgress(
          generationProgress({
            outputCount: job.outputs.length,
            workflowPercent,
            loading: true,
          }),
        );
      });
      setGeneration(generated);
      void loadAccount();
      setLiveProgress(generationProgress(generated.outputs.length));

      const previewImages = await createOutputPreviews(
        generated.outputs,
        (output) => apiDownload(`/outputs/${output.id}/download`, { token }),
        (blob) => URL.createObjectURL(blob),
      );
      setPreviews(previewImages);
      resetGalleryCache();
      message.success("五图已生成，可预览和下载");
    } catch (error) {
      const displayMessage = generationErrorMessage(error);
      const generationTimedOut = isGenerationTimeoutError(error);
      setLastError(displayMessage);
      let recoveredCount = 0;
      if (!generationTimedOut && activeProject) {
        setProject({ ...activeProject, status: "failed" });
      }
      if (activeProject) {
        try {
          const partialOutputs = await apiGet<ProjectOutputsResponse>(`/projects/${activeProject.id}/outputs`, { token });
          if (partialOutputs.items.length > 0) {
            const previewImages = await createOutputPreviews(
              partialOutputs.items,
              (output) => apiDownload(`/outputs/${output.id}/download`, { token }),
              (blob) => URL.createObjectURL(blob),
            );
            setGeneration({
              id: "",
              status: generationTimedOut ? "running" : "failed",
              provider_name: "partial",
              outputs: partialOutputs.items,
            });
            setPreviews(previewImages);
            recoveredCount = previewImages.length;
            setLiveProgress(generationProgress(recoveredCount));
          }
        } catch {
          // Preserve the original generation error if partial preview recovery also fails.
        }
      }
      if (recoveredCount === 0 && !generationTimedOut) {
        setLiveProgress(0);
      }
      if (recoveredCount > 0 || generationTimedOut) {
        message.warning(`${displayMessage}；已保留 ${recoveredCount} 张阶段性输出。`);
      } else {
        message.error(displayMessage);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="desktop-shell workbench-shell">
      <section className="source-stage workbench-stage" aria-label="智枫生图生成工作台">
        <AmbientLayer />
      <header className="app-topbar">
        <div className="topbar-brand">
          <BrandMark />
          <div>
            <strong>智枫生图</strong>
            <span>V2.0 商品五图生成台</span>
          </div>
        </div>
        <nav className="topbar-nav" aria-label="工作台导航">
          <Button
            type={activeWorkbenchPage === "home" ? "primary" : "text"}
            icon={<Home size={15} />}
            onClick={() => setActiveWorkbenchPage("home")}
          >
            首页
          </Button>
          <Button
            type={activeWorkbenchPage === "gallery" ? "primary" : "text"}
            icon={<Images size={15} />}
            onClick={openGallery}
          >
            图库
          </Button>
          <Button
            type={activeWorkbenchPage === "account" ? "primary" : "text"}
            icon={<Wallet size={15} />}
            onClick={openAccount}
          >
            账户
          </Button>
        </nav>
        <div className="topbar-user">
          <UpdateBadge
            version={appVersion}
            hasNotice={hasUpdateNotice(updateInfo) && !updateModalOpen}
            onClick={() => setUpdateModalOpen(true)}
          />
          <Tag className="soft-tag">
            <UserRound size={13} />
            {accountDisplayName(account, username, userEmail)}
          </Tag>
          <Button onClick={onLogout} icon={<LogOut size={16} />}>
            退出
          </Button>
        </div>
      </header>
      <UpdateModal
        open={updateModalOpen}
        update={updateInfo}
        appVersion={appVersion}
        installing={installingUpdate}
        downloadProgress={updateDownloadProgress}
        onInstall={installUpdate}
        onLater={dismissUpdatePrompt}
      />

      {activeWorkbenchPage === "home" ? (
      <section className="workbench-grid">
        <aside id="config" className="config-rail app-panel">
          <div className="section-heading compact">
            <span className="icon-chip">
              <Wand2 size={18} />
            </span>
            <div>
              <Title level={3}>生成配置</Title>
              <Paragraph>商品资料、源图和正式条码数字。</Paragraph>
            </div>
          </div>

          <Form form={form} layout="vertical" initialValues={productInitialValues} onFinish={runFlow} requiredMark={false}>
            <Form.Item label="商品图" required>
              {productImagePreviewUrl ? (
                <div className="upload-preview-card">
                  <Image
                    src={productImagePreviewUrl}
                    alt="已上传商品图预览"
                    className="upload-preview-image"
                    preview={{ mask: "放大预览" }}
                  />
                  <Button
                    type="text"
                    danger
                    className="upload-delete-button"
                    aria-label="删除已上传商品图"
                    icon={<Trash2 size={18} />}
                    disabled={loading}
                    onClick={clearProductImage}
                  />
                </div>
              ) : (
                <Upload.Dragger {...uploadProps} disabled={loading} className="desktop-uploader">
                  <UploadCloud size={26} />
                  <Text strong>选择或拖入商品图片</Text>
                  <Paragraph>PNG / JPEG / WebP，图片模型只处理视觉素材。</Paragraph>
                </Upload.Dragger>
              )}
            </Form.Item>

            <Row gutter={12}>
              <Col span={12}>
                <Form.Item label="合格证参考图">
                  {certificateReferencePreviewUrl ? (
                    <div className="upload-preview-card">
                      <Image
                        src={certificateReferencePreviewUrl}
                        alt="已上传合格证参考图预览"
                        className="upload-preview-image"
                        preview={{ mask: "放大预览" }}
                      />
                      <Button
                        type="text"
                        danger
                        className="upload-delete-button"
                        aria-label="删除已上传合格证参考图"
                        icon={<Trash2 size={18} />}
                        disabled={loading}
                        onClick={clearCertificateReferenceImage}
                      />
                    </div>
                  ) : (
                    <Upload.Dragger {...certificateReferenceUploadProps} disabled={loading} className="desktop-uploader">
                      <UploadCloud size={22} />
                      <Text strong>上传合格证参考</Text>
                      <Paragraph>可选，参考样式。</Paragraph>
                    </Upload.Dragger>
                  )}
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="包装箱参考图">
                  {packageReferencePreviewUrl ? (
                    <div className="upload-preview-card">
                      <Image
                        src={packageReferencePreviewUrl}
                        alt="已上传包装箱参考图预览"
                        className="upload-preview-image"
                        preview={{ mask: "放大预览" }}
                      />
                      <Button
                        type="text"
                        danger
                        className="upload-delete-button"
                        aria-label="删除已上传包装箱参考图"
                        icon={<Trash2 size={18} />}
                        disabled={loading}
                        onClick={clearPackageReferenceImage}
                      />
                    </div>
                  ) : (
                    <Upload.Dragger {...packageReferenceUploadProps} disabled={loading} className="desktop-uploader">
                      <UploadCloud size={22} />
                      <Text strong>上传包装箱参考</Text>
                      <Paragraph>可选，参考样式。</Paragraph>
                    </Upload.Dragger>
                  )}
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="name" label="商品名称" rules={[{ required: true, whitespace: true, message: "请输入商品名称" }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="brand" label="品牌" rules={[{ required: true, whitespace: true, message: "请输入品牌" }]}>
                  <Input />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={12}>
              <Col span={24}>
                <Form.Item name="model" label="规格型号">
                  <Input />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={12}>
              <Col span={10}>
                <Form.Item name="companyName" label="公司名称" rules={[{ required: true, whitespace: true, message: "请输入公司名称" }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="productionDate" label="生产日期" rules={[{ required: true, message: "请选择日期" }]}>
                  <Input type="date" />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="inspector" label="检验员" rules={[{ required: true, whitespace: true, message: "请输入检验员" }]}>
                  <Input />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={12}>
              <Col span={10}>
                <Form.Item name="manufacturerName" label="生产厂家" rules={[{ required: true, whitespace: true, message: "请输入生产厂家" }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col span={14}>
                <Form.Item name="manufacturerAddress" label="厂商地址" rules={[{ required: true, whitespace: true, message: "请输入厂商地址" }]}>
                  <Input />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={12}>
              <Col span={10}>
                <Form.Item name="barcodeType" label="条码制式" rules={[{ required: true, message: "请选择条码制式" }]}>
                  <Select
                    options={[
                      { label: "EAN-13", value: "EAN_13" },
                      { label: "EAN-8", value: "EAN_8" },
                      { label: "UPC-A", value: "UPC_A" },
                      { label: "Code 128 数字", value: "CODE_128" },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={14}>
                <Form.Item name="barcodeValue" label="条码数字" rules={[{ required: true, whitespace: true, message: "请输入条码数字" }]}>
                  <Input />
                </Form.Item>
              </Col>
            </Row>

            <Button type="primary" htmlType="submit" loading={loading} block size="large" icon={<Play size={17} />}>
              上传商品图并生成五张图片
            </Button>
          </Form>
        </aside>

        <section className="main-stage">
          {lastError ? (
            <Alert
              className="error-banner"
              type="error"
              showIcon
              icon={<AlertCircle size={18} />}
              message="生成失败"
              description={lastError}
            />
          ) : null}

          <section id="pipeline" className="app-panel pipeline-panel">
            <div className="pipeline-copy">
              <Tag className="soft-tag red-tag">
                <Sparkles size={13} />
                AI-Native Workbench
              </Tag>
              <Title level={2}>五图生成工作台</Title>
              <Paragraph>
                源图进入模型生成视觉内容；正式文字、合格证字段和条码由系统后置合成，保证下载前的质量门槛。
              </Paragraph>
            </div>
            <div className="progress-orb" aria-label={`当前进度 ${progress}%`}>
              <Progress
                type="circle"
                percent={progress}
                size={142}
                status={lastError ? "exception" : loading ? "active" : "normal"}
              />
            </div>
          </section>

          <Row gutter={[14, 14]} className="status-strip">
            <Col xs={24} md={8}>
              <div className="metric-tile">
                <ImageIcon size={18} />
                <Statistic title="素材状态" value={asset ? "已上传" : "未上传"} />
              </div>
            </Col>
            <Col xs={24} md={8}>
              <div className="metric-tile">
                <Workflow size={18} />
                <Statistic title="项目状态" value={project?.status ?? "未创建"} />
              </div>
            </Col>
            <Col xs={24} md={8}>
              <div className="metric-tile">
                <Gauge size={18} />
                <Statistic title="输出数量" value={generation?.outputs.length ?? 0} suffix="/ 5" />
              </div>
            </Col>
          </Row>

          <section id="outputs" className="app-panel">
            <div className="section-heading compact split-heading">
              <div className="heading-left">
                <span className="icon-chip">
                  <ImageIcon size={18} />
                </span>
                <div>
                  <Title level={3}>五图预览</Title>
                  <Paragraph>生成后可直接预览并下载单张 PNG。</Paragraph>
                </div>
              </div>
              <Tag className="soft-tag">
                <Barcode size={13} />
                条码系统合成
              </Tag>
            </div>
            {previews.length === 0 ? (
              <Alert
                type={lastError ? "error" : "info"}
                showIcon
                message={lastError ? "生成失败，未产生输出" : "还没有输出"}
                description={lastError ? "请根据上方错误处理后重新提交。" : "提交左侧表单后会生成五张图片预览。"}
              />
            ) : (
              <List
                grid={{ gutter: 14, xs: 1, sm: 2, lg: 3 }}
                dataSource={previews}
                renderItem={(item) => (
                  <List.Item>
                    <article className="output-card">
                      <div className="output-card-top">
                        <strong>{outputName[item.output_type] ?? item.output_type}</strong>
                        <Tag color="green">{item.quality_status}</Tag>
                      </div>
                      <Image
                        src={item.url}
                        alt={outputName[item.output_type] ?? item.output_type}
                        className="output-image"
                        style={{ width: "100%", maxHeight: 260, objectFit: "contain" }}
                      />
                      <div className="output-card-bottom">
                        <Text type="secondary">
                          {item.width} x {item.height}
                        </Text>
                        <Button href={item.url} download={`${item.output_type}.png`} size="small" icon={<Download size={14} />}>
                          下载
                        </Button>
                      </div>
                    </article>
                  </List.Item>
                )}
              />
            )}
          </section>

        </section>
      </section>
      ) : null}
      {activeWorkbenchPage === "gallery" ? (
        <section className="gallery-page app-panel" aria-label="用户图库">
          <div className="section-heading compact split-heading">
            <div className="heading-left">
              <span className="icon-chip">
                <Images size={18} />
              </span>
              <div>
                <Title level={3}>图库</Title>
                <Paragraph>展示当前账号已生成的商品图。</Paragraph>
              </div>
            </div>
            <Tag className="soft-tag">
              第 {galleryPageIndex + 1} 页 · {galleryPreviews.length} 张图片
            </Tag>
          </div>
          {galleryLoading && galleryPreviews.length === 0 ? (
            <Alert type="info" showIcon message="正在加载图库" description="正在读取当前账号下已经生成过的商品图。" />
          ) : galleryPreviews.length === 0 ? null : (
            <>
            <List
              grid={{ gutter: 14, xs: 1, sm: 2, lg: 4 }}
              dataSource={galleryPreviews}
              renderItem={(item) => (
                <List.Item>
                  <article className="output-card gallery-card">
                    <div className="output-card-top">
                      <strong>{outputName[item.output_type] ?? item.output_type}</strong>
                      <Tag color="green">{item.quality_status}</Tag>
                    </div>
                    <GalleryPreviewImage item={item} token={token} />
                    <div className="output-card-bottom">
                      <Text type="secondary">
                        {item.width} x {item.height}
                      </Text>
                      <Button onClick={() => void downloadOriginalOutput(item)} size="small" icon={<Download size={14} />}>
                        下载
                      </Button>
                    </div>
                  </article>
                </List.Item>
              )}
            />
            {galleryPageIndex > 0 || galleryCursor ? (
              <div className="gallery-load-more">
                <Button disabled={galleryPageIndex === 0 || galleryLoading} onClick={() => void loadPreviousGalleryPage()}>
                  上一页
                </Button>
                <Button loading={galleryLoading} disabled={!galleryCursor} onClick={() => void loadNextGalleryPage()}>
                  下一页
                </Button>
              </div>
            ) : null}
            </>
          )}
        </section>
      ) : null}
      {activeWorkbenchPage === "account" ? (
        <section className="account-page app-panel" aria-label="account">
          <div className="section-heading compact split-heading">
            <div className="heading-left">
              <span className="icon-chip">
                <Wallet size={18} />
              </span>
              <div>
                <Title level={3}>账户</Title>
                <Paragraph>查看当前账号余额与充值入口。</Paragraph>
              </div>
            </div>
            <Button onClick={loadAccount} loading={accountLoading} icon={<Workflow size={15} />}>
              刷新余额
            </Button>
          </div>

          <div className="account-summary-grid">
            <article className="account-summary-card">
              <Text type="secondary">登录账号</Text>
              <strong>{account?.user.email ?? userEmail}</strong>
              <span>{account?.user.username || account?.username || "未设置用户名"}</span>
            </article>
            <article className="account-summary-card balance-card">
              <Text type="secondary">账户余额</Text>
              <strong>{account?.balance_points ?? 0}</strong>
              <span>可用 {account?.available_points ?? 0} 点，预占 {account?.reserved_points ?? 0} 点</span>
            </article>
            <article className="account-summary-card">
              <Text type="secondary">最近到期</Text>
              <strong>{account?.next_expiring_lot?.remaining_points ?? 0}</strong>
              <span>{formatExpiry(account?.next_expiring_lot?.expires_at)}</span>
            </article>
          </div>

          <section className="recharge-section" aria-label="recharge package">
            <Title level={4}>充值套餐</Title>
            <article className="recharge-card">
              <Tag color="blue" className="recommend-tag">
                推荐
              </Tag>
              <div className="recharge-card-copy">
                <Text strong>3699元套餐</Text>
                <Title level={2}>
                  10,000 <span>积分</span>
                </Title>
                <Space direction="vertical" size={4}>
                  <Text>有效期：充值后一年内有效</Text>
                  <Text>约可生成 1000 次</Text>
                  <Text>每次生成 5 张图扣 10 点</Text>
                </Space>
              </div>
              <Button type="primary" block size="large" icon={<CreditCard size={16} />} onClick={() => setRechargeOpen(true)}>
                立即充值
              </Button>
            </article>
          </section>

          <section className="transactions-section" aria-label="transactions">
            <div className="section-heading compact">
              <span className="icon-chip">
                <Gauge size={18} />
              </span>
              <div>
                <Title level={4}>余额明细</Title>
                <Paragraph>展示当前账号最近的充值、扣费和释放记录。</Paragraph>
              </div>
            </div>
            {accountTransactions.length === 0 ? (
              <Alert type="info" showIcon message="暂无余额记录" description="充值或生成图片后会显示余额变动。" />
            ) : (
              <List
                dataSource={accountTransactions}
                renderItem={(item) => (
                  <List.Item>
                    <div className="transaction-row">
                      <div>
                        <strong>{transactionName(item.type)}</strong>
                        <span>{transactionDetailText(item)}</span>
                      </div>
                      <Text className={item.points < 0 ? "points-minus" : "points-plus"}>
                        {item.points > 0 ? "+" : ""}
                        {item.points}
                      </Text>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </section>

          <Modal open={rechargeOpen} title="联系客服充值" footer={null} centered onCancel={() => setRechargeOpen(false)}>
            <div className="recharge-modal-content">
              <QrCode size={22} />
              <Paragraph strong>请使用微信扫码添加客服，联系客服充值。</Paragraph>
              <img src="/wechat-service-qr.jpg" alt="微信客服二维码" />
            </div>
          </Modal>
        </section>
      ) : null}
      </section>
    </main>
  );
}

function GalleryPreviewImage({ item, token }: { item: OutputResponse; token: string }) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setPreviewUrl("");
    setFailed(false);

    apiDownload(outputPreviewDownloadPath(item), { token })
      .then((blob) => {
        const nextUrl = URL.createObjectURL(blob);
        if (!active) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        objectUrl = nextUrl;
        setPreviewUrl(nextUrl);
      })
      .catch(() => {
        if (active) {
          setFailed(true);
        }
      });

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [item, token]);

  if (failed) {
    return (
      <div
        className="output-image"
        style={{ alignItems: "center", display: "flex", justifyContent: "center", minHeight: 180, width: "100%" }}
      >
        缩略图加载失败
      </div>
    );
  }

  if (!previewUrl) {
    return (
      <div
        className="output-image"
        style={{ alignItems: "center", display: "flex", justifyContent: "center", minHeight: 180, width: "100%" }}
      >
        缩略图加载中
      </div>
    );
  }

  return (
    <Image
      src={previewUrl}
      alt={outputName[item.output_type] ?? item.output_type}
      className="output-image"
      style={{ width: "100%", maxHeight: 280, objectFit: "contain" }}
    />
  );
}

async function uploadProductOriginal(file: File, productId: string, token: string): Promise<AssetResponse> {
  return uploadProductBoundAsset(file, productId, token, "product_original");
}

async function uploadReferenceAsset(
  file: File,
  productId: string,
  token: string,
  assetType: "certificate_reference" | "package_reference",
): Promise<AssetResponse> {
  return uploadProductBoundAsset(file, productId, token, assetType);
}

async function uploadProductBoundAsset(
  file: File,
  productId: string,
  token: string,
  assetType: "product_original" | "certificate_reference" | "package_reference",
): Promise<AssetResponse> {
  const presign = await apiPost<UploadPresignResponse>(
    "/uploads/presign",
    {
      asset_type: assetType,
      filename: file.name,
      content_type: file.type || "image/png",
      size_bytes: file.size,
    },
    { token },
  );
  await apiPutRaw(presign.upload_url, file, presign.headers);
  return await apiPost<AssetResponse>(
    "/uploads/complete",
    { upload_token: presign.upload_token, product_id: productId },
    { token },
  );
}

async function waitForGenerationCompletion(
  jobId: string,
  token: string,
  onProgress: (job: GenerationResponse) => void,
): Promise<GenerationResponse> {
  const deadline = Date.now() + 20 * 60 * 1000;
  while (Date.now() < deadline) {
    await delay(1200);
    const job = await apiGet<GenerationResponse>(`/generation-jobs/${jobId}`, { token });
    onProgress(job);
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed") {
      throw new Error(`${job.error_code || "IMAGE_PROVIDER_FAILED"}: ${job.error_message || "Generation failed"}`);
    }
  }
  throw new Error("GENERATION_TIMEOUT: Generation did not finish in time.");
}

function isGenerationTimeoutError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("GENERATION_TIMEOUT");
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function triggerBrowserDownload(href: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function isNoReleaseAvailableError(error: unknown): boolean {
  return error instanceof Error && error.message.includes("NO_RELEASE_AVAILABLE");
}

function errorDisplayMessage(error: unknown): string {
  return userFacingErrorMessage(error, "update");
}

function formatExpiry(value?: string): string {
  if (!value) {
    return "暂无有效点数";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function transactionName(type: string): string {
  const names: Record<string, string> = {
    recharge: "充值入账",
    generation_charge: "生成扣费",
    generation_release: "释放预占",
    expire: "点数到期",
  };
  return names[type] ?? type;
}

async function requestRegistrationCode(email: string): Promise<RegistrationCodeResponse> {
  return await apiPost<RegistrationCodeResponse>("/auth/registration-code", { email });
}

async function requestPasswordResetCode(email: string): Promise<RegistrationCodeResponse> {
  return await apiPost<RegistrationCodeResponse>("/auth/password-reset-code", { email });
}

async function resetPassword(email: string, verificationCode: string, newPassword: string): Promise<void> {
  await apiPost<{ email: string; status: string }>("/auth/reset-password", {
    email,
    verification_code: verificationCode,
    new_password: newPassword,
  });
}

async function registerAccount(
  username: string,
  email: string,
  verificationCode: string,
  password: string,
): Promise<AuthResponse> {
  return await apiPost<AuthResponse>("/auth/register", {
    username,
    email,
    verification_code: verificationCode,
    password,
  });
}
