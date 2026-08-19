export type AccountDisplaySource = {
  user?: {
    username?: string | null;
    email?: string | null;
  } | null;
  username?: string | null;
  email?: string | null;
} | null;

export type TransactionDisplaySource = {
  type: string;
  points: number;
  remark?: string | null;
  created_at?: string | null;
};

export function accountDisplayName(
  account: AccountDisplaySource,
  fallbackUsername: string,
  fallbackEmail: string,
): string {
  return (
    cleanText(account?.user?.username) ||
    cleanText(account?.username) ||
    cleanText(fallbackUsername) ||
    cleanText(account?.user?.email) ||
    cleanText(account?.email) ||
    cleanText(fallbackEmail) ||
    "未登录用户"
  );
}

export function transactionDetailText(item: TransactionDisplaySource): string {
  const remark = cleanText(item.remark);
  if (!isDeduction(item)) {
    return remark || formatTransactionTimestamp(item.created_at);
  }
  const timestamp = formatTransactionTimestamp(item.created_at);
  if (remark && timestamp) {
    return `${remark} · ${timestamp}`;
  }
  return timestamp || remark;
}

function isDeduction(item: TransactionDisplaySource): boolean {
  return item.points < 0 || item.type === "generation_charge";
}

function formatTransactionTimestamp(value?: string | null): string {
  const text = cleanText(value);
  if (!text) {
    return "";
  }
  const directMatch = text.match(
    /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?/,
  );
  if (directMatch) {
    const [, year, month, day, hour, minute, second = "00"] = directMatch;
    return `${year}-${pad2(month)}-${pad2(day)} ${pad2(hour)}:${pad2(minute)}:${pad2(second)}`;
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return text;
  }
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(
    date.getHours(),
  )}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;
}

function cleanText(value?: string | null): string {
  return typeof value === "string" ? value.trim() : "";
}

function pad2(value: string | number): string {
  return String(value).padStart(2, "0");
}
