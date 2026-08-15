export const gtRailwayMallStandard = {
  sourceUrl: "https://mall.95306.cn/mall-view/noticeRe?id=15",
  mainImage: {
    count: "3-5 张",
    size: "800 x 800 px",
    maxSize: "单张不超过 1M",
    firstImage: "首张白底",
    fillRatio: "商品居中，填充背景空间不低于 80%",
  },
  detailImage: {
    width: "800 px",
    height: "高度不限",
    maxSize: "单张不超过 5M",
  },
  forbidden: ["水印", "促销文字", "日期", "网站名称或链接", "其他品牌 Logo", "大面积黑投影", "大面积反光", "拉伸/变形/压缩"],
  requiredSignals: ["不同视角且不得重复", "清晰完整", "与商品信息一致", "至少一张展示品牌标识或生产厂家信息", "详情图展示合格证/说明书/质检报告/生产厂家信息标签"],
};

export const outputPlan = [
  { key: "main", title: "商品主图", size: "800 x 800", railwayRole: "主图 1", gate: "白底、无文字、商品完整居中" },
  { key: "certificate", title: "商品与合格证图", size: "800 x 800", railwayRole: "主图 2", gate: "合格证信息准确、条码可识别" },
  { key: "package", title: "商品与包装箱图", size: "800 x 800", railwayRole: "主图 3", gate: "包装标签简洁、条码可识别" },
  { key: "detail", title: "商品详情图", size: "800 x 2400", railwayRole: "详情图", gate: "宽 800、文字后置排版、关键字段 OCR" },
  { key: "scene", title: "细节实拍图", size: "800 x 800", railwayRole: "主图 4/5", gate: "真实场景、结构不变形、无违规元素" },
];

