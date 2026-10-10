export type AuthUser = {
  id: string;
  email: string;
  phone?: string;
  username?: string;
  email_verified?: boolean;
  phone_verified?: boolean;
};

export type AuthResponse = {
  access_token: string;
  user: AuthUser;
};

export type RegistrationCodeResponse = {
  phone: string;
  expires_in_seconds: number;
  debug_code?: string;
};

export type LoginRequestBody = {
  phone?: string;
  username?: string;
  password: string;
};

export function loginRequestBody(account: string, password: string): LoginRequestBody {
  const normalized = account.trim();
  if (/^\d+$/.test(normalized)) {
    return { phone: normalized, password };
  }
  return { username: normalized, password };
}

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
  if (message.includes("PHONE_CODE_INVALID")) {
    return "验证码不正确或已过期，请重新获取后再提交";
  }
  if (message.includes("INVITATION_CODE_INVALID")) {
    return "邀请码不存在或未启用，请确认后再提交";
  }
  if (message.includes("EMAIL_DOMAIN_UNSUPPORTED")) {
    return "邮箱域名暂不支持";
  }
  if (
    message.includes("EMAIL_CODE_RATE_LIMITED") ||
    message.includes("PHONE_CODE_RATE_LIMITED") ||
    message.includes("REGISTER_RATE_LIMITED") ||
    message.includes("LOGIN_RATE_LIMITED")
  ) {
    return "请求频繁，请稍后再试";
  }
  if (message.includes("SMTP_NOT_CONFIGURED")) {
    return "邮件发送服务尚未配置，无法发送验证码";
  }
  if (message.includes("SMS_NOT_CONFIGURED")) {
    return "短信验证码服务尚未配置，无法发送验证码";
  }
  if (message.includes("LimitExceeded.PhoneNumberDailyLimit")) {
    return "请求频率过高，请稍后再试";
  }
  if (message.includes("SMS_PROVIDER_FAILED")) {
    return "短信服务发送失败，请查看后端日志或腾讯云短信控制台错误原因";
  }
  if (message.includes("EMAIL_NOT_VERIFIED")) {
    return "账号还没有完成邮箱验证，请先完成验证";
  }
  if (message.includes("PHONE_NOT_VERIFIED")) {
    return "账号还没有完成手机号验证，请先完成验证";
  }
  if (message.includes("ACCOUNT_INACTIVE")) {
    return "账号状态不可用，请联系管理员";
  }
  if (message.includes("EMAIL_ALREADY_REGISTERED")) {
    return "该邮箱已经注册，请直接登录";
  }
  if (message.includes("PHONE_ALREADY_REGISTERED")) {
    return "该手机号已经注册，请直接登录";
  }
  if (message.includes("USERNAME_ALREADY_REGISTERED")) {
    return "该用户名已经注册，请换一个用户名";
  }
  if (message.includes("INVALID_CREDENTIALS")) {
    return "账号或密码不正确";
  }
  if (message.includes("PASSWORD_RESET_IN_PROGRESS")) {
    return "密码重置正在处理，请稍后再试";
  }
  if (message.includes("REFRESH_INVALID") || message.includes("REFRESH_REQUIRED")) {
    return "登录已过期，请重新输入密码登录";
  }
  return "认证失败，请稍后重试";
}
