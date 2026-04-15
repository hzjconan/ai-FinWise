describe('Customer Product Browsing', () => {
  beforeEach(() => {
    cy.seedProduct('BROWSE-001', '浏览测试产品A');
    cy.seedProduct('BROWSE-002', '浏览测试产品B');
    cy.createAnonymousCustomer();
  });

  it('shows product list page', () => {
    cy.visit('/products');
    cy.contains('浏览测试产品A');
    cy.contains('浏览测试产品B');
  });

  it('views product detail', () => {
    cy.visit('/products/BROWSE-001');
    cy.contains('浏览测试产品A');
    cy.contains('债券');
  });

  it('adds and removes product from favorites', () => {
    cy.visit('/products/BROWSE-001');
    // Add to favorites
    cy.contains('button', '收藏').click();
    cy.get('.ant-message').should('contain.text', '已收藏');
    // Remove from favorites
    cy.contains('button', '已收藏').click();
    cy.get('.ant-message').should('contain.text', '已取消收藏');
  });
});
