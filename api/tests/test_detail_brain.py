import unittest
import json
from unittest.mock import Mock, patch
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from PIL import Image

from app.providers.real_image import KeleFiveImagePipeline
from app.providers.detail_brain import (
    DETAIL_PLAN_SCHEMA,
    DetailBrainConfig,
    OpenAIDetailBrain,
    compose_detail_prompts_from_plan,
    validate_detail_plan,
)


VALID_PLAN = {
    "modules": [
        {
            "index": 1,
            "type": "ecommerce_promo",
            "size": "800x800",
            "layout": "not_applicable",
            "left_scene": {
                "caption": "not_applicable",
                "environment": "not_applicable",
                "usage": "not_applicable",
                "render_style": "not_applicable",
                "camera": "not_applicable",
                "lighting": "not_applicable",
                "color_palette": "not_applicable",
                "product_presence": "not_applicable",
            },
            "right_scene": {
                "caption": "not_applicable",
                "environment": "not_applicable",
                "usage": "not_applicable",
                "render_style": "not_applicable",
                "camera": "not_applicable",
                "lighting": "not_applicable",
                "color_palette": "not_applicable",
                "product_presence": "not_applicable",
            },
            "image_prompt": "首屏电商宣传图，绘制商品名和核心卖点。",
        },
        {
            "index": 2,
            "type": "usage_scene_pair",
            "size": "800x800",
            "layout": "left_right_two_columns",
            "left_scene": {
                "caption": "车间加工",
                "environment": "真实车间作业环境",
                "usage": "工人正在使用该商品完成加工任务",
                "render_style": "纪实广角摄影",
                "camera": "低机位28mm",
                "lighting": "冷白工业顶光",
                "color_palette": "金属灰和安全黄色",
                "product_presence": "visible",
            },
            "right_scene": {
                "caption": "户外施工",
                "environment": "真实户外施工现场",
                "usage": "施工人员正在使用该商品处理现场任务",
                "render_style": "户外新闻摄影",
                "camera": "平视35mm",
                "lighting": "强烈自然日光",
                "color_palette": "混凝土灰和尘土黄",
                "product_presence": "absent",
            },
            "image_prompt": "两个真实使用场景。",
        },
        {
            "index": 3,
            "type": "usage_scene_pair",
            "size": "800x800",
            "layout": "left_right_two_columns",
            "left_scene": {
                "caption": "仓库搬运",
                "environment": "真实仓库作业通道",
                "usage": "工作人员正在使用该商品完成仓储作业",
                "render_style": "高角度空间摄影",
                "camera": "俯视24mm",
                "lighting": "柔和仓库漫反射光",
                "color_palette": "货架蓝和地面灰",
                "product_presence": "partial",
            },
            "right_scene": {
                "caption": "门店安装",
                "environment": "真实门店安装现场",
                "usage": "安装人员正在使用该商品完成安装任务",
                "render_style": "近景过程摄影",
                "camera": "侧面50mm",
                "lighting": "暖色室内侧光",
                "color_palette": "木色和暖白",
                "product_presence": "visible",
            },
            "image_prompt": "另外两个真实使用场景。",
        },
        {
            "index": 4,
            "type": "detail_features",
            "size": "800x800",
            "layout": "not_applicable",
            "left_scene": {
                "caption": "not_applicable",
                "environment": "not_applicable",
                "usage": "not_applicable",
                "render_style": "not_applicable",
                "camera": "not_applicable",
                "lighting": "not_applicable",
                "color_palette": "not_applicable",
                "product_presence": "not_applicable",
            },
            "right_scene": {
                "caption": "not_applicable",
                "environment": "not_applicable",
                "usage": "not_applicable",
                "render_style": "not_applicable",
                "camera": "not_applicable",
                "lighting": "not_applicable",
                "color_palette": "not_applicable",
                "product_presence": "not_applicable",
            },
            "image_prompt": "商品细节特写，绘制中文细节标签。",
        },
    ]
}

