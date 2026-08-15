export type AuthUser = {
  id: string;
  email: string;
  username?: string;
  email_verified?: boolean;
};

export type AuthResponse = {
  access_token: string;
  user: AuthUser;
};

export type RegistrationCodeResponse = {
  email: string;
  expires_in_seconds: number;
  debug_code?: string;
};

export async function restoreAuthFromRefresh(refresh: () => Promise<AuthResponse>): Promise<AuthResponse | null> {
  try {
    return await refresh();
  } catch {
    return null;
  }
}

export function authErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (message.includes("EMAIL_CODE_INVALID")) {
    return "验证码不正确或已过期，请重新获取后再提交";
  }
  if (message.includes("EMAIL_DOMAIN_UNSUPPORTED")) {
    return "邮箱域名暂不支持";
  }
  if (message.includes("EMAIL_CODE_RATE_LIMITED")) {
    return "验证码请求过于频繁，请稍后再试";
  }
  if (message.includes("SMTP_NOT_CONFIGURED")) {
    return "邮件发送服务尚未配置，无法发送验证码";
  }
  if (message.includes("EMAIL_NOT_VERIFIED")) {
    return "账号还没有完成邮箱验证，请先完成验证";
  }
  if (message.includes("EMAIL_ALREADY_REGISTERED")) {
    return "该邮箱已经注册，请直接登录";
  }
  if (message.includes("INVALID_CREDENTIALS")) {
    return "邮箱或密码不正确";
  }
  if (message.includes("PASSWORD_RESET_IN_PROGRESS")) {
    return "密码重置正在处理，请稍后再试";
  }
  if (message.includes("REFRESH_INVALID") || message.includes("REFRESH_REQUIRED")) {
    return "登录已过期，请重新输入密码登录";
  }
  return message || "认证失败，请稍后重试";
}
