describe('Admin Dashboard', () => {
  beforeEach(() => {
    cy.adminLogin();
    cy.visit('/dashboard');
  });

  it('shows product and question counts', () => {
    cy.contains('理财产品');
    cy.contains('评估题目');
    cy.get('[data-testid="dashboard-products-card"]').should('be.visible');
    cy.get('[data-testid="dashboard-questions-card"]').should('be.visible');
  });

  it('navigates to products list on products card click', () => {
    cy.get('[data-testid="dashboard-products-card"]').click();
    cy.url().should('include', '/products');
  });

  it('navigates to questionnaire list on questions card click', () => {
    cy.get('[data-testid="dashboard-questions-card"]').click();
    cy.url().should('include', '/questionnaire');
  });
});
