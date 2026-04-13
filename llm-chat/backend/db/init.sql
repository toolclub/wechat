-- ============================================================
-- ChatFlow 数据库初始化脚本
-- 从零开始创建全部表结构（已存在则跳过）
-- ============================================================

-- ── 对话主表 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id               VARCHAR(36)      NOT NULL,
    title            TEXT             NOT NULL DEFAULT '新对话',
    system_prompt    TEXT             NOT NULL DEFAULT '',
    mid_term_summary TEXT             NOT NULL DEFAULT '',
    mid_term_cursor  INTEGER          NOT NULL DEFAULT 0,
    client_id        VARCHAR(36)      NOT NULL DEFAULT '',
    created_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    CONSTRAINT pk_conversations PRIMARY KEY (id)
);

COMMENT ON TABLE  conversations                  IS '对话主表：存储每个对话的元数据和摘要信息';
COMMENT ON COLUMN conversations.id               IS '对话唯一标识（8位短UUID）';
COMMENT ON COLUMN conversations.title            IS '对话标题（首条用户消息前30字自动生成）';
COMMENT ON COLUMN conversations.system_prompt    IS '自定义系统提示词';
COMMENT ON COLUMN conversations.mid_term_summary IS '中期摘要：旧消息压缩后的文本摘要';
COMMENT ON COLUMN conversations.mid_term_cursor  IS '已完成摘要的消息游标（messages表的记录偏移量）';
COMMENT ON COLUMN conversations.client_id        IS '浏览器唯一标识（由前端localStorage生成的UUID）';
COMMENT ON COLUMN conversations.created_at       IS '对话创建时间（Unix时间戳，浮点数秒）';
COMMENT ON COLUMN conversations.updated_at       IS '对话最后更新时间（Unix时间戳，浮点数秒）';

CREATE INDEX IF NOT EXISTS ix_conversations_client_id ON conversations(client_id);
CREATE INDEX IF NOT EXISTS ix_conversations_updated_at ON conversations(updated_at DESC);

-- ── 消息表 ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id         SERIAL           NOT NULL,
    conv_id    VARCHAR(36)      NOT NULL,
    role       VARCHAR(20)      NOT NULL,
    content    TEXT             NOT NULL,
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    CONSTRAINT pk_messages     PRIMARY KEY (id),
    CONSTRAINT fk_messages_conv FOREIGN KEY (conv_id)
        REFERENCES conversations(id) ON DELETE CASCADE
);

COMMENT ON TABLE  messages            IS '消息表：存储对话中的每一条消息（永不删除）';
COMMENT ON COLUMN messages.id         IS '自增主键';
COMMENT ON COLUMN messages.conv_id    IS '所属对话ID，关联 conversations.id，级联删除';
COMMENT ON COLUMN messages.role       IS '消息角色：user（用户）/ assistant（AI）/ system（系统）';
COMMENT ON COLUMN messages.content    IS '消息内容；assistant消息压缩后工具调用段替换为 [old tools call] 占位符';
COMMENT ON COLUMN messages.created_at IS '消息发送时间（Unix时间戳，浮点数秒）';

CREATE INDEX IF NOT EXISTS ix_messages_conv_id      ON messages(conv_id);
CREATE INDEX IF NOT EXISTS ix_messages_conv_created ON messages(conv_id, created_at ASC);

-- ── 工具调用事件表 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tool_events (
    id         SERIAL           NOT NULL,
    conv_id    VARCHAR(36)      NOT NULL,
    tool_name  VARCHAR(100)     NOT NULL,
    tool_input JSONB            NOT NULL DEFAULT '{}',
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    CONSTRAINT pk_tool_events      PRIMARY KEY (id),
    CONSTRAINT fk_tool_events_conv FOREIGN KEY (conv_id)
        REFERENCES conversations(id) ON DELETE CASCADE
);

COMMENT ON TABLE  tool_events            IS '工具调用事件表：记录每次对话中所有工具调用的历史，供前端刷新后复现';
COMMENT ON COLUMN tool_events.id         IS '自增主键';
COMMENT ON COLUMN tool_events.conv_id    IS '所属对话ID，关联 conversations.id，级联删除';
COMMENT ON COLUMN tool_events.tool_name  IS '工具名称（web_search / fetch_webpage / calculator / get_current_datetime 等）';
COMMENT ON COLUMN tool_events.tool_input IS '工具调用参数（JSONB格式），如 web_search 存 {"query":"..."}, fetch_webpage 存 {"url":"..."}';
COMMENT ON COLUMN tool_events.created_at IS '工具调用时间（Unix时间戳，浮点数秒）';

CREATE INDEX IF NOT EXISTS ix_tool_events_conv_id      ON tool_events(conv_id);
CREATE INDEX IF NOT EXISTS ix_tool_events_conv_created ON tool_events(conv_id, created_at ASC);

-- ── 对话状态字段（增量迁移） ─────────────────────────────────────────────────
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';
COMMENT ON COLUMN conversations.status IS '对话状态：active（空闲）/ streaming（流式输出中）/ completed（已完成）/ error（错误）';

-- ── 消息详情表（LEGACY — 已被 messages 新字段替代，ORM 已删除） ────────────────
-- LEGACY: thinking / stream_buffer / stream_completed 已迁入 messages 表，
-- 此表对新部署不再需要。物理保留是为了让既有部署 ALTER 时不报错，
-- 若确认不需要历史数据可手动 DROP TABLE message_details。
CREATE TABLE IF NOT EXISTS message_details (
    id               SERIAL           NOT NULL,
    conv_id          VARCHAR(36)      NOT NULL,
    msg_index        INTEGER          NOT NULL,
    role             VARCHAR(20)      NOT NULL,
    content          TEXT             NOT NULL DEFAULT '',
    thinking         TEXT             NOT NULL DEFAULT '',
    tool_calls       JSONB            NOT NULL DEFAULT '[]',
    steps            JSONB            NOT NULL DEFAULT '[]',
    search_results   JSONB            NOT NULL DEFAULT '[]',
    sandbox_output   TEXT             NOT NULL DEFAULT '',
    stream_completed BOOLEAN          NOT NULL DEFAULT TRUE,
    stream_buffer    TEXT             NOT NULL DEFAULT '',
    images           JSONB            NOT NULL DEFAULT '[]',
    created_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    updated_at       DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    CONSTRAINT pk_message_details PRIMARY KEY (id),
    CONSTRAINT fk_msgdetail_conv  FOREIGN KEY (conv_id)
        REFERENCES conversations(id) ON DELETE CASCADE
);

COMMENT ON TABLE  message_details               IS '消息详情表：存储每条消息的完整结构化数据（thinking、工具调用、步骤等）';
COMMENT ON COLUMN message_details.msg_index     IS '消息在对话中的序号（0-based）';
COMMENT ON COLUMN message_details.thinking      IS '模型推理/思考过程';
COMMENT ON COLUMN message_details.tool_calls    IS '工具调用详情 JSON 数组';
COMMENT ON COLUMN message_details.steps         IS '多步执行记录 JSON 数组';
COMMENT ON COLUMN message_details.stream_completed IS '流式输出是否完成';
COMMENT ON COLUMN message_details.stream_buffer IS '流式输出中间缓冲';

CREATE INDEX IF NOT EXISTS ix_msgdetail_conv     ON message_details(conv_id);
CREATE INDEX IF NOT EXISTS ix_msgdetail_conv_idx ON message_details(conv_id, msg_index);
