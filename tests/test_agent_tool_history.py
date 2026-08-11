import unittest

from service.zy import agent, tools


class AgentToolHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        agent._sessions.clear()
        self.original_chat_once = agent.deepseek_client.chat_once
        self.original_execute_tool = agent.tools.execute_tool
        self.original_record_turn = agent.memory.record_turn
        agent.memory.record_turn = lambda *args, **kwargs: None

    async def asyncTearDown(self):
        agent.deepseek_client.chat_once = self.original_chat_once
        agent.tools.execute_tool = self.original_execute_tool
        agent.memory.record_turn = self.original_record_turn
        agent.config._runtime.clear()
        agent._sessions.clear()

    async def test_multiple_tool_results_follow_one_assistant_tool_call_message(self):
        responses = [
            {
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "name": "get_page_info", "arguments": {}},
                    {"id": "call_2", "name": "get_page_content", "arguments": {"maxTextLen": 100}},
                ],
            },
            {"content": "处理完成", "tool_calls": []},
        ]

        async def fake_chat_once(messages, _tools):
            if len(responses) == 1:
                roles = [message["role"] for message in messages]
                self.assertEqual(roles[-3:], ["assistant", "tool", "tool"])
                self.assertEqual(
                    [message["tool_call_id"] for message in messages[-2:]],
                    ["call_1", "call_2"],
                )
            return responses.pop(0)

        async def fake_execute(name, args, send_to_extension):
            return {"ok": True, "tool": name}

        async def sink(*args, **kwargs):
            return None

        agent.deepseek_client.chat_once = fake_chat_once
        agent.tools.execute_tool = fake_execute
        await agent.handle_chat(sink, sink, "session", "看看这个页面")

        history = agent._sessions["session"]["messages"]
        self.assertEqual(
            [message["role"] for message in history],
            ["system", "user", "assistant", "tool", "tool", "assistant"],
        )
        self.assertEqual(history[-1]["content"], "处理完成")

    def test_repairs_old_tool_before_assistant_history(self):
        session = {
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "old request"},
                {"role": "tool", "tool_call_id": "bad", "content": "orphan"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "bad", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
                },
            ]
        }
        agent._repair_and_trim_history(session)
        self.assertEqual(
            [message["role"] for message in session["messages"]],
            ["system", "user"],
        )

    def test_execute_script_result_has_a_larger_budget(self):
        value = {"result": "x" * 20000}
        script_text = tools.result_to_text(value, "execute_script")
        default_text = tools.result_to_text(value, "click_element")
        self.assertGreater(len(script_text), len(default_text))
        self.assertIn("结果截断", script_text)

    def test_restore_session_keeps_visible_conversation_after_restart(self):
        agent.restore_session("restored", [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ])
        messages = agent._sessions["restored"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["system", "user", "assistant"])
        self.assertEqual(messages[-1]["content"], "之前的回答")

    def test_task_plan_tracks_step_and_overall_status(self):
        session = agent._get_or_create_session("planned")
        created = agent._set_task_plan(session, {
            "goal": "整理页面数据",
            "steps": [
                {"id": "collect", "title": "读取页面"},
                {"id": "export", "title": "保存结果"},
            ],
        })
        self.assertTrue(created["ok"])
        self.assertEqual(session["plan"]["status"], "running")
        self.assertEqual(agent._update_task_plan(session, {
            "step_id": "collect", "status": "completed", "detail": "已读取 20 条",
        })["plan"]["steps"][0]["status"], "completed")
        self.assertEqual(session["plan"]["status"], "running")
        agent._update_task_plan(session, {"step_id": "export", "status": "completed"})
        self.assertEqual(session["plan"]["status"], "completed")

    def test_task_plan_rejects_unknown_step(self):
        session = agent._get_or_create_session("invalid-plan")
        agent._set_task_plan(session, {"goal": "测试", "steps": [{"id": "one", "title": "第一步"}]})
        result = agent._update_task_plan(session, {"step_id": "missing", "status": "running"})
        self.assertIn("未找到计划步骤", result["error"])

    async def test_budget_exhaustion_requests_a_final_summary(self):
        agent.config.update_runtime({"max_tool_rounds": 1})
        calls = []

        async def fake_chat_once(messages, tool_definitions):
            calls.append(tool_definitions)
            if tool_definitions:
                return {"content": None, "tool_calls": [{"id": "call_1", "name": "get_page_info", "arguments": {}}]}
            return {"content": "根据已读取的数据，任务已完成。", "tool_calls": []}

        async def fake_execute(name, args, send_to_extension):
            return {"ok": True, "title": "示例页面"}

        replies = []

        async def sink(message_type, **payload):
            if message_type == "chat_reply":
                replies.append(payload)

        agent.deepseek_client.chat_once = fake_chat_once
        agent.tools.execute_tool = fake_execute
        await agent.handle_chat(sink, sink, "budget", "读取页面")

        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0])
        self.assertEqual(calls[1], [])
        self.assertEqual(replies[-1]["text"], "根据已读取的数据，任务已完成。")
        self.assertFalse(replies[-1]["error"])

    async def test_plan_tools_emit_progress_events_without_browser_dispatch(self):
        responses = [
            {"content": None, "tool_calls": [{
                "id": "plan", "name": "set_task_plan", "arguments": {
                    "goal": "整理页面", "steps": [{"id": "read", "title": "读取页面"}],
                },
            }]},
            {"content": None, "tool_calls": [{
                "id": "done", "name": "update_task_plan", "arguments": {
                    "step_id": "read", "status": "completed",
                },
            }]},
            {"content": "页面已整理", "tool_calls": []},
        ]
        plan_events = []

        async def fake_chat_once(_messages, _tools):
            return responses.pop(0)

        async def unexpected_browser_call(*_args, **_kwargs):
            raise AssertionError("计划工具不应发送浏览器指令")

        async def sink(message_type, **payload):
            if message_type == "task_plan":
                plan_events.append(payload["plan"])

        agent.deepseek_client.chat_once = fake_chat_once
        agent.tools.execute_tool = unexpected_browser_call
        await agent.handle_chat(sink, sink, "plan-events", "整理页面")

        self.assertGreaterEqual(len(plan_events), 2)
        self.assertEqual(plan_events[-1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
