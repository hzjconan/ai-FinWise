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

  it('sends sort params when clicking sortable column header', () => {
    cy.intercept('GET', '/api/v1/admin/products?*').as('list');
    cy.visit('/products');
    cy.wait('@list');
    cy.contains('.ant-table-column-title', '产品编号').click();
    cy.wait('@list').its('request.url').should('match', /sort_by=product_code.*sort_order=asc/);
    cy.contains('.ant-table-column-title', '产品编号').click();
    cy.wait('@list').its('request.url').should('match', /sort_by=product_code.*sort_order=desc/);
  });

  it('does not show sorter on 类型/风险等级/状态 columns', () => {
    cy.visit('/products');
    cy.contains('.ant-table-column-has-sorters', '产品编号').should('exist');
    cy.contains('.ant-table-column-has-sorters', '名称').should('exist');
    cy.contains('.ant-table-column-has-sorters', '期望收益').should('exist');
    cy.contains('.ant-table-column-has-sorters', '类型').should('not.exist');
    cy.contains('.ant-table-column-has-sorters', '风险等级').should('not.exist');
    cy.contains('.ant-table-column-has-sorters', '状态').should('not.exist');
  });

  it('paginates to page 2 with single API call and renders page 2 rows', () => {
    // 种够 >10 条以产生第 2 页
    for (let i = 0; i < 12; i += 1) {
      cy.seedProduct(`PAG-${String(i).padStart(3, '0')}`, `分页测试${i}`);
    }
    const calls: string[] = [];
    cy.intercept('GET', '/api/v1/admin/products?*', (req) => {
      calls.push(req.url);
    }).as('list');
    cy.visit('/products');
    cy.wait('@list');
    cy.get('.ant-pagination-item-2').click();
    cy.wait('@list').its('request.url').should('include', 'page=2');
    cy.get('.ant-pagination-item-2').should('have.class', 'ant-pagination-item-active');
    // 只应新增 1 条翻页请求（首次 + 翻页 = 2 次）
    cy.wait(500).then(() => {
      const page2Calls = calls.filter((u) => /[?&]page=2(&|$)/.test(u));
      expect(page2Calls.length, 'page=2 API call count').to.eq(1);
    });
  });

  it('sends risk_level query param when filter selected', () => {
    cy.intercept('GET', '/api/v1/admin/products?*').as('list');
    cy.visit('/products');
    cy.wait('@list');
    cy.get('.ant-select-selection-placeholder').contains('风险等级').click();
    cy.get('.ant-select-dropdown:visible').contains('R2').click();
    cy.wait('@list').its('request.url').should('include', 'risk_level=R2');
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
