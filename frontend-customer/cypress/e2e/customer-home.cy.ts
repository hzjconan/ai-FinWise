describe('Customer Home', () => {
  beforeEach(() => {
    cy.seedProduct('HOME-001', '首页测试产品');
  });

  it('shows home page with assessment CTA', () => {
    cy.visit('/');
    cy.contains('不知道该买什么理财产品');
    cy.contains('开始风险评估');
  });

  it('auto-creates anonymous customer only once', () => {
    cy.intercept('POST', '/api/v1/auth/customer/anonymous').as('createCustomer');
    cy.visit('/');
    // Wait for the auto-creation to complete
    cy.window().its('localStorage').invoke('getItem', 'customer_code')
      .should('match', /^CUS-/);
    // 确保匿名客户创建 API 只被调用了一次（防止 StrictMode 双重执行）
    cy.get('@createCustomer.all').should('have.length', 1);
  });

  it('recovers from stale customer_code in localStorage', () => {
    // 模拟 localStorage 中残留了一个后端已不存在的 customer_code
    window.localStorage.setItem('customer_code', 'CUS-STALE-999');

    cy.intercept('POST', '/api/v1/auth/customer/anonymous').as('createCustomer');
    cy.visit('/');

    // 应自动检测到旧 code 无效，清除并重新创建
    cy.wait('@createCustomer');
    cy.window().its('localStorage').invoke('getItem', 'customer_code')
      .should('match', /^CUS-/)
      .and('not.eq', 'CUS-STALE-999');
  });

  it('shows product list', () => {
    cy.visit('/');
    cy.contains('热门产品');
    cy.contains('首页测试产品');
  });

  it('navigates to product detail', () => {
    cy.visit('/');
    cy.contains('首页测试产品').click();
    cy.url().should('include', '/products/HOME-001');
  });

  it('navigates to full product list', () => {
    cy.visit('/');
    cy.contains('查看全部产品').click();
    cy.url().should('include', '/products');
  });
});
