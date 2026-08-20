import { describe, expect, it } from "vitest";
import { buildProductCreatePayload, type ProductPayloadValues } from "./productPayload";

const baseValues: ProductPayloadValues = {
  name: "智枫蓝牙耳机",
  brand: "智枫",
  model: "",
};

describe("product payload", () => {
  it("omits optional product fields when the user leaves them blank", () => {
    const payload = buildProductCreatePayload(baseValues);

    expect(payload).toEqual({
      name: "智枫蓝牙耳机",
      brand: "智枫",
    });
    expect(payload).not.toHaveProperty("specs");
  });

  it("never sends specifications to the backend", () => {
    const payload = buildProductCreatePayload({
      ...baseValues,
      specificationKey: "阻抗",
      specificationValue: "32",
      specificationUnit: "Ω",
    } as ProductPayloadValues);

    expect(payload).not.toHaveProperty("specs");
  });

  it("sends the user-entered specification model only", () => {
    const payload = buildProductCreatePayload({
      ...baseValues,
      model: "ZF-CUP-800",
    });

    expect(payload).toEqual({
      name: "智枫蓝牙耳机",
      brand: "智枫",
      model: "ZF-CUP-800",
    });
  });

  it("does not send removed optional fields even if stale form data exists", () => {
    const payload = buildProductCreatePayload({
      ...baseValues,
      category: "日用百货",
      material: "聚乙烯",
      color: "白色",
      description: "用户已经不再填写这个字段",
    } as ProductPayloadValues);

    expect(payload).toEqual({
      name: "智枫蓝牙耳机",
      brand: "智枫",
    });
    expect(payload).not.toHaveProperty("category");
    expect(payload).not.toHaveProperty("material");
    expect(payload).not.toHaveProperty("color");
    expect(payload).not.toHaveProperty("description");
  });
});