for _module in VALID_PLAN["modules"]:
    for _offset, _side in enumerate(("left_scene", "right_scene")):
        _is_usage = _module["index"] in {2, 3}
        _module[_side].update(
            scene_index=(_module["index"] - 2) * 2 + _offset + 1 if _is_usage else 0,
            source="auto" if _is_usage else "not_applicable",
            user_input="",
        )


class DetailBrainPlanTests(unittest.TestCase):
    def test_module_indexes_must_be_integers_so_custom_scene_keys_cannot_be_lost(self):
        inputs = {"scene_3": "会议室，用于远程会议"}
        for module_position, invalid_index in ((2, 3.0), (0, True), (2, "3")):
            with self.subTest(index=invalid_index):
                plan = _plan_for_inputs(inputs)
                plan["modules"][module_position]["index"] = invalid_index
                with self.assertRaisesRegex(ValueError, "DETAIL_PLAN_INVALID"):
                    compose_detail_prompts_from_plan(plan, product={}, scene_inputs=inputs)

    def test_custom_scene_keeps_third_slot_in_request_and_final_prompt(self):
        scene_inputs = {"scene_3": "会议室，用于远程会议"}
        plan = _plan_for_inputs(scene_inputs)
        responses = Mock()
        responses.create.return_value = SimpleNamespace(output_text=json.dumps(plan, ensure_ascii=False))
        brain = OpenAIDetailBrain(
            DetailBrainConfig(base_url="https://example.invalid/v1", api_key="test-key"),
            client_factory=lambda **_kwargs: SimpleNamespace(responses=responses),
        )

        prompts = brain.build_detail_prompts(product={"name": "摄像头"}, project={"detail_config": {"scene_inputs": scene_inputs}})

        request_data = json.loads(responses.create.call_args.kwargs["input"][1]["content"][0]["text"])
        self.assertEqual(request_data["detail_config"]["scene_inputs"], scene_inputs)
        self.assertEqual(responses.create.call_count, 1)
        self.assertIn('"scene_index": 3', prompts[2])
        self.assertIn('"side": "left"', prompts[2])
        self.assertIn(scene_inputs["scene_3"], prompts[2])
        self.assertNotIn(scene_inputs["scene_3"], prompts[1])

    def test_all_custom_scene_inputs_reach_their_assigned_module(self):
        inputs = {f"scene_{index}": f"指定场所{index}，用于用途{index}" for index in range(1, 5)}
        prompts = compose_detail_prompts_from_plan(_plan_for_inputs(inputs), product={}, scene_inputs=inputs)
        for index in range(1, 5):
            self.assertIn(inputs[f"scene_{index}"], prompts[1 if index <= 2 else 2])
            self.assertNotIn(inputs[f"scene_{index}"], prompts[2 if index <= 2 else 1])
        self.assertNotIn("指定场所", prompts[0])
        self.assertNotIn("指定场所", prompts[3])

    def test_plan_rejects_missing_swapped_or_fabricated_scene_provenance(self):
        inputs = {"scene_3": "会议室，用于远程会议"}
        for field, value in (("scene_index", 1), ("source", "auto"), ("user_input", "模型私自替换了场景")):
            with self.subTest(field=field):
                plan = _plan_for_inputs(inputs)
                plan["modules"][2]["left_scene"][field] = value
                with self.assertRaisesRegex(ValueError, "DETAIL_SCENE_SOURCE_INVALID"):
                    validate_detail_plan(plan, scene_inputs=inputs)
        plan = _plan_for_inputs(inputs)
        del plan["modules"][2]["left_scene"]["scene_index"]
        with self.assertRaisesRegex(ValueError, "DETAIL_SCENE_SOURCE_INVALID"):
            validate_detail_plan(plan, scene_inputs=inputs)

    def test_auto_scene_cannot_claim_a_user_source(self):
        plan = _copy_plan()
        plan["modules"][1]["left_scene"].update(source="user", user_input="不存在的用户要求")
        with self.assertRaisesRegex(ValueError, "DETAIL_SCENE_SOURCE_INVALID"):
            validate_detail_plan(plan)

    def test_repeated_user_choices_are_allowed_but_auto_duplicates_are_rejected(self):
        inputs = {"scene_1": "办公室，用于视频会议", "scene_3": "办公室，用于视频会议"}
        plan = _plan_for_inputs(inputs)
        plan["modules"][2]["left_scene"] = {**plan["modules"][1]["left_scene"], "scene_index": 3}
        validate_detail_plan(plan, scene_inputs=inputs)
        # The automatically filled fourth slot must not duplicate a supplied scene.
        plan["modules"][2]["right_scene"]["caption"] = plan["modules"][1]["left_scene"]["caption"]
        with self.assertRaisesRegex(ValueError, "DETAIL_USAGE_SCENE_DUPLICATE"):
            validate_detail_plan(plan, scene_inputs=inputs)

    def test_missing_brain_rejects_custom_scenes_before_any_image_call(self):
        provider = Mock()
        pipeline = KeleFiveImagePipeline(provider)
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "DETAIL_BRAIN_REQUIRED"):
                pipeline.generate_five_images(
                    output_dir=Path(tmp), job_id="custom-scenes", product={},
                    project={"detail_config": {"scene_inputs": {"scene_3": "会议室，用于远程会议"}}},
                    source_image_path=Path(tmp) / "source.png",
                )
        provider.edit_image.assert_not_called()

    def test_failed_brain_is_not_retried_or_replaced_with_default_scenes(self):
        responses = Mock()
        responses.create.side_effect = TimeoutError("upstream timed out")
        brain = OpenAIDetailBrain(
            DetailBrainConfig(base_url="https://example.invalid/v1", api_key="test-key"),
            client_factory=lambda **_kwargs: SimpleNamespace(responses=responses),
        )
        with self.assertRaisesRegex(RuntimeError, "DETAIL_BRAIN_FAILED"):
            brain.build_detail_prompts(product={}, project={"detail_config": {"scene_inputs": {"scene_1": "办公室，用于会议"}}})
        self.assertEqual(responses.create.call_count, 1)

    def test_detail_brain_default_timeout_is_150_seconds(self):
        from app.api.phase_one import load_detail_brain_config

        with patch.dict(
            "os.environ",
            {
                "DETAIL_BRAIN_API_KEY": "test-key",
                "DETAIL_BRAIN_EXTRA_HEADERS_JSON": "{}",
            },
            clear=True,
        ):
            config = load_detail_brain_config()

        self.assertEqual(config.timeout_seconds, 150)

    def test_detail_plan_schema_is_strict_for_openai_structured_outputs(self):
        assert_strict_openai_schema(DETAIL_PLAN_SCHEMA)

    def test_usage_scene_modules_must_use_left_right_columns(self):
        plan = _copy_plan()
        plan["modules"][1]["layout"] = "top_bottom"

        with self.assertRaisesRegex(ValueError, "DETAIL_USAGE_LAYOUT_INVALID"):
            validate_detail_plan(plan)

    def test_usage_scenes_must_be_unique_but_not_blocklisted_by_scene_words(self):
        plan = _copy_plan()

        validated = validate_detail_plan(plan)

        self.assertEqual(validated["modules"][1]["left_scene"]["caption"], "车间加工")
        self.assertEqual(validated["modules"][2]["left_scene"]["caption"], "仓库搬运")

    def test_rejects_duplicate_usage_scene_captions(self):
        plan = _copy_plan()
        plan["modules"][2]["right_scene"]["caption"] = "车间加工"

        with self.assertRaisesRegex(ValueError, "DETAIL_USAGE_SCENE_DUPLICATE"):
            validate_detail_plan(plan)

    def test_rejects_duplicate_usage_render_direction(self):
        plan = _copy_plan()
        plan["modules"][2]["right_scene"]["render_style"] = "纪实广角摄影"

        with self.assertRaisesRegex(ValueError, "DETAIL_USAGE_RENDER_DUPLICATE"):
            validate_detail_plan(plan)

    def test_system_prompt_does_not_include_fixed_scene_examples(self):
        from app.providers.detail_brain import DETAIL_BRAIN_SYSTEM_PROMPT

        self.assertNotIn("户外施工", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertNotIn("施工人员", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertNotIn("车间加工", DETAIL_BRAIN_SYSTEM_PROMPT)

    def test_system_prompt_uses_policy_safe_commercial_persona_without_reducing_quality(self):
        from app.providers.detail_brain import DETAIL_BRAIN_SYSTEM_PROMPT

        self.assertIn("policy-safe Chinese ecommerce art director", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("preserve premium ecommerce quality", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("No graphic violence, blood, gore, injury, weapons, fighting, accidents, disaster, or dangerous-operation content", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("Avoid human faces", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("correct intended use of the product", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("do not improvise or vary caption typography", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("All four usage scenes must include visible Chinese caption text", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("Caption styling may be plain with no label box, but the styling choice must be globally consistent across all four usage scenes", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("font size, caption background color, and caption font color must be identical across all four usage scenes", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("never mix boxed, unboxed, styled, and plain captions", DETAIL_BRAIN_SYSTEM_PROMPT)
        self.assertIn("neutral product environments", DETAIL_BRAIN_SYSTEM_PROMPT)

    def test_composed_usage_prompts_force_left_right_layout_and_consistent_required_text(self):
        prompts = compose_detail_prompts_from_plan(
            _copy_plan(),
            product={"name": "智枫工具", "brand": "智枫", "model": "ZF-88"},
        )

        self.assertEqual(len(prompts), 4)
        self.assertIn("800x800", prompts[1])
        self.assertIn("left-right two-column layout", prompts[1])
        self.assertIn("Do not use top-bottom layout", prompts[1])
        self.assertIn("render the Chinese text directly inside the generated image", prompts[1])
        self.assertIn("product may be visible, partially visible, or absent", prompts[1])
        self.assertIn("Caption style lock", prompts[1])
        self.assertIn("Caption text lock", prompts[1])
        self.assertIn("both columns must render visible Chinese caption text", prompts[1])
        self.assertIn("Caption style may be plain with no label box", prompts[1])
        self.assertIn("font size, caption background color, and caption font color must match across both columns and both usage-scene modules", prompts[1])
        self.assertIn("Do not mix boxed, unboxed, styled, and plain captions", prompts[1])
        self.assertIn("Only caption wording may differ", prompts[1])
        self.assertNotIn("omit captions", prompts[1])
        self.assertNotIn("Each scene must include its own Chinese text description inside its own column", prompts[1])
        self.assertIn("Scene left render style: 纪实广角摄影", prompts[1])
        self.assertIn("Scene right product presence: absent", prompts[1])
        self.assertIn("Scene left caption: 车间加工", prompts[1])
        self.assertIn("Scene right caption: 户外施工", prompts[1])

    def test_composed_prompts_neutralize_bloody_or_violent_planner_text(self):
        plan = _copy_plan()
        plan["modules"][1]["left_scene"]["usage"] = "血腥暴力事故现场，武器打斗后流血"
        plan["modules"][1]["image_prompt"] = "展示血腥、流血、武器和打斗画面"

        prompts = compose_detail_prompts_from_plan(
            plan,
            product={"name": "智枫工具", "brand": "智枫", "model": "ZF-88"},
        )

        joined = " ".join(prompts)
        for forbidden in ("血腥", "暴力", "事故现场", "武器", "打斗", "流血"):
            self.assertNotIn(forbidden, joined)
        self.assertTrue(all("Commercial safety constraint" in prompt for prompt in prompts))
        self.assertIn("polished lighting", prompts[0])
        self.assertIn("left-right two-column layout", prompts[1])
        self.assertIn("real visible product details", prompts[3])

    def test_openai_detail_brain_uses_responses_api_and_parses_structured_output(self):
        class FakeResponses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(output_text=_json_plan())

        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        brain = OpenAIDetailBrain(
            DetailBrainConfig(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                model="gpt-5.5",
                reasoning_effort="medium",
            ),
            client_factory=lambda **_kwargs: client,
        )

        prompts = brain.build_detail_prompts(
            product={"name": "智枫工具", "brand": "智枫"},
            project={"detail_config": {"selling_points": ["耐用"]}},
        )

        self.assertEqual(len(prompts), 4)
        self.assertEqual(responses.calls[0]["model"], "gpt-5.5")
        self.assertEqual(responses.calls[0]["reasoning"], {"effort": "medium"})
        self.assertIn("left-right two-column layout", prompts[2])

    def test_openai_detail_brain_disables_sdk_retries(self):
        class FakeResponses:
            def create(self, **_kwargs):
                return SimpleNamespace(output_text=_json_plan())

        client_kwargs = {}

        def client_factory(**kwargs):
            client_kwargs.update(kwargs)
            return SimpleNamespace(responses=FakeResponses())

        brain = OpenAIDetailBrain(
            DetailBrainConfig(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                timeout_seconds=150,
            ),
            client_factory=client_factory,
        )

        brain.build_detail_prompts(
            product={"name": "智枫工具"},
            project={"detail_config": {}},
        )

        self.assertEqual(client_kwargs["timeout"], 150)
        self.assertEqual(client_kwargs.get("max_retries"), 0)

    def test_five_image_pipeline_uses_detail_brain_prompts_and_builds_800_by_3200_detail(self):
        class FakeImageProvider:
            def __init__(self):
                self.prompts = []

            def edit_image(self, *, prompt, size, image_paths):
                self.prompts.append(prompt)
                image = Image.new("RGB", (800, 800), "#ffffff")
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()

        class FakeBrain:
            name = "fake-detail-brain"

            def __init__(self):
                self.calls = []

            def build_detail_prompts(self, *, product, project, source_image_path=None):
                self.calls.append((product, project, source_image_path))
                return [f"dynamic detail brain prompt {index}" for index in range(1, 5)]

        provider = FakeImageProvider()
        brain = FakeBrain()
        pipeline = KeleFiveImagePipeline(provider, detail_brain=brain)
        product = {"name": "智枫工具", "brand": "智枫"}
        project = {"barcode_type": "EAN_13", "barcode_value": "6903244675147"}

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (800, 800), "white").save(source)
            outputs = pipeline.generate_five_images(
                output_dir=Path(tmp),
                job_id="job",
                product=product,
                project=project,
                source_image_path=source,
            )

            detail = next(output for output in outputs if output.output_type == "detail")
            with Image.open(detail.path) as image:
                self.assertEqual(image.size, (800, 3200))

        self.assertEqual(len(brain.calls), 1)
        self.assertTrue(all(f"dynamic detail brain prompt {index}" in provider.prompts for index in range(1, 5)))
        self.assertFalse(any("Fixed four-scene usage plan" in prompt for prompt in provider.prompts))


def _copy_plan():
    import copy

    return copy.deepcopy(VALID_PLAN)


def _plan_for_inputs(inputs):
    plan = _copy_plan()
    for module in plan["modules"][1:3]:
        for side in ("left_scene", "right_scene"):
            scene = module[side]
            user_input = inputs.get(f"scene_{scene['scene_index']}", "")
            scene.update(source="user" if user_input else "auto", user_input=user_input)
    return plan


def _json_plan():
    import json

    return json.dumps(VALID_PLAN, ensure_ascii=False)


def assert_strict_openai_schema(schema):
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        assert schema.get("additionalProperties") is False
        assert sorted(schema.get("required", [])) == sorted(properties.keys())
    if schema.get("type") == "array":
        assert_strict_openai_schema(schema.get("items"))
    for child in schema.get("properties", {}).values():
        assert_strict_openai_schema(child)


if __name__ == "__main__":
    unittest.main()
