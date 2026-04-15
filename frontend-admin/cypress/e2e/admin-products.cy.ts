describe('Admin Product Management', () => {
  beforeEach(() => {
    cy.adminLogin();
  });

  it('shows empty product list', () => {
    cy.visit('/products');
    cy.get('.ant-table').should('be.visible');
  });

  it('creates a new product', () => {
    const code = `E2E-${Date.now()}`;
    cy.visit('/products/new');
    cy.get('#product_code').type(code);
    cy.get('#name').type('E2E测试产品');
    cy.get('#type').click();
    cy.get('.ant-select-item-option').contains('债券').click();
    // Wait for dropdown to close
    cy.get('.ant-select-dropdown').should('not.be.visible');
    cy.get('#min_investment').type('10000');
    // Use the primary submit button
    cy.get('button.ant-btn-primary').first().click({ force: true });
    cy.contains('产品已创建');
    cy.url().should('include', '/products');
  });

  it('lists created product', () => {
    cy.seedProduct('LIST-001', '列表测试产品');
    cy.visit('/products');
    cy.contains('LIST-001');
    cy.contains('列表测试产品');
  });

  it('edits product details', () => {
    cy.seedProduct('EDIT-001', '编辑测试产品');
    cy.visit('/products/EDIT-001');
    cy.get('#name').should('be.visible').clear().type('已编辑产品');
    cy.get('button.ant-btn-primary').first().click({ force: true });
    cy.contains('产品已更新');
  });

  it('manages product status', () => {
    cy.seedProduct('STATUS-001', '状态测试产品');
    cy.visit('/products');
    cy.contains('tr', 'STATUS-001').within(() => {
      cy.contains('a', '下架').click();
    });
    cy.get('.ant-popconfirm').should('be.visible');
    cy.get('.ant-popconfirm-buttons .ant-btn-primary').click();
    cy.get('.ant-message').should('contain.text', '状态已更新');
  });
});
