import { describe, expect, it } from "vitest";
import { accountDisplayName, transactionDetailText } from "./accountDisplay";

describe("accountDisplayName", () => {
  it("prefers the username over the email for the topbar account label", () => {
    expect(
      accountDisplayName(
        {
          user: {
            username: "ZH",
            email: "1176412310@qq.com",
          },
        },
        "",
        "1176412310@qq.com",
      ),
    ).toBe("ZH");
  });
});

describe("transactionDetailText", () => {
  it("adds the specific timestamp to generation charge rows", () => {
    expect(
      transactionDetailText({
        type: "generation_charge",
        points: -10,
        remark: "生成5张图片扣费",
        created_at: "2026-08-18 16:32:45.252322+08",
      }),
    ).toBe("生成5张图片扣费 · 2026-08-18 16:32:45");
  });

  it("keeps non-deduction rows unchanged when they already have a remark", () => {
    expect(
      transactionDetailText({
        type: "recharge",
        points: 10000,
        remark: "充值入账",
        created_at: "2026-08-18 16:32:45.252322+08",
      }),
    ).toBe("充值入账");
  });
});
