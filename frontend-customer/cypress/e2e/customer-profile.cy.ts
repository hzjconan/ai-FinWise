describe('Customer Profile', () => {
  beforeEach(() => {
    cy.createAnonymousCustomer();
  });

  it('shows customer code', () => {
    cy.visit('/profile');
    cy.contains('客户编号');
    cy.get('body').invoke('text').should('match', /CUS-/);
  });

  it('shows empty assessment history', () => {
    cy.visit('/profile');
    cy.contains('暂无评估记录');
  });

  it('shows empty favorites', () => {
    cy.visit('/profile');
    cy.contains('收藏').click();
    cy.contains('暂无收藏');
  });

  it('shows assessment history after completing one', () => {
    cy.seedQuestions();
    // Complete an assessment via API
    cy.window().then((win) => {
      const customerCode = win.localStorage.getItem('customer_code')!;
      cy.request('GET', '/api/v1/assessment/questions').then((resp) => {
        const questions = resp.body;
        const answers = questions.map((q: any) => ({
          question_id: q.id,
          option_id: q.options[0].id,
        }));
        cy.request('POST', '/api/v1/assessment/submit', {
          customer_code: customerCode,
          answers,
        });
      });
    });

    cy.visit('/profile');
    cy.contains('评估记录 (1)');
    cy.contains('问卷');
  });

  it('shows favorites after adding one', () => {
    cy.seedProduct('FAV-001', '收藏测试产品');
    cy.window().then((win) => {
      const customerCode = win.localStorage.getItem('customer_code')!;
      cy.request('POST', `/api/v1/customers/${customerCode}/favorites`, {
        product_code: 'FAV-001',
      });
    });

    cy.visit('/profile');
    cy.contains('收藏').click();
    cy.contains('收藏测试产品');
  });
});
