describe('Customer Home', () => {
  beforeEach(() => {
    cy.seedProduct('HOME-001', '首页测试产品');
  });

  it('shows home page with assessment CTA', () => {
    cy.visit('/');
    cy.contains('不知道该买什么理财产品');
    cy.contains('开始风险评估');
  });

  it('auto-creates anonymous customer', () => {
    cy.visit('/');
    // Wait for the auto-creation to complete
    cy.window().its('localStorage').invoke('getItem', 'customer_code')
      .should('match', /^CUS-/);
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
