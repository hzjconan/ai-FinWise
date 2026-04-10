import { useEffect, useState } from 'react';
import {
  Button, Card, Form, Input, InputNumber, List, Modal, Space, Tag, message, Popconfirm,
} from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import {
  adminListQuestions, adminCreateQuestion, adminUpdateQuestion, adminDeleteQuestion,
  type Question,
} from '../../api/questions';

interface OptionForm {
  content: string;
  score: number;
}

export default function QuestionList() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Question | null>(null);
  const [form] = Form.useForm();

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
      sort_order: q.sort_order,
      options: q.options.map((o) => ({ content: o.content, score: o.score })),
    });
    setModalOpen(true);
  };

  const onSave = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await adminUpdateQuestion(editing.id, values);
        message.success('题目已更新');
      } else {
        await adminCreateQuestion(values);
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2>问卷管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新增题目</Button>
      </div>

      <List
        dataSource={questions}
        renderItem={(q) => (
          <Card style={{ marginBottom: 12 }} size="small">
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <strong>Q{q.sort_order}. {q.content}</strong>
                <div style={{ marginTop: 8 }}>
                  {q.options.map((o) => (
                    <Tag key={o.id}>{o.content}（{o.score}分）</Tag>
                  ))}
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
          <Form.Item name="sort_order" label="排序" initialValue={0}>
            <InputNumber min={0} />
          </Form.Item>
          <Form.List name="options">
            {(fields, { add, remove }) => (
              <>
                <label style={{ fontWeight: 'bold' }}>选项</label>
                {fields.map(({ key, name, ...rest }) => (
                  <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="start">
                    <Form.Item {...rest} name={[name, 'content']} rules={[{ required: true }]}>
                      <Input placeholder="选项内容" style={{ width: 300 }} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, 'score']} rules={[{ required: true }]}>
                      <InputNumber placeholder="分值" min={1} max={10} />
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
    </div>
  );
}
