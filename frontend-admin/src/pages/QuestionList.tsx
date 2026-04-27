import { useEffect, useRef, useState } from 'react';
import {
  Button, Card, Drawer, Form, Input, InputNumber, List, Modal, Radio, Space, Tag, Tooltip,
  message, Popconfirm,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, QuestionCircleOutlined, EyeOutlined,
  HolderOutlined,
} from '@ant-design/icons';
import {
  adminListQuestions, adminCreateQuestion, adminUpdateQuestion, adminDeleteQuestion,
  adminSortQuestions, type Question,
} from '../api/questions';

interface OptionForm {
  content: string;
  score: number;
}

export default function QuestionList() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [editing, setEditing] = useState<Question | null>(null);
  const [form] = Form.useForm();
  const dragIndexRef = useRef<number | null>(null);

  const load = () => {
    adminListQuestions().then(({ data }) => setQuestions(data));
  };

  useEffect(load, []);

  const openNew = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ options: [{ content: '', score: 1 }] });
    setModalOpen(true);
  };

  const openEdit = (q: Question) => {
    setEditing(q);
    form.setFieldsValue({
      content: q.content,
      options: q.options.map((o) => ({ content: o.content, score: o.score })),
    });
    setModalOpen(true);
  };

  const onSave = async () => {
    const values = await form.validateFields();
    // sort_order 由列表顺序决定，新建时追加到末尾
    const sort_order = editing
      ? editing.sort_order
      : Math.max(0, ...questions.map((q) => q.sort_order)) + 1;
    try {
      if (editing) {
        await adminUpdateQuestion(editing.id, { ...values, sort_order });
        message.success('题目已更新');
      } else {
        await adminCreateQuestion({ ...values, sort_order });
        message.success('题目已创建');
      }
      setModalOpen(false);
      load();
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '操作失败');
    }
  };

  const onDelete = async (id: number) => {
    await adminDeleteQuestion(id);
    message.success('题目已删除');
    load();
  };

  const onDrop = async (dropIndex: number) => {
    const fromIndex = dragIndexRef.current;
    dragIndexRef.current = null;
    if (fromIndex === null || fromIndex === dropIndex) return;

    const reordered = [...questions];
    const [moved] = reordered.splice(fromIndex, 1);
    reordered.splice(dropIndex, 0, moved);

    // 乐观更新 UI 顺序 + 重写 sort_order
    const withOrders = reordered.map((q, i) => ({ ...q, sort_order: i + 1 }));
    setQuestions(withOrders);

    try {
      await adminSortQuestions(
        withOrders.map((q) => ({ id: q.id, sort_order: q.sort_order })),
      );
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '排序失败');
      load();
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2>问卷管理</h2>
        <Space>
          <Button
            icon={<EyeOutlined />}
            onClick={() => setPreviewOpen(true)}
            disabled={questions.length === 0}
            data-cy="preview-btn"
          >
            预览
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>
            新增题目
          </Button>
        </Space>
      </div>

      <p style={{ color: '#999', fontSize: 12, marginBottom: 8 }}>
        提示：拖拽题目卡片左侧的 <HolderOutlined /> 图标可调整顺序
      </p>

      <List
        dataSource={questions}
        renderItem={(q, index) => (
          <Card
            key={q.id}
            data-cy={`question-card-${q.id}`}
            style={{ marginBottom: 12 }}
            size="small"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => onDrop(index)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1 }}>
                <span
                  draggable
                  onDragStart={() => { dragIndexRef.current = index; }}
                  data-cy={`drag-handle-${q.id}`}
                  style={{ cursor: 'grab', color: '#999', fontSize: 18, padding: 4 }}
                  title="拖拽排序"
                >
                  <HolderOutlined />
                </span>
                <div>
                  <strong>Q{q.sort_order}. {q.content}</strong>
                  <div style={{ marginTop: 8 }}>
                    {q.options.map((o) => (
                      <Tag key={o.id}>{o.content}（{o.score}分）</Tag>
                    ))}
                  </div>
                </div>
              </div>
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(q)} />
                <Popconfirm title="确认删除？" onConfirm={() => onDelete(q.id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            </div>
          </Card>
        )}
      />

      <Modal
        title={editing ? '编辑题目' : '新增题目'}
        open={modalOpen}
        onOk={onSave}
        onCancel={() => setModalOpen(false)}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="content" label="题目内容" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.List name="options">
            {(fields, { add, remove }) => (
              <>
                <Space style={{ fontWeight: 'bold', marginBottom: 8 }}>
                  选项
                  <Tooltip title="每个选项的分值会影响风险评估结果：所有题目得分汇总后计算百分比，分值越高，评估结果越偏向激进型（C5）；分值越低，越偏向保守型（C1）。">
                    <QuestionCircleOutlined style={{ color: '#999', cursor: 'help' }} />
                  </Tooltip>
                </Space>
                {fields.map(({ key, name, ...rest }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="start">
                    <Form.Item {...rest} name={[name, 'content']} rules={[{ required: true }]}>
                      <Input placeholder="选项内容" style={{ width: 300 }} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'score']} rules={[{ required: true }]}>
                      <InputNumber min={1} max={10} addonBefore="分值" placeholder="分值" />
                    </Form.Item>
                    {fields.length > 1 && (
                      <Button danger onClick={() => remove(name)} icon={<DeleteOutlined />} />
                    )}
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ content: '', score: 1 })} block>
                  + 添加选项
                </Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>

      <Drawer
        title="问卷预览（客户视角）"
        placement="right"
        width={520}
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        data-cy="preview-drawer"
      >
        <p style={{ color: '#999', marginBottom: 16 }}>
          仅用于预览，选项不会保存。
        </p>
        {questions.map((q, i) => (
          <Card
            key={q.id}
            size="small"
            title={`第 ${i + 1} 题 / 共 ${questions.length} 题`}
            style={{ marginBottom: 16 }}
          >
            <h4 style={{ marginBottom: 12 }}>{q.content}</h4>
            <Radio.Group style={{ width: '100%' }}>
              <Space direction="vertical" style={{ width: '100%' }}>
                {q.options.map((o) => (
                  <Radio
                    key={o.id}
                    value={o.id}
                    style={{ display: 'block', padding: '4px 0' }}
                  >
                    {o.content}
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
          </Card>
        ))}
      </Drawer>
    </div>
  );
}
