import unittest
from pathlib import Path

from service.zy import skills, tools


class AgentToolsTests(unittest.TestCase):
    def test_skill_catalog_is_local_and_readable(self):
        result = skills.list_skills()
        names = {item["name"] for item in result["skills"]}
        self.assertIn("browser-ai-assistant", names)
        loaded = skills.read_skill("browser-ai-assistant")
        self.assertIn("浏览器 AI 助手", loaded["content"])

    def test_save_file_is_confined_to_outputs(self):
        result = tools._save_file({"filename": "test-agent-output.txt", "content": "saved locally"})
        path = Path(result["path"])
        try:
            self.assertTrue(result["ok"])
            self.assertEqual(path.read_text(encoding="utf-8"), "saved locally")
            self.assertEqual(tools._save_file({"filename": "../escape.txt", "content": "no"})["error"], "只能保存到 outputs 文件夹，文件名不能包含绝对路径或 ..")
        finally:
            if path.exists():
                path.unlink()
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()

    def test_create_skill_is_saved_and_discovered(self):
        result = skills.create_skill(
            "test-export-skill",
            "测试导出工作流",
            "## 步骤\n1. 读取页面\n2. 保存 CSV\n",
        )
        path = Path(result["path"])
        try:
            self.assertTrue(result["ok"])
            self.assertIn("测试导出工作流", path.read_text(encoding="utf-8"))
            names = {item["name"] for item in skills.list_skills()["skills"]}
            self.assertIn("test-export-skill", names)
        finally:
            if path.exists():
                path.unlink()
            if path.parent.exists() and not any(path.parent.iterdir()):
                path.parent.rmdir()


if __name__ == "__main__":
    unittest.main()
