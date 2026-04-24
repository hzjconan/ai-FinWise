describe('Customer Risk Assessment', () => {
  beforeEach(() => {
    cy.seedQuestions();
    cy.seedProduct('REC-001', '推荐测试产品');
    cy.createAnonymousCustomer();
  });

  it('shows assessment questions', () => {
    cy.visit('/assessment/questionnaire');
    cy.contains('第 1 /');
  });

  it('navigates between questions', () => {
    cy.visit('/assessment/questionnaire');
    cy.get('.ant-radio-wrapper').first().click();
    cy.contains('button', '下一题').click();
    cy.contains('第 2 /');
    cy.contains('button', '上一题').click();
    cy.contains('第 1 /');
  });

  it('requires selection before proceeding', () => {
    cy.visit('/assessment/questionnaire');
    cy.contains('button', '下一题').click();
    cy.get('.ant-message').should('contain.text', '请选择一个选项');
  });

  it('completes full assessment flow', () => {
    // Get question count first
    cy.request('GET', '/api/v1/assessment/questions').then((resp) => {
      const questionCount = resp.body.length;

      cy.visit('/assessment/questionnaire');
      // Answer all questions except the last one
      for (let i = 0; i < questionCount - 1; i++) {
        cy.get('.ant-radio-wrapper').first().click();
        cy.contains('button', '下一题').click();
      }
      // Answer and submit the last question
      cy.get('.ant-radio-wrapper').first().click();
      cy.contains('button', '提交评估').click();

      cy.url().should('include', '/assessment/result');
      cy.contains('您的风险偏好');
    });
  });
});
