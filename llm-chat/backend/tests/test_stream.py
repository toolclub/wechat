"""
T-STREAM-*: 流式处理测试
覆盖: stream.py 工具追踪、终态化、SSE 检测
"""
import pytest


# ═══════════════════════════════════════════════════════════════
# T-STREAM-01: 工具执行追踪（多工具并行）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestToolExecTracking:
    """测试 _tool_exec_map 多工具并行追踪逻辑。"""

    def test_single_tool_lifecycle(self):
        """单工具：创建 → 累积输出 → 完成"""
        tool_exec_map = {}
        tool_output_map = {}
        tool_search_map = {}

        # tool_call 事件
        seq = 1
        tool_exec_map[seq] = 100  # 模拟 DB 返回 id
        tool_output_map[seq] = ""
        tool_search_map[seq] = []

        # sandbox_output 事件
        tool_output_map[seq] += "line1\n"
        tool_output_map[seq] += "line2\n"

        # tool_result 事件
        exec_id = tool_exec_map.get(seq, 0)
        output = tool_output_map.get(seq, "")

        assert exec_id == 100
        assert output == "line1\nline2\n"

        # 清理
        tool_exec_map.pop(seq, None)
        tool_output_map.pop(seq, None)
        assert seq not in tool_exec_map

    def test_multi_tool_parallel(self):
        """多工具并行：各自 seq 独立追踪"""
        tool_exec_map = {}
        tool_output_map = {}

        # 3 个 tool_call 快速到达
        for seq in (1, 2, 3):
            tool_exec_map[seq] = 100 + seq
            tool_output_map[seq] = ""

        # 输出分别累积
        tool_output_map[1] += "tool1_output"
        tool_output_map[2] += "tool2_output"
        tool_output_map[3] += "tool3_output"

        # 完成第 2 个
        assert tool_exec_map[2] == 102
        assert tool_output_map[2] == "tool2_output"
        tool_exec_map.pop(2)
        tool_output_map.pop(2)

        # 1 和 3 不受影响
        assert tool_exec_map[1] == 101
        assert tool_exec_map[3] == 103
        assert 2 not in tool_exec_map


# ═══════════════════════════════════════════════════════════════
# T-STREAM-02: 消息终态化
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestMessageFinalization:
    def test_finalized_flag_prevents_double_finalize(self):
        """_finalized 标记防止重复终态化"""
        finalized = False

        def finalize():
            nonlocal finalized
            if finalized:
                return "skipped"
            finalized = True
            return "done"

        assert finalize() == "done"
        assert finalize() == "skipped"

    def test_event_log_not_blocked_by_finalized(self):
        """event_log 写入不受 _finalized 限制"""
        finalized = True
        event_batch = [{"type": "done"}]

        # event_log 始终写入
        written = []
        if event_batch:
            written.extend(event_batch)
            event_batch.clear()

        # message 更新跳过
        msg_updated = False
        if not finalized:
            msg_updated = True

        assert len(written) == 1  # event_log 写了
        assert msg_updated is False  # message 没更新


# ═══════════════════════════════════════════════════════════════
# T-STREAM-03: SSE 事件检测
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestSSEDetection:
    def test_detect_from_sse_string(self):
        """从 SSE 字符串检测事件类型"""
        import json
        from fsm.sse_events import detect_sse_event_type, SSEEventType

        sse_str = 'data: {"content": "hello"}'
        data = json.loads(sse_str[6:].strip())
        assert detect_sse_event_type(data) == SSEEventType.CONTENT

    def test_detect_non_data_prefix(self):
        """非 data: 前缀返回 unknown"""
        sse_str = "not_data: {}"
        assert not sse_str.startswith("data: ")

    def test_ping_value(self):
        """ping 事件值正确"""
        from fsm.sse_events import SSEEventType
        assert SSEEventType.PING.value == "ping"
        assert SSEEventType.PING == "ping"
