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
    cy.get('.ant-modal').find('input[role="spinbutton"]').first().clear().type('1');

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
