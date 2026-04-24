// AI 对话评估页 E2E。后端 LLM 在 P2 前是 NotImplementedError，因此全部
// 通过 cy.intercept 桩接 /assessment/chat/* 端点。

describe('Customer AI Chat Assessment', () => {
  beforeEach(() => {
    cy.createAnonymousCustomer();
  });

  it('mode select page navigates to chat page', () => {
    cy.visit('/assessment');
    cy.get('[data-cy="mode-chat"]').click();
    cy.url().should('include', '/assessment/chat');
  });

  it('mode select page navigates to questionnaire page', () => {
    cy.seedQuestions();
    cy.visit('/assessment');
    cy.get('[data-cy="mode-questionnaire"]').click();
    cy.url().should('include', '/assessment/questionnaire');
  });

  it('renders opening message from /start', () => {
    cy.intercept('POST', '/api/v1/assessment/chat/start', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-001',
        resumed: false,
        messages: [
          {
            role: 'assistant',
            content: '您好！请问您有投资经验吗？',
            created_at: new Date().toISOString(),
          },
        ],
      },
    }).as('start');

    cy.visit('/assessment/chat');
    cy.wait('@start');
    cy.get('[data-cy="msg-assistant"]').should('contain.text', '请问您有投资经验吗');
    cy.get('[data-cy="chat-progress"]').should('contain.text', '已对话 0 轮');
  });

  it('sends message, streams delta, and increments round', () => {
    cy.intercept('POST', '/api/v1/assessment/chat/start', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-002',
        resumed: false,
        messages: [
          { role: 'assistant', content: '开场白', created_at: new Date().toISOString() },
        ],
      },
    });

    // SSE 响应：两个 delta + 一个 completed asking
    const sseBody =
      'event: delta\ndata: {"content":"了解"}\n\n' +
      'event: delta\ndata: {"content":"，请问您可接受的最大回撤？"}\n\n' +
      'event: completed\ndata: {"phase":"asking","round":1}\n\n';

    cy.intercept('POST', '/api/v1/assessment/chat/CHAT-TEST-002/message', {
      statusCode: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: sseBody,
    }).as('send');

    cy.visit('/assessment/chat');
    cy.get('[data-cy="chat-input"]').type('我有少量基金经验');
    cy.get('[data-cy="chat-send"]').click();
    cy.wait('@send');

    cy.get('[data-cy="msg-user"]').should('contain.text', '我有少量基金经验');
    cy.get('[data-cy="msg-assistant"]').last().should('contain.text', '请问您可接受的最大回撤');
    cy.get('[data-cy="chat-progress"]').should('contain.text', '已对话 1 轮');
  });

  it('navigates to result page when LLM concludes', () => {
    cy.intercept('POST', '/api/v1/assessment/chat/start', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-003',
        resumed: false,
        messages: [
          { role: 'assistant', content: '开场白', created_at: new Date().toISOString() },
        ],
      },
    });

    const sseBody =
      'event: completed\ndata: {"phase":"concluded","round":5,"assessment":{"assessment_code":"ASM-TEST-001","source":"ai_chat","risk_preference":"C3","risk_label":"平衡型","ai_summary":"综合判断为平衡型","ai_dimensions":{"experience":3,"loss_tolerance":3,"income_stability":3,"investment_horizon":3,"volatility_tolerance":3}}}\n\n';

    cy.intercept('POST', '/api/v1/assessment/chat/CHAT-TEST-003/message', {
      statusCode: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: sseBody,
    });

    cy.visit('/assessment/chat');
    cy.get('[data-cy="chat-input"]').type('好的');
    cy.get('[data-cy="chat-send"]').click();

    cy.url().should('include', '/assessment/result');
    cy.contains('您的风险偏好');
    cy.contains('平衡型');
  });

  it('shows retry button on SSE error event', () => {
    cy.intercept('POST', '/api/v1/assessment/chat/start', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-004',
        resumed: false,
        messages: [
          { role: 'assistant', content: '开场白', created_at: new Date().toISOString() },
        ],
      },
    });

    cy.intercept('POST', '/api/v1/assessment/chat/CHAT-TEST-004/message', {
      statusCode: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: 'event: error\ndata: {"code":"llm_error","message":"AI 暂时无法响应"}\n\n',
    });

    cy.visit('/assessment/chat');
    cy.get('[data-cy="chat-input"]').type('hi');
    cy.get('[data-cy="chat-send"]').click();

    cy.get('[data-cy="chat-error"]').should('contain.text', 'AI 暂时无法响应');
    cy.get('[data-cy="chat-retry"]').should('be.visible');
  });

  it('restart button creates a new session', () => {
    cy.intercept('POST', '/api/v1/assessment/chat/start', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-005',
        resumed: false,
        messages: [
          { role: 'assistant', content: '第一次开场', created_at: new Date().toISOString() },
        ],
      },
    });

    cy.intercept('POST', '/api/v1/assessment/chat/CHAT-TEST-005/restart', {
      statusCode: 200,
      body: {
        session_code: 'CHAT-TEST-006',
        resumed: false,
        messages: [
          { role: 'assistant', content: '重新开始后的开场', created_at: new Date().toISOString() },
        ],
      },
    }).as('restart');

    cy.visit('/assessment/chat');
    cy.get('[data-cy="msg-assistant"]').should('contain.text', '第一次开场');
    cy.get('[data-cy="chat-restart"]').click();
    cy.wait('@restart');
    cy.get('[data-cy="msg-assistant"]').should('contain.text', '重新开始后的开场');
  });
});
