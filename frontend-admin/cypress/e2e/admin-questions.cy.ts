describe('Admin Question Management', () => {
  beforeEach(() => {
    cy.adminLogin();
    cy.visit('/questionnaire');
  });

  it('shows question management page', () => {
    cy.contains('问卷管理');
    cy.contains('新增题目');
  });

  it('creates a new question with options', () => {
    cy.contains('新增题目').click();
    cy.get('.ant-modal').should('be.visible');

    cy.get('.ant-modal textarea').type('您能承受多大的投资损失？');

    cy.get('.ant-modal').find('input[placeholder="选项内容"]').first().type('10%以内');
    cy.get('.ant-modal').find('input[placeholder="分值"]').first().clear().type('1');

    cy.get('.ant-modal').contains('+ 添加选项').click();
    cy.get('.ant-modal').find('input[placeholder="选项内容"]').last().type('30%以内');
    cy.get('.ant-modal').find('input[placeholder="分值"]').last().clear().type('3');

    cy.get('.ant-modal .ant-btn-primary').click();
    cy.get('.ant-message').should('contain.text', '题目已创建');
  });

  it('lists questions', () => {
    cy.seedQuestions();
    cy.visit('/questionnaire');
    // Should have at least 1 question displayed
    cy.get('.ant-card').should('have.length.at.least', 1);
  });

  it('shows preview drawer with all questions in customer view', () => {
    cy.seedQuestions();
    cy.visit('/questionnaire');
    cy.get('[data-cy="preview-btn"]').click();
    cy.get('[data-cy="preview-drawer"]').should('be.visible');
    cy.get('[data-cy="preview-drawer"]').contains('客户视角');
    // 抽屉里至少渲染了 1 道题（含客户端 Radio 选项）
    cy.get('[data-cy="preview-drawer"] .ant-radio-group').its('length').should('be.gte', 1);
  });

  it('preview button is disabled when no questions exist', () => {
    cy.intercept('GET', '/api/v1/admin/questions', { statusCode: 200, body: [] }).as('emptyList');
    cy.visit('/questionnaire');
    cy.wait('@emptyList');
    cy.get('[data-cy="preview-btn"]').should('be.disabled');
  });

  it('drag handle is rendered for sorting', () => {
    cy.seedQuestions();
    cy.visit('/questionnaire');
    // 每个题目卡片都应有可拖拽的把手
    cy.get('[data-cy^="drag-handle-"]').its('length').should('be.gte', 1);
    cy.get('[data-cy^="drag-handle-"]').first().should('have.attr', 'draggable', 'true');
  });

  it('updates sort order via API when reordering', () => {
    cy.intercept('PUT', '/api/v1/admin/questions/sort').as('sortApi');
    cy.seedQuestions();
    cy.visit('/questionnaire');

    // HTML5 drag 在 Cypress 中触发不可靠；这里直接通过组件回调间接验证。
    // 模拟拖拽：手动构造 dragstart / drop 事件序列，由组件 onDrop 派发 API 调用
    cy.get('[data-cy^="drag-handle-"]').then(($handles) => {
      if ($handles.length < 2) return; // 至少需要 2 题
      cy.wrap($handles[0]).trigger('dragstart');
      cy.get('[data-cy^="question-card-"]').eq(1).trigger('dragover').trigger('drop');
      cy.wait('@sortApi').its('request.body.orders').should('have.length', $handles.length);
    });
  });

  it('deletes a question', () => {
    cy.seedQuestions();
    cy.visit('/questionnaire');
    cy.get('.ant-card').then(($cards) => {
      const countBefore = $cards.length;
      cy.get('.ant-btn-dangerous').first().click();
      cy.get('.ant-popconfirm').should('be.visible');
      cy.get('.ant-popconfirm-buttons .ant-btn-primary').click();
      cy.get('.ant-message').should('contain.text', '题目已删除');
      cy.get('.ant-card').should('have.length', countBefore - 1);
    });
  });
});
