import json
import tempfile
import unittest
from pathlib import Path

from reel_content_policy import validate_queue


class ContentPolicyTests(unittest.TestCase):
    def make_case(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        data = root / "shorts"
        data.mkdir()
        (data / "caption.txt").write_text(
            "물방울은 왜 둥글까\n\n설명\n\n#과학 #생활과학 #표면장력 #물방울", encoding="utf-8")
        item = {
            "id": "item-1", "caption": "caption.txt", "video_sha256": "abc",
            "content_policy": {
                "version": 1, "mode": "full", "topic_family": "general_physics",
                "keywords": ["물방울"],
                "hashtags": ["#과학", "#생활과학", "#표면장력", "#물방울"],
                "measurement_hours": [24, 72], "hook": "visible_result_first_2s",
                "controlled_change": "second_visible_result", "pair_id": "round-drops",
            },
        }
        queue = {"queue": [item]}
        (root / "reel_content_policy_baseline.json").write_text(
            json.dumps({"version": 1, "accounts": {}}), encoding="utf-8")
        return temp, root, data, queue, item

    def test_valid_full_policy(self):
        temp, root, data, queue, _ = self.make_case()
        self.addCleanup(temp.cleanup)
        validate_queue(queue, data, "ko", "phyedu_net", root)

    def test_generic_only_tags_fail(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        (data / "caption.txt").write_text(
            "물방울은 왜 둥글까\n\n설명\n\n#과학 #생활과학 #물리 #PhyEdu", encoding="utf-8")
        item["content_policy"]["hashtags"] = ["#과학", "#생활과학", "#물리", "#PhyEdu"]
        with self.assertRaisesRegex(RuntimeError, "topic-specific"):
            validate_queue(queue, data, "ko", "phyedu_net", root)

    def test_shorts_tag_fails(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        (data / "caption.txt").write_text(
            "물방울은 왜 둥글까\n\n설명\n\n#과학 #표면장력 #물방울 #shorts", encoding="utf-8")
        item["content_policy"]["hashtags"] = ["#과학", "#표면장력", "#물방울", "#shorts"]
        with self.assertRaisesRegex(RuntimeError, "#shorts"):
            validate_queue(queue, data, "ko", "phyedu_net", root)

    def test_missing_visual_gate_fails(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        del item["content_policy"]["hook"]
        with self.assertRaisesRegex(RuntimeError, "first two seconds"):
            validate_queue(queue, data, "ko", "phyedu_net", root)

    def test_baseline_requires_exact_hash(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        item["content_policy"]["mode"] = "baseline_asset"
        (root / "reel_content_policy_baseline.json").write_text(json.dumps({
            "version": 1, "accounts": {"phyedu_net": {"item-1": "different"}}
        }), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "id/hash"):
            validate_queue(queue, data, "ko", "phyedu_net", root)

    def exam_reading(self, item):
        policy = item["content_policy"]
        for key in ("hook", "controlled_change", "pair_id"):
            del policy[key]
        policy.update(mode="exam_reading", exam_year=2027, questions=[41, 42])

    def test_exam_reading_valid_for_cut_account(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        self.exam_reading(item)
        validate_queue(queue, data, "ko", "phyedu.cut", root)

    def test_exam_reading_rejected_for_other_accounts(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        self.exam_reading(item)
        for account in ("phyedu_net", "phyedu_en", "phyedu_cut"):
            with self.assertRaisesRegex(RuntimeError, "limited to @phyedu.cut"):
                validate_queue(queue, data, "ko", account, root)

    def test_exam_reading_requires_year_and_ordered_questions(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        self.exam_reading(item)
        policy = item["content_policy"]
        for year in ("2027", True, 2027.0, None):
            policy["exam_year"] = year
            with self.assertRaisesRegex(RuntimeError, "exam_year"):
                validate_queue(queue, data, "ko", "phyedu.cut", root)
        policy["exam_year"] = 2027
        for questions in ([], [42, 41], [41, 41], [0], [46], [True], ["41"], 41, None):
            policy["questions"] = questions
            with self.assertRaisesRegex(RuntimeError, "questions"):
                validate_queue(queue, data, "ko", "phyedu.cut", root)

    def test_exam_reading_keeps_shared_caption_checks(self):
        temp, root, data, queue, item = self.make_case()
        self.addCleanup(temp.cleanup)
        self.exam_reading(item)
        item["content_policy"]["hashtags"] = ["#과학", "#생활과학", "#표면장력"]
        with self.assertRaisesRegex(RuntimeError, "exactly match"):
            validate_queue(queue, data, "ko", "phyedu.cut", root)
        item["content_policy"]["hashtags"] = ["#과학", "#생활과학", "#표면장력", "#물방울"]
        item["content_policy"]["measurement_hours"] = [24]
        with self.assertRaisesRegex(RuntimeError, "measurement"):
            validate_queue(queue, data, "ko", "phyedu.cut", root)


if __name__ == "__main__":
    unittest.main()
