"""
T-FSM-*: 状态机测试
覆盖: fsm/conversation.py, fsm/tool_execution.py, fsm/sse_events.py, db/state_machine.py
"""
import json
import pytest

# ═══════════════════════════════════════════════════════════════
# T-FSM-01: 对话状态机合法转换
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestConversationSMTransitions:
    def _make(self, status="active"):
        from fsm.conversation import ConversationSM
        return ConversationSM.from_db_status(status, conv_id="test")

    def test_active_to_streaming(self):
        sm = self._make("active")
        sm.send_event("streaming")
        assert sm.current_value == "streaming"

    def test_streaming_to_completed(self):
        sm = self._make("streaming")
        sm.send_event("completed")
        assert sm.current_value == "completed"

    def test_streaming_to_error(self):
        sm = self._make("streaming")
        sm.send_event("error")
        assert sm.current_value == "error"

    def test_streaming_to_active_stop(self):
        sm = self._make("streaming")
        sm.send_event("active")
        assert sm.current_value == "active"

    def test_completed_to_streaming_new_round(self):
        sm = self._make("completed")
        sm.send_event("streaming")
        assert sm.current_value == "streaming"

    def test_error_to_streaming_retry(self):
        sm = self._make("error")
        sm.send_event("streaming")
        assert sm.current_value == "streaming"

    def test_full_lifecycle(self):
        sm = self._make("active")
        sm.send_event("streaming")
        assert sm.current_value == "streaming"
        sm.send_event("completed")
        assert sm.current_value == "completed"
        sm.send_event("streaming")
        assert sm.current_value == "streaming"
        sm.send_event("error")
        assert sm.current_value == "error"
        sm.send_event("streaming")
        assert sm.current_value == "streaming"
        sm.send_event("active")
        assert sm.current_value == "active"


# ═══════════════════════════════════════════════════════════════
# T-FSM-02: 对话状态机非法转换
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestConversationSMInvalid:
    def _make(self, status="active"):
        from fsm.conversation import ConversationSM
        return ConversationSM.from_db_status(status, conv_id="test")

    def test_active_to_completed_rejected(self):
        sm = self._make("active")
        result = sm.send_event("completed")
        assert result == "active"  # 不变

    def test_active_to_error_rejected(self):
        sm = self._make("active")
        result = sm.send_event("error")
        assert result == "active"

    def test_completed_to_error_rejected(self):
        sm = self._make("completed")
        result = sm.send_event("error")
        assert result == "completed"

    def test_invalid_target(self):
        sm = self._make("active")
        result = sm.send_event("nonexistent")
        assert result == "active"


# ═══════════════════════════════════════════════════════════════
# T-FSM-03: from_db_status 恢复
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestConversationSMRestore:
    def test_valid_status(self):
        from fsm.conversation import ConversationSM
        for s in ("active", "streaming", "completed", "error"):
            sm = ConversationSM.from_db_status(s)
            assert sm.current_value == s

    def test_invalid_status_fallback(self):
        from fsm.conversation import ConversationSM
        sm = ConversationSM.from_db_status("unknown")
        assert sm.current_value == "active"

    def test_empty_status_fallback(self):
        from fsm.conversation import ConversationSM
        sm = ConversationSM.from_db_status("")
        assert sm.current_value == "active"


# ═══════════════════════════════════════════════════════════════
# T-FSM-04: 工具执行状态机
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestToolExecutionSM:
    def test_running_to_done(self):
        from fsm.tool_execution import ToolExecutionSM
        sm = ToolExecutionSM()
        sm.send_event("done")
        assert sm.current_value == "done"

    def test_running_to_error(self):
        from fsm.tool_execution import ToolExecutionSM
        sm = ToolExecutionSM()
        sm.send_event("error")
        assert sm.current_value == "error"

    def test_running_to_timeout(self):
        from fsm.tool_execution import ToolExecutionSM
        sm = ToolExecutionSM()
        sm.send_event("timeout")
        assert sm.current_value == "timeout"

    def test_done_is_final(self):
        from fsm.tool_execution import ToolExecutionSM
        sm = ToolExecutionSM()
        sm.send_event("done")
        with pytest.raises(Exception):
            sm.send_event("error")

    def test_invalid_event(self):
        from fsm.tool_execution import ToolExecutionSM
        sm = ToolExecutionSM()
        result = sm.send_event("invalid")
        assert result == "running"


# ═══════════════════════════════════════════════════════════════
# T-FSM-05: SSE 事件类型检测
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestSSEEventDetection:
    def test_single_key(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({"content": "hi"}) == SSEEventType.CONTENT

    def test_multi_key_priority(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({"tool_result": {}, "content": "x"}) == SSEEventType.TOOL_RESULT

    def test_control_highest_priority(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({"done": True, "content": "x"}) == SSEEventType.DONE

    def test_empty_dict(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({}) == SSEEventType.UNKNOWN

    def test_thinking_before_content(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({"thinking": "x", "content": "y"}) == SSEEventType.THINKING

    def test_tool_call_args(self):
        from fsm.sse_events import SSEEventType, detect_sse_event_type
        assert detect_sse_event_type({"tool_call_args": {"text": "x"}}) == SSEEventType.TOOL_CALL_ARGS


# ═══════════════════════════════════════════════════════════════
# T-FSM-06: 枚举 .value 兼容性
# ═══════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestEnumCompat:
    def test_tool_status_value(self):
        from db.state_machine import ToolExecutionStatus
        assert ToolExecutionStatus.RUNNING.value == "running"
        assert ToolExecutionStatus.DONE.value == "done"

    def test_tool_status_str_compare(self):
        from db.state_machine import ToolExecutionStatus
        assert ToolExecutionStatus.RUNNING == "running"

    def test_conv_status_value(self):
        from db.state_machine import ConversationStatus
        assert ConversationStatus.ACTIVE.value == "active"

    def test_conv_status_construct(self):
        from db.state_machine import ConversationStatus
        assert ConversationStatus("active") == ConversationStatus.ACTIVE

    def test_json_serialization(self):
        from db.state_machine import ConversationStatus
        result = json.dumps({"s": ConversationStatus.ACTIVE})
        assert result == '{"s": "active"}'

    def test_validate_conv_transition(self):
        from db.state_machine import validate_conv_transition
        assert validate_conv_transition("active", "streaming") is True
        assert validate_conv_transition("active", "completed") is False

    def test_validate_tool_transition(self):
        from db.state_machine import validate_tool_transition
        assert validate_tool_transition("running", "done") is True
        assert validate_tool_transition("done", "error") is False
